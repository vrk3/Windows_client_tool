"""CMTrace-style log viewer.

Opens any log file, colours it by severity, follows it as it grows, and lets
you filter and search it. Unlike the CBS and DISM viewers, which point at
fixed system paths, this one reads whatever you hand it -- which is why it is
its own module rather than another tab in the Diagnose hub.

Reading and parsing run on the UI thread deliberately. `LogReader` caps a
first read at a few megabytes and every later read is only what was appended,
so the work per tick is small and bounded; a worker thread would buy nothing
and cost the marshalling.
"""
import logging
import os
from datetime import timedelta
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QDateTime
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton,
    QSplitter, QTableView, QToolButton, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider

from modules.log_viewer import cmtrace_parser
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.log_model import (
    COMPONENT, LogModel, MESSAGE, SEVERITY, THREAD, TIME,
)
from modules.log_viewer.log_reader import LogReader
from modules.log_viewer.log_search_provider import LogSearchProvider

logger = logging.getLogger(__name__)

#: How often a followed file is checked. Fast enough to feel live, slow
#: enough that a busy log does not repaint the table continuously.
FOLLOW_MS = 1000

LEVELS = ("Error", "Warning", "Info")


class LogViewerWidget(QWidget):
    #: Offered on a row. Five minutes is the default because a servicing
    #: operation's related lines land within seconds of each other; the
    #: wider ones are for correlating across a reboot.
    RANGE_MINUTES = (1, 5, 15, 60)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = LogModel(self)
        self.provider = LogSearchProvider()
        self._reader: Optional[LogReader] = None
        self._path = ""
        self._last_found = -1
        self._lookup = None
        self._rules = []
        self._config = None
        # Whether the user has actually asked for a time range. The boxes
        # always HOLD a value (the log's whole span, or whatever
        # anchor_range/a manual edit set), but _apply_filters must not send
        # it to the model unless this is True -- otherwise "Clear range"
        # is undone by the next touch of any other control, and while
        # following, the upper bound is frozen at the moment the log was
        # opened, so new lines (later than that bound) silently stop
        # appearing.
        self._range_active = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        top = QHBoxLayout()
        # A split button: pressing it browses, the arrow lists the logs this
        # machine actually has. Same idea as TreeSize's scan target -- offer
        # somewhere to go rather than making someone type a path.
        self.open_button = QToolButton(self)
        self.open_button.setText("Open log…")
        self.open_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.open_button.clicked.connect(self.choose_file)
        self.open_menu = QMenu(self.open_button)
        self.open_button.setMenu(self.open_menu)
        self._build_open_menu()
        top.addWidget(self.open_button)

        self.follow = QCheckBox("Follow", self)
        self.follow.setToolTip("Re-read the file as it grows and stay at the "
                               "bottom, the way CMTrace does.")
        self.follow.toggled.connect(self._on_follow_toggled)
        top.addWidget(self.follow)

        # CSI writes operation lists that run to 1,260 continuation lines
        # under one record, and 9,185 of the big CBS archive's 90,714 rows
        # are continuations. Folded by default, because a log you have to
        # scroll past is a log you stop reading -- and the parent's
        # "(+N lines)" suffix and the status bar both say what is hidden.
        self.fold = QCheckBox("Fold continuations", self)
        self.fold.setChecked(True)
        self.fold.setToolTip("Tuck wrapped continuation lines under the "
                             "record they belong to.")
        self.fold.toggled.connect(self._on_fold_toggled)
        top.addWidget(self.fold)

        self.rolled = QCheckBox("Include rolled (.lo_)", self)
        self.rolled.setToolTip("ConfigMgr rolls foo.log to foo.lo_ . Read the "
                               "pair as one timeline.")
        self.rolled.toggled.connect(lambda _c: self.reload())
        top.addWidget(self.rolled)

        top.addSpacing(12)
        self._level_boxes = {}
        for level in LEVELS:
            box = QCheckBox(level, self)
            box.setChecked(True)
            box.toggled.connect(lambda _c: self._apply_filters())
            self._level_boxes[level] = box
            top.addWidget(box)

        top.addSpacing(12)
        top.addWidget(QLabel("Component:", self))
        self.component = QComboBox(self)
        self.component.setMinimumWidth(160)
        self.component.addItem("All")
        self.component.currentIndexChanged.connect(lambda _i: self._apply_filters())
        top.addWidget(self.component)
        top.addStretch(1)
        layout.addLayout(top)

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("Find:", self))
        self.find_box = QLineEdit(self)
        self.find_box.setPlaceholderText("text to look for")
        self.find_box.returnPressed.connect(self.find_next)
        find_row.addWidget(self.find_box, 1)
        self.previous_button = QPushButton("Previous", self)
        self.previous_button.clicked.connect(self.find_previous)
        find_row.addWidget(self.previous_button)
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.find_next)
        find_row.addWidget(self.next_button)

        # Find JUMPS to the next match and leaves everything on screen.
        # Filter HIDES everything that does not match. Two different jobs, so
        # two boxes -- the previous "Show only matches" checkbox shared Find's
        # text and only re-applied when it was toggled, so editing the text
        # afterwards silently did nothing.
        find_row.addSpacing(16)
        find_row.addWidget(QLabel("Filter:", self))
        self.filter_box = QLineEdit(self)
        self.filter_box.setPlaceholderText(
            "show only lines containing… (case insensitive)")
        self.filter_box.setClearButtonEnabled(True)
        self.filter_box.textChanged.connect(lambda _t: self._apply_filters())
        find_row.addWidget(self.filter_box, 1)
        layout.addLayout(find_row)

        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Thread:", self))
        # Editable with a completer, not a plain dropdown: DISM carries 329
        # distinct thread ids, and an alphabetical list of 329 numbers is not
        # a control anyone can use. Ordered by how common each one is.
        self.thread = QComboBox(self)
        self.thread.setEditable(True)
        self.thread.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.thread.setMinimumWidth(140)
        self.thread.addItem("All")
        self.thread.currentIndexChanged.connect(lambda _i: self._apply_filters())
        range_row.addWidget(self.thread)

        range_row.addSpacing(12)
        range_row.addWidget(QLabel("From:", self))
        self.time_from = QDateTimeEdit(self)
        self.time_from.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        # Only a genuine user edit reaches this slot: both programmatic
        # writers (_reset_range, anchor_range) already blockSignals() around
        # setDateTime(). A real edit is what turns the range on.
        self.time_from.dateTimeChanged.connect(self._on_range_edited)
        range_row.addWidget(self.time_from)
        range_row.addWidget(QLabel("To:", self))
        self.time_to = QDateTimeEdit(self)
        self.time_to.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.time_to.dateTimeChanged.connect(self._on_range_edited)
        range_row.addWidget(self.time_to)
        self.clear_range_button = QPushButton("Clear range", self)
        self.clear_range_button.clicked.connect(self._reset_range)
        range_row.addWidget(self.clear_range_button)

        self.export_button = QPushButton("Export…", self)
        self.export_button.clicked.connect(self.choose_export)
        range_row.addWidget(self.export_button)

        self.error_lookup_button = QPushButton("Error lookup…", self)
        self.error_lookup_button.clicked.connect(
            lambda _c=False: self.open_error_lookup())
        range_row.addWidget(self.error_lookup_button)

        self.highlight_button = QPushButton("Highlight rules…", self)
        self.highlight_button.clicked.connect(self.edit_highlight_rules)
        range_row.addWidget(self.highlight_button)

        range_row.addSpacing(12)
        self.regex_box = QCheckBox("Regex", self)
        self.regex_box.setToolTip("Treat Find and Filter as regular "
                                  "expressions.")
        self.regex_box.toggled.connect(lambda _c: self._apply_filters())
        range_row.addWidget(self.regex_box)
        range_row.addStretch(1)
        layout.addLayout(range_row)

        self.table = QTableView(self)
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.setShowGrid(False)
        self.table.setFont(QFont("Consolas", 9))
        self.table.setWordWrap(False)
        # Message takes whatever is left; without this every column sits at
        # its default width and the text is crammed into the left third of
        # the window with two thirds empty beside it.
        header = self.table.horizontalHeader()
        for column in (TIME, SEVERITY, COMPONENT, THREAD):
            header.setSectionResizeMode(column,
                                        QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(MESSAGE, QHeaderView.ResizeMode.Stretch)

        from .log_delegate import LogMessageDelegate

        self.table.setItemDelegateForColumn(MESSAGE, LogMessageDelegate(self))

        # Message is a Stretch section, so the table has no horizontal scroll
        # bar to reach a clipped line with -- measured on a real CBS archive,
        # 3,998 of 4,000 sampled rows were elided and the tooltip was the
        # only way to read one. Scrolling would not have helped either: those
        # rows are up to 2,751px wide. CMTrace uses a detail pane; so does
        # this. Collapsible and visible by default, so dragging it shut is
        # the setting rather than something to store.
        self.detail = QPlainTextEdit(self)
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 9))
        self.detail.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.detail.setPlaceholderText(
            "Select a row to read the whole line here.")

        self.splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.splitter.addWidget(self.table)
        self.splitter.addWidget(self.detail)
        self.splitter.setChildrenCollapsible(True)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([600, 160])
        layout.addWidget(self.splitter, 1)

        self.status = QLabel("No log open.", self)
        self.status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)

        self.table.selectionModel().currentRowChanged.connect(
            self._on_row_selected)

        self.table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)

        from PyQt6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence.StandardKey.Copy, self.table,
                  activated=self.copy_selection)

        self._timer = QTimer(self)
        self._timer.setInterval(FOLLOW_MS)
        self._timer.timeout.connect(self._poll)

    # ---- opening --------------------------------------------------------

    def _build_open_menu(self) -> None:
        """The logs present on this machine, plus Browse.

        Rebuilt rather than cached: a ConfigMgr client can be installed, and
        CBS rolls into new archives, between one opening of the menu and the
        next.
        """
        from .known_logs import known_logs, newest_cbs_archive

        self.open_menu.clear()
        for log in known_logs():
            self.open_menu.addAction(
                log.label, lambda _c=False, p=log.path: self.open(p))
        archive = newest_cbs_archive()
        if archive:
            self.open_menu.addSeparator()
            self.open_menu.addAction(
                "CBS — newest rolled archive",
                lambda _c=False, p=archive: self.open(p))
        self.open_menu.addSeparator()
        self.open_menu.addAction("Browse…", self.choose_file)

    def choose_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, "Open log", "",
            "Logs (*.log *.lo_ *.txt);;All files (*)")
        if path:
            self.open(path)

    def open(self, path: str) -> None:
        self._path = path
        self.reload()

    def reload(self) -> None:
        """Start again from the beginning of the current file."""
        if not self._path:
            return
        self.model.clear()
        self.detail.clear()
        self._reader = LogReader(self._path,
                                 include_rolled=self.rolled.isChecked())
        self._poll(scroll=True)
        self._refresh_components()
        self._refresh_threads()
        self._reset_range()
        # The refreshes above blockSignals() around rebuilding the Component
        # and Thread combos, so falling back to index 0 ("All") when the
        # previous log's selection is not in the new one never told the
        # model -- it kept filtering on a component/thread that belonged to
        # the log that is no longer open. One unblocked call here is what
        # guarantees the widgets and the model agree. Safe to combine with
        # _reset_range just above: _range_active is False at this point, so
        # this does not re-introduce the frozen-range bug that flag exists
        # to prevent.
        self._apply_filters()

    def _poll(self, scroll: bool = None) -> None:
        if self._reader is None:
            return
        try:
            text = self._reader.read_new()
        except Exception as exc:                    # noqa: BLE001
            logger.warning("Could not read %s", self._path, exc_info=True)
            self.status.setText(f"Could not read the log: {exc}")
            return
        if text:
            self.model.append(cmtrace_parser.parse(text))
            self.provider.set_entries(self.model._entries,
                                      os.path.basename(self._path))
        if scroll or (scroll is None and self.follow.isChecked()):
            self.table.scrollToBottom()
        self._update_status()

    def _update_status(self) -> None:
        if not self._path:
            self.status.setText("No log open.")
            return
        parts = [os.path.basename(self._path),
                 f"{self.model.rowCount():,} shown of {self.model.total:,}"]
        if self.model.dropped:
            # Saying so matters: silently showing the last 200k lines of a
            # 900k-line log is how someone concludes the log is clean.
            parts.append(f"{self.model.dropped:,} older records dropped")
        folded = self.model.folded_count()
        if folded:
            # Same reason. These records are one click away rather than gone,
            # but the count still has to be visible.
            parts.append(f"{folded:,} continuation lines folded")
        if self._reader is not None and self._reader.truncated:
            parts.append("opened at the tail of a large file")
        self.status.setText("  |  ".join(parts))

    def _on_row_selected(self, current, _previous) -> None:
        """Show the whole selected record, and spell out its error codes.

        This used to overwrite the status line, which is where the file name
        and the record counts live -- so clicking a row threw away the one
        piece of text saying how much of the log was on screen.
        """
        entry = self.model.entry(current.row()) if current.isValid() else None
        if entry is None:
            self.detail.clear()
            return
        from .error_codes import explain

        stamp = self.model.data(self.model.index(current.row(), TIME)) or "—"
        head = [f"{stamp}   {entry.level}"]
        if entry.source:
            head.append(entry.source)
        thread = entry.raw.get("thread", "")
        if thread:
            head.append(f"thread {thread}")
        if entry.raw.get("continuation"):
            head.append("(continuation of the record above)")

        parts = ["   |   ".join(head), "", entry.message]
        found = explain(entry.message)
        if found:
            parts.append("")
            parts.extend(f"{code} — {meaning}" for code, meaning in found)
        self.detail.setPlainText("\n".join(parts))

    # ---- context menu and actions -------------------------------------------

    def anchor_range(self, row: int, minutes: int) -> None:
        """Set the time range to ±minutes around the timestamp of the given row."""
        entry = self.model.entry(row)
        if entry is None or entry.timestamp == UNKNOWN_TIME:
            return
        span = timedelta(minutes=minutes)
        self.time_from.blockSignals(True)
        self.time_to.blockSignals(True)
        self.time_from.setDateTime(QDateTime(entry.timestamp - span))
        self.time_to.setDateTime(QDateTime(entry.timestamp + span))
        self.time_from.blockSignals(False)
        self.time_to.blockSignals(False)
        self._range_active = True
        self._apply_filters()

    def _on_range_edited(self, _new_value) -> None:
        """A genuine user edit of either box -- see the comment on the
        connect() calls. This is what turns the range on."""
        self._range_active = True
        self._apply_filters()

    def build_row_menu(self, row: int) -> QMenu:
        """Build the context menu for a row."""
        menu = QMenu(self)
        for minutes in self.RANGE_MINUTES:
            menu.addAction(
                f"Show ±{minutes} minute{'s' if minutes > 1 else ''} "
                f"around this row",
                lambda _c=False, m=minutes: self.anchor_range(row, m))
        menu.addSeparator()
        menu.addAction("Look up the error codes on this row",
                       lambda _c=False: self.open_error_lookup(row))
        menu.addAction("Copy selected rows", self.copy_selection)
        return menu

    def _on_context_menu(self, point) -> None:
        """Handle right-click on the table."""
        index = self.table.indexAt(point)
        if index.isValid():
            self.build_row_menu(index.row()).exec(
                self.table.viewport().mapToGlobal(point))

    def open_error_lookup(self, row: int = -1) -> None:
        from .error_lookup_dialog import ErrorLookupDialog

        if self._lookup is None:
            self._lookup = ErrorLookupDialog(self)
        entry = self.model.entry(row) if row >= 0 else None
        self._lookup.show_for(entry.message if entry is not None else "")

    def edit_highlight_rules(self) -> None:
        from .highlight import save_rules
        from .highlight_dialog import HighlightDialog

        dialog = HighlightDialog(self._rules, self)
        if dialog.exec():
            self._rules = dialog.rules()
            self.model.set_highlight_rules(self._rules)
            if self._config is not None:
                save_rules(self._config, self._rules)

    def _on_fold_toggled(self, folded: bool) -> None:
        self.model.set_folding(folded)
        self._update_status()

    def _sync_fold_box(self) -> None:
        """Keep the checkbox honest: `find` unfolds to reach a match, and a
        box that still read "folded" would be lying about the view."""
        if self.fold.isChecked() != self.model.is_folding():
            self.fold.blockSignals(True)
            self.fold.setChecked(self.model.is_folding())
            self.fold.blockSignals(False)

    def visible_entries(self) -> list:
        """What the filter left, in view order -- folding deliberately ignored.

        A folded continuation is hidden for reading, not excluded by the
        user, so an export that dropped it would lose a tenth of a real CBS
        archive without saying so. Every other filter still applies.
        """
        return self.model.rows_for_export()

    def copy_selection(self) -> None:
        """Copy selected rows to clipboard without provenance header."""
        rows = sorted({index.row()
                       for index in self.table.selectionModel().selectedRows()}
                      or {self.table.currentIndex().row()})
        entries = [self.model.entry(row) for row in rows
                   if self.model.entry(row) is not None]
        if not entries:
            return
        from .log_export import as_text
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(as_text(entries, header=False))
        self.status.setText(f"{len(entries):,} row(s) copied.")

    def export_to(self, path: str) -> None:
        """Export the filtered view to a file (CSV or text).

        Writes to a temporary file beside the target, then atomically replaces
        the destination. This ensures the destination is never truncated or
        left in a partial state if the write fails.
        """
        import tempfile
        from .log_export import as_csv, as_text

        entries = self.visible_entries()
        text = (as_csv(entries) if path.lower().endswith(".csv")
                else as_text(entries))

        # Create a temporary file in the same directory as the target to ensure
        # os.replace() stays on the same volume (atomic on Windows).
        target_dir = os.path.dirname(path)
        if not target_dir:
            target_dir = "."

        temp_fd = None
        temp_path = None
        try:
            # Create temp file in the same directory as the target
            temp_fd, temp_path = tempfile.mkstemp(
                dir=target_dir,
                prefix=".export_",
                suffix=os.path.splitext(path)[1])

            # Write to the temp file
            with os.fdopen(temp_fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)

            # Atomically replace the target with the temp file
            os.replace(temp_path, path)
        except OSError as exc:
            logger.warning("Could not export to %s", path, exc_info=True)
            self.status.setText(f"Could not write the export: {exc}")
            # Clean up the temp file if it was created
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    # Best-effort cleanup; the original export failure above
                    # is already reported, and this is not another one.
                    logger.debug("Could not remove temp export file %s",
                                temp_path, exc_info=True)
            return

        self.status.setText(f"{len(entries):,} row(s) written to "
                            f"{os.path.basename(path)}")

    def choose_export(self) -> None:
        """Open a file dialog to choose where to export the filtered view."""
        path, _filter = QFileDialog.getSaveFileName(
            self, "Export the filtered view", "",
            "Text (*.txt);;CSV (*.csv)")
        if path:
            self.export_to(path)

    # ---- filtering and find ---------------------------------------------

    def _refresh_components(self) -> None:
        current = self.component.currentText()
        self.component.blockSignals(True)
        self.component.clear()
        self.component.addItem("All")
        for name in self.model.components():
            self.component.addItem(name)
        index = self.component.findText(current)
        self.component.setCurrentIndex(max(0, index))
        self.component.blockSignals(False)

    def _refresh_threads(self) -> None:
        current = self.thread.currentText()
        self.thread.blockSignals(True)
        self.thread.clear()
        self.thread.addItem("All")
        for thread, count in self.model.threads():
            self.thread.addItem(f"{thread}  ({count:,})")
        index = self.thread.findText(current)
        self.thread.setCurrentIndex(max(0, index))
        self.thread.blockSignals(False)

    def _reset_range(self) -> None:
        """Open the boxes on the whole log, and stop filtering by time."""
        span = self.model.time_span()
        for box, value in ((self.time_from, span[0] if span else None),
                           (self.time_to, span[1] if span else None)):
            box.blockSignals(True)
            if value is not None:
                box.setDateTime(QDateTime(value))
            box.blockSignals(False)
        self._range_active = False
        self.model.set_filter(time_from=False, time_to=False)
        self._update_status()

    def _apply_filters(self) -> None:
        checked = {level for level, box in self._level_boxes.items()
                   if box.isChecked()}
        # All boxes ticked means no filtering at all, rather than a set that
        # happens to list every level -- Debug records would vanish otherwise.
        levels = set() if checked == set(LEVELS) else checked
        component = self.component.currentText()
        thread = self.thread.currentText()
        thread = "" if thread == "All" else thread.split(" ")[0]
        # The boxes always hold a value -- the log's whole span, or
        # whatever anchor_range/a manual edit set -- but that must reach
        # the model only once the user has actually asked for a range.
        # Otherwise every OTHER control (Filter, a severity box, Component,
        # Thread, Regex) re-sends time_from/time_to on every call, undoing
        # "Clear range", and while following, the upper bound is frozen at
        # the moment the log was opened so newer lines never appear.
        time_from: object = False
        time_to: object = False
        if self._range_active:
            # A backwards range would hide every row, and an empty table
            # reads as "no such records" -- a lie about the log rather than
            # a complaint about the range. Say so and filter nothing.
            start = self.time_from.dateTime().toPyDateTime()
            end = self.time_to.dateTime().toPyDateTime()
            if start > end:
                self.model.set_filter(time_from=False, time_to=False)
                self.status.setText("That time range ends before it starts.")
                return
            time_from, time_to = start, end
        self.model.set_filter(
            levels=levels,
            needle=self.filter_box.text(),
            component="" if component == "All" else component,
            thread=thread,
            time_from=time_from,
            time_to=time_to,
            regex=self.regex_box.isChecked())
        if self.model.filter_pattern_is_invalid():
            self.status.setText("That pattern is not finished yet.")
            return
        self._update_status()

    def find_next(self) -> None:
        self._find(forwards=True)

    def find_previous(self) -> None:
        self._find(forwards=False)

    def _find(self, forwards: bool) -> None:
        needle = self.find_box.text().strip()
        if not needle:
            return
        start = self.table.currentIndex().row()
        if start < 0:
            start = 0 if forwards else self.model.rowCount()
        row = self.model.find(needle, start_row=start, forwards=forwards)
        # `find` unfolds to reach a match it would otherwise have missed, so
        # the checkbox has to be told what happened to it.
        self._sync_fold_box()
        if row < 0:
            self.status.setText(f"No match for {needle!r}.")
            return
        index = self.model.index(row, MESSAGE)
        self.table.setCurrentIndex(index)
        self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    # ---- following ------------------------------------------------------

    def _on_follow_toggled(self, following: bool) -> None:
        if following and self._path:
            self._timer.start()
        else:
            self._timer.stop()

    def stop(self) -> None:
        self._timer.stop()


class LogViewerModule(BaseModule):
    name = "Log Viewer"
    icon = "📄"
    description = "CMTrace-style viewer for ConfigMgr and plain text logs"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE

    def __init__(self) -> None:
        super().__init__()
        self._widget: Optional[LogViewerWidget] = None
        self._provider = LogSearchProvider()

    def create_widget(self) -> QWidget:
        self._widget = LogViewerWidget()
        self._provider = self._widget.provider
        config = getattr(self.app, "config", None) if self.app else None
        if config is not None:
            from .highlight import load_rules

            self._widget._config = config
            self._widget._rules = load_rules(config)
            self._widget.model.set_highlight_rules(self._widget._rules)
        return self._widget

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._provider

    def on_deactivate(self) -> None:
        # Following holds a timer and re-reads a file nobody is looking at.
        if self._widget is not None:
            self._widget.stop()

    def on_stop(self) -> None:
        self.on_deactivate()

    def get_status_info(self) -> str:
        if self._widget is None or not self._widget._path:
            return "No log open"
        return (f"{os.path.basename(self._widget._path)} — "
                f"{self._widget.model.total:,} records")
