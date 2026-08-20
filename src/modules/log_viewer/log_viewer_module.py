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
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QTableView,
    QToolButton, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider

from modules.log_viewer import cmtrace_parser
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
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.model = LogModel(self)
        self.provider = LogSearchProvider()
        self._reader: Optional[LogReader] = None
        self._path = ""
        self._last_found = -1

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
        layout.addWidget(self.table, 1)

        self.status = QLabel("No log open.", self)
        self.status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)

        self.table.selectionModel().currentRowChanged.connect(
            self._on_row_selected)

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
        self._reader = LogReader(self._path,
                                 include_rolled=self.rolled.isChecked())
        self._poll(scroll=True)
        self._refresh_components()

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
        if self._reader is not None and self._reader.truncated:
            parts.append("opened at the tail of a large file")
        self.status.setText("  |  ".join(parts))

    def _on_row_selected(self, current, _previous) -> None:
        """Spell out any error codes on the selected line.

        The tooltip carries the same thing, but a tooltip has to be
        discovered; the status bar is already where this widget talks.
        """
        entry = self.model.entry(current.row()) if current.isValid() else None
        if entry is None:
            return
        from .error_codes import explain

        found = explain(entry.message)
        if found:
            self.status.setText("   ".join(f"{code} — {meaning}"
                                           for code, meaning in found))
        else:
            self._update_status()

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

    def _apply_filters(self) -> None:
        checked = {level for level, box in self._level_boxes.items()
                   if box.isChecked()}
        # All boxes ticked means no filtering at all, rather than a set that
        # happens to list every level -- Debug records would vanish otherwise.
        levels = set() if checked == set(LEVELS) else checked
        component = self.component.currentText()
        self.model.set_filter(
            levels=levels,
            needle=self.filter_box.text(),
            component="" if component == "All" else component)
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
