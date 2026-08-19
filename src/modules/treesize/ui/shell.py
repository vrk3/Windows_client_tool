"""The TreeSize pane: ribbon, nav bar, panes, status bar (spec 5.1).

Layout, top to bottom:

    ribbon (tabs + active page)
    nav bar: ◂ ▸ ▴ | path combo | ▶ | scan overview
    splitter: [ directory tree / drive list ] | [ view tabs ]
    status bar

The chart is a view in the right-hand tab strip, not a separate panel; the
Drive List, scan overview and status bar are each individually toggleable from
the View tab, as in Pro.

The shell owns wiring and no scanning: it hands a target to a Worker and turns
results into widget state. That keeps the whole file readable and means the
engine stays testable without a display.
"""
from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QMessageBox, QPushButton, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ..scan.filters import FilterSet
from ..store.aggregates import AggregateCache
from ..store.node_store import EXCLUDED
from .backstage import Backstage, FindResults, TitleRow
from .context_menu import RowActions
from .directory_tree import DirectoryTree
from .formatting import Mode, Unit
from .panels import DriveList, ScanOverview, TreeSizeStatusBar, drive_space
from .ribbon import Ribbon
from .scan_worker import ScanWorker
from .views.chart import ChartView
from .views.details import DetailsView
from .views.tables import (
    AgeView, ExtensionsView, FileGroupsView, TopFilesView, UsersView,
)

MODE_ACTIONS = {
    "mode.size": Mode.SIZE,
    "mode.allocated": Mode.ALLOCATED,
    "mode.files": Mode.FILES,
    "mode.percent": Mode.PERCENT,
}
UNIT_ACTIONS = {
    "unit.auto": Unit.AUTO, "unit.tb": Unit.TB, "unit.gb": Unit.GB,
    "unit.mb": Unit.MB, "unit.kb": Unit.KB, "unit.b": Unit.B,
}
# The right-hand tab strip, in the product's order. The chart is a VIEW here,
# not a separate panel -- that is spec 5.1's arrangement and the thing most
# clones get wrong.
VIEW_TABS = ("Chart", "Details", "Extensions", "File groups", "Users",
             "Age of Files", "Top Files")


class TreeSizeShell(QWidget):
    scan_finished = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._store = None
        self._root = -1
        self._result = None
        self._worker: ScanWorker | None = None
        self._filters = FilterSet()
        self.row_actions = RowActions(self)
        self._paused = False
        self._pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.ribbon = Ribbon(self)
        self.title_row = TitleRow(self.ribbon, self)
        layout.addWidget(self.title_row)
        layout.addWidget(self.ribbon)

        self.find_results = FindResults(self.ribbon, self)
        layout.addWidget(self.find_results)

        # The File tab opens a full-pane page, not a dropdown. It replaces the
        # whole body rather than sitting inside it, which is what "backstage"
        # means in a ribbon application.
        self.backstage = Backstage(self)
        self.backstage.hide()
        layout.addWidget(self.backstage, 1)

        self.nav_bar = self._build_nav_bar()
        layout.addWidget(self.nav_bar)

        self.scan_overview = ScanOverview(self)
        layout.addWidget(self.scan_overview)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        left = QSplitter(Qt.Orientation.Vertical, self.splitter)
        self.directory_tree = DirectoryTree(left)
        self.drive_list = DriveList(left)
        left.addWidget(self.directory_tree)
        left.addWidget(self.drive_list)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 1)

        self.views = QTabWidget(self.splitter)
        self.chart = ChartView(self.views)
        self.details = DetailsView(self.views)
        self.extensions = ExtensionsView(self.views)
        self.file_groups = FileGroupsView(self.views)
        self.users = UsersView(self.views)
        self.ages = AgeView(self.views)
        self.top_files = TopFilesView(parent=self.views)
        for widget, title in ((self.chart, "Chart"),
                              (self.details, "Details"),
                              (self.extensions, "Extensions"),
                              (self.file_groups, "File groups"),
                              (self.users, "Users"),
                              (self.ages, "Age of Files"),
                              (self.top_files, "Top Files")):
            self.views.addTab(widget, title)
        self._aggregates = AggregateCache()

        self.splitter.addWidget(left)
        self.splitter.addWidget(self.views)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        self.status_bar = TreeSizeStatusBar(self)
        layout.addWidget(self.status_bar)

        self._body = (self.nav_bar, self.splitter, self.scan_overview,
                      self.status_bar)
        self._recent: list[str] = []
        self._backstage_open = False

        self._wire()
        self.drive_list.refresh()

    # ---- construction ---------------------------------------------------

    def _build_nav_bar(self) -> QWidget:
        bar = QWidget(self)
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 3, 6, 3)
        row.setSpacing(4)
        self.back_button = QPushButton("◂", bar)
        self.forward_button = QPushButton("▸", bar)
        self.up_button = QPushButton("▴", bar)
        for button in (self.back_button, self.forward_button, self.up_button):
            button.setFixedWidth(28)
            button.setObjectName("navButton")
            row.addWidget(button)
        self.path_combo = QComboBox(bar)
        self.path_combo.setEditable(True)
        self.path_combo.setMinimumWidth(320)
        row.addWidget(self.path_combo, 1)
        self.go_button = QPushButton("▶", bar)
        self.go_button.setFixedWidth(28)
        self.go_button.setObjectName("navButton")
        row.addWidget(self.go_button)
        self.scan_state = QLabel("", bar)
        self.scan_state.setObjectName("scanState")
        row.addWidget(self.scan_state)
        return bar

    def _wire(self) -> None:
        self.go_button.clicked.connect(self._start_scan_from_combo)
        self.path_combo.lineEdit().returnPressed.connect(self._start_scan_from_combo)
        self.up_button.clicked.connect(self._go_up)
        self.drive_list.drive_activated.connect(self.start_scan)
        self.directory_tree.node_selected.connect(self._on_node_selected)
        self.directory_tree.node_activated.connect(self._on_node_selected)
        self.details.node_activated.connect(self._drill_into)
        self.chart.node_clicked.connect(self._on_node_selected)
        self.top_files.node_activated.connect(self._drill_into)

        # One context menu for every pane: the same right-click must offer the
        # same things wherever it happens, or the module stops feeling like a
        # single product.
        self.directory_tree.customContextMenuRequested.connect(
            self._tree_context_menu)
        for table in (self.details, self.top_files, self.extensions,
                      self.file_groups, self.users, self.ages):
            table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.details.customContextMenuRequested.connect(
            lambda pos: self._table_context_menu(self.details, pos))
        self.top_files.customContextMenuRequested.connect(
            lambda pos: self._table_context_menu(self.top_files, pos))
        # Aggregates are computed lazily per tab: building all six for every
        # selection would walk the subtree six times for five views nobody is
        # looking at.
        self.views.currentChanged.connect(lambda _i: self._refresh_right_pane())

        for action_id, mode in MODE_ACTIONS.items():
            self.ribbon.action(action_id).triggered.connect(
                lambda _checked=False, m=mode: self.set_mode(m))
        for action_id, unit in UNIT_ACTIONS.items():
            self.ribbon.action(action_id).triggered.connect(
                lambda _checked=False, u=unit: self.set_unit(u))

        self.ribbon.action("scan.stop").triggered.connect(self.stop_scan)
        self.ribbon.action("scan.pause").triggered.connect(self.toggle_pause)
        self.ribbon.action("scan.refresh").triggered.connect(self.refresh_scan)
        self.ribbon.action("scan.remove").triggered.connect(self.clear_scan)
        self.ribbon.action("tree.expand").triggered.connect(
            lambda: self.directory_tree.expandToDepth(1))
        self.ribbon.action("sort.size").triggered.connect(
            lambda: self.directory_tree.sortByColumn(1, Qt.SortOrder.DescendingOrder))
        self.ribbon.action("sort.name").triggered.connect(
            lambda: self.directory_tree.sortByColumn(0, Qt.SortOrder.AscendingOrder))

        for action_id, widget in (("panel.drives", self.drive_list),
                                  ("panel.overview", self.scan_overview),
                                  ("panel.status", self.status_bar)):
            action = self.ribbon.action(action_id)
            action.setChecked(True)
            action.toggled.connect(widget.setVisible)

        self.title_row.find_requested.connect(self.find_results.search)
        self.find_results.command_chosen.connect(self._run_command)
        self.ribbon.tab_changed.connect(self._on_tab_changed)
        self.backstage.closed.connect(self._close_backstage)
        self.backstage.scan_requested.connect(self.start_scan)
        self.backstage.action_requested.connect(self._run_command)

        self._wire_menus()

        self.ribbon.action("mode.size").setChecked(True)
        self.ribbon.action("unit.auto").setChecked(True)
        self.ribbon.action("unit.decimals.1").setChecked(True)
        self.ribbon.action("hidesmall.off").setChecked(True)
        self._set_scanning(False)

    def _wire_menus(self) -> None:
        """Give every dropdown item something to do.

        A menu entry that does nothing is worse than an absent one: it reads as
        broken rather than unfinished.
        """
        act = self.ribbon.action

        for depth in (1, 2, 3):
            act("tree.expand.%d" % depth).triggered.connect(
                lambda _c=False, d=depth: self.directory_tree.expandToDepth(d - 1))
        act("tree.expand.all").triggered.connect(self.directory_tree.expandAll)
        act("tree.collapse.all").triggered.connect(self.directory_tree.collapseAll)

        for decimals in (0, 1, 2):
            act("unit.decimals.%d" % decimals).triggered.connect(
                lambda _c=False, d=decimals: self.set_decimals(d))

        for suffix, widget in (("chart", self.chart), ("details", self.details),
                               ("extensions", self.extensions),
                               ("groups", self.file_groups), ("users", self.users),
                               ("age", self.ages), ("top", self.top_files)):
            act("view.go." + suffix).triggered.connect(
                lambda _c=False, w=widget: self.views.setCurrentWidget(w))

        act("scan.refresh.all").triggered.connect(self.refresh_scan)
        act("scan.refresh.selected").triggered.connect(self._refresh_selected)
        act("scan.stop.all").triggered.connect(self.stop_scan)

        act("export.csv").triggered.connect(lambda: self._export("csv"))
        act("export.html").triggered.connect(lambda: self._export("html"))
        act("export.clipboard").triggered.connect(self._export_clipboard)

        act("exclude.selected").triggered.connect(self._exclude_selected)
        act("exclude.pattern").triggered.connect(self._exclude_pattern)
        act("exclude.clear").triggered.connect(self._clear_exclusions)

        for suffix, threshold in (("off", 0), ("1mb", 1 << 20),
                                  ("10mb", 10 << 20), ("100mb", 100 << 20)):
            act("hidesmall." + suffix).triggered.connect(
                lambda _c=False, t=threshold, sfx=suffix: self._set_min_size(t, sfx))

        self._refresh_target_menu()

    def _run_command(self, action_id: str) -> None:
        """Fire a ribbon command by id, from the Find box or the backstage.

        A menu parent (Export, Select scan target) has no useful click action of
        its own, so its menu is popped up instead of triggering nothing.
        """
        self._close_backstage()
        menu = self.ribbon.menu(action_id)
        action = self.ribbon.actions_by_id.get(action_id)
        if menu is not None and menu.actions():
            menu.popup(self.mapToGlobal(self.rect().topLeft()))
            return
        if action is not None:
            action.trigger()

    def _on_tab_changed(self, name: str) -> None:
        if name == "File":
            self.backstage.set_recent(self._recent)
            for widget in self._body:
                widget.hide()
            self.ribbon.pages.hide()
            self.backstage.show()
            self._backstage_open = True
        else:
            self._close_backstage()

    def _close_backstage(self) -> None:
        # Tracked explicitly rather than read off isVisible(): a widget that has
        # not been shown yet reports isVisible() False even while the backstage
        # is the active page, and this method would then return without ever
        # restoring the body.
        if not self._backstage_open:
            return
        self._backstage_open = False
        self.backstage.hide()
        self.ribbon.pages.show()
        for widget in self._body:
            widget.show()
        # Panel toggles own the visibility of two of these, so honour them
        # rather than forcing everything back on.
        for action_id, widget in (("panel.overview", self.scan_overview),
                                  ("panel.status", self.status_bar)):
            widget.setVisible(self.ribbon.action(action_id).isChecked())
        if self.ribbon.tab_bar.currentIndex() == 0:
            self.ribbon.tab_bar.setCurrentIndex(1)

    def _refresh_target_menu(self) -> None:
        """The scan-target list is whatever drives exist now, not a fixed list."""
        from .panels import list_drives
        items = []
        for letter, _total, _free in list_drives():
            root = letter + ":" + chr(92)
            items.append((root, lambda _c=False, r=root: self.start_scan(r)))
        items.append((None, None))
        items.append(("Select folder\u2026", self._browse_for_folder))
        self.ribbon.set_menu_items("scan.select", items)

    def _browse_for_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select folder to scan")
        if folder:
            self.start_scan(folder)

    def set_decimals(self, decimals: int) -> None:
        unit = self.directory_tree.tree_model.unit
        self.directory_tree.tree_model.set_unit(unit, decimals)
        for view in (self.details, self.extensions, self.file_groups,
                     self.users, self.ages, self.top_files):
            view.set_unit(unit, decimals)
        for value in (0, 1, 2):
            self.ribbon.action("unit.decimals.%d" % value).setChecked(value == decimals)
        self._refresh_right_pane()

    def _set_min_size(self, threshold: int, chosen: str) -> None:
        self._filters.min_size = threshold
        for suffix in ("off", "1mb", "10mb", "100mb"):
            self.ribbon.action("hidesmall." + suffix).setChecked(suffix == chosen)
        if self._result is not None:
            self.refresh_scan()

    def _refresh_selected(self) -> None:
        node = getattr(self, "_selected", -1)
        if self._store is not None and node >= 0:
            self.start_scan(self._store.path(node))

    def _exclude_selected(self) -> None:
        node = getattr(self, "_selected", -1)
        if self._store is None or node < 0:
            return
        name = self._store.name(node)
        self._filters.exclude_globs = tuple(self._filters.exclude_globs) + (name,)
        self.refresh_scan()

    def _exclude_pattern(self) -> None:
        pattern, ok = QInputDialog.getText(
            self, "Exclude by pattern",
            "Exclude names matching (for example *.tmp):")
        if ok and pattern.strip():
            self._filters.exclude_globs = (
                tuple(self._filters.exclude_globs) + (pattern.strip(),))
            self.refresh_scan()

    def _clear_exclusions(self) -> None:
        self._filters.exclude_globs = ()
        self._filters.exclude_path_globs = ()
        self._filters.min_size = 0
        self.ribbon.action("hidesmall.off").setChecked(True)
        if self._result is not None:
            self.refresh_scan()

    def _export_rows(self):
        """The visible subtree as rows, which is what an export should contain."""
        node = getattr(self, "_selected", self._root)
        if self._store is None or node < 0:
            return []
        store = self._store
        rows = [("Name", "Size (bytes)", "Allocated (bytes)", "Files",
                 "Folders", "Path")]
        for child in store.children(node):
            if store.attrs[child] & EXCLUDED:
                continue
            rows.append((store.name(child), str(store.size[child]),
                         str(store.alloc[child]), str(store.file_count[child]),
                         str(store.folder_count[child]), store.path(child)))
        return rows

    def _export(self, kind: str) -> None:
        rows = self._export_rows()
        if len(rows) < 2:
            QMessageBox.information(self, "Export", "Nothing to export.")
            return
        chooser = {"csv": "CSV (*.csv)", "html": "HTML (*.html)"}[kind]
        path, _ = QFileDialog.getSaveFileName(self, "Export scan result", "", chooser)
        if not path:
            return
        try:
            if kind == "csv":
                import csv
                # utf-8-sig so Excel opens non-ASCII filenames correctly rather
                # than mojibake, which is the whole point of exporting to CSV.
                with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                    csv.writer(handle).writerows(rows)
            else:
                import html
                body = "\n".join(
                    "<tr>" + "".join("<td>%s</td>" % html.escape(cell)
                                     for cell in row) + "</tr>"
                    for row in rows)
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("<!doctype html><meta charset=utf-8>"
                                 "<style>table{border-collapse:collapse}"
                                 "td,th{border:1px solid #999;padding:3px 6px}"
                                 "</style><table>" + body + "</table>")
        except OSError as exc:
            QMessageBox.warning(self, "Export failed", str(exc))
            return
        self.scan_state.setText("Exported %s rows" % format(len(rows) - 1, ","))

    def _export_clipboard(self) -> str:
        """Copy the visible rows and RETURN what was copied.

        Returning the text is not decoration: reading it back off the
        Windows clipboard is timing-dependent while widgets are being
        created and destroyed around it, so a test that round-trips through
        the OS is flaky for reasons unrelated to the export being right.
        """
        rows = self._export_rows()
        if len(rows) < 2:
            return ""
        text = "\n".join("\t".join(row) for row in rows)
        QApplication.clipboard().setText(text)
        self.scan_state.setText("Copied %s rows" % format(len(rows) - 1, ","))
        return text

    def set_mode(self, mode: Mode) -> None:
        self.directory_tree.tree_model.set_mode(mode)
        for action_id, candidate in MODE_ACTIONS.items():
            self.ribbon.action(action_id).setChecked(candidate is mode)

    def set_unit(self, unit: Unit) -> None:
        self.directory_tree.tree_model.set_unit(unit)
        for view in (self.details, self.extensions, self.file_groups,
                     self.users, self.ages, self.top_files):
            view.set_unit(unit)
        for action_id, candidate in UNIT_ACTIONS.items():
            self.ribbon.action(action_id).setChecked(candidate is unit)
        self._refresh_right_pane()

    def _set_scanning(self, scanning: bool) -> None:
        self.ribbon.set_enabled("scan.stop", scanning)
        self.ribbon.set_enabled("scan.pause", scanning)
        self.ribbon.set_enabled("scan.refresh", not scanning and self._store is not None)
        self.ribbon.set_enabled("scan.remove", not scanning and self._store is not None)
        self.scan_state.setText("Scanning…" if scanning else "")

    # ---- scanning -------------------------------------------------------

    def _start_scan_from_combo(self) -> None:
        target = self.path_combo.currentText().strip()
        if target:
            self.start_scan(target)

    def start_scan(self, target: str, filters: FilterSet | None = None) -> None:
        """Run the scan on a worker thread and return immediately.

        Everything the UI needs during the scan arrives by signal; nothing
        blocks here, which is what makes Stop and Pause mean anything.
        """
        if self._worker is not None:
            return                       # a scan is already running
        self.path_combo.setEditText(target)
        if self.path_combo.findText(target) < 0:
            self.path_combo.addItem(target)
        if target in self._recent:
            self._recent.remove(target)
        self._recent.insert(0, target)
        del self._recent[8:]

        worker = ScanWorker(target, filters=filters or self._filters)
        worker.signals.batch_ready.connect(self._on_batch)
        worker.signals.finished.connect(self._on_finished)
        worker.signals.failed.connect(self._on_failed)
        worker.signals.cancelled.connect(self._on_cancelled)
        self._worker = worker
        self._paused = False
        self._set_scanning(True)
        self._pool.start(worker)

    def wait_for_scan(self, timeout_ms: int = 120_000) -> bool:
        """Block until the running scan finishes. For tests and shutdown only."""
        from PyQt6.QtCore import QDeadlineTimer, QCoreApplication
        deadline = QDeadlineTimer(timeout_ms)
        while self._worker is not None and not deadline.hasExpired():
            QCoreApplication.processEvents()
        return self._worker is None

    def _on_batch(self, index_range) -> None:
        start, end = index_range
        self.scan_state.setText(f"Scanning… {end:,} items")

    def _on_finished(self, result) -> None:
        self._worker = None
        self.show_result(result)

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self._set_scanning(False)
        self.scan_state.setText(f"Scan failed: {message}")

    def _on_cancelled(self) -> None:
        self._worker = None
        self._set_scanning(False)
        self.scan_state.setText("Scan stopped")

    def show_result(self, result) -> None:
        self._result = result
        self._store = result.store
        self._root = result.root
        self.directory_tree.set_scan(result.store, result.root)
        letter = result.store.name(result.root)[:1]
        total, free = drive_space(letter) if letter.isalpha() else (0, 0)
        self.status_bar.show_result(result, total, free)
        self._aggregates.clear()
        self._on_node_selected(result.root)
        self._set_scanning(False)
        self.scan_state.setText("")
        self.scan_finished.emit(result)

    def stop_scan(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        else:
            self._set_scanning(False)

    def toggle_pause(self) -> None:
        if self._worker is None:
            return
        self._paused = not self._paused
        if self._paused:
            self._worker.pause()
            self.scan_state.setText("Paused")
        else:
            self._worker.resume()
        self.ribbon.action("scan.pause").setText("Resume" if self._paused else "Pause")

    def refresh_scan(self) -> None:
        target = self.path_combo.currentText().strip()
        if target:
            self.start_scan(target, filters=self._filters)

    def clear_scan(self) -> None:
        self._store = None
        self._root = -1
        self._result = None
        self._aggregates.clear()
        self.directory_tree.tree_model.clear()
        self.details.show_children_of(None, -1)
        self.chart.set_scan(None, -1)
        for view in (self.extensions, self.file_groups, self.users,
                     self.ages, self.top_files):
            view.clear()
        self.scan_overview.clear()
        self.status_bar.clear()
        self._set_scanning(False)

    # ---- context menus --------------------------------------------------

    def _tree_context_menu(self, pos) -> None:
        index = self.directory_tree.indexAt(pos)
        if not index.isValid():
            return
        from .tree_model import NodeIndexRole
        node = index.data(NodeIndexRole)
        if node is None:
            return
        menu = self.row_actions.menu_for(int(node), self.directory_tree)
        if menu is not None:
            menu.exec(self.directory_tree.viewport().mapToGlobal(pos))

    def _table_context_menu(self, table, pos) -> None:
        item = table.itemAt(pos)
        if item is None:
            return
        from PyQt6.QtCore import Qt as _Qt
        node = item.data(0, _Qt.ItemDataRole.UserRole)
        if node is None:
            from .views.tables import NodeRole
            node = item.data(0, NodeRole)
        if node is None:
            return
        menu = self.row_actions.menu_for(int(node), table)
        if menu is not None:
            menu.exec(table.viewport().mapToGlobal(pos))

    # ---- selection ------------------------------------------------------

    def _on_node_selected(self, node: int) -> None:
        self._selected = node
        self.scan_overview.show_node(self._store, node,
                                     self.directory_tree.tree_model.unit)
        self._refresh_right_pane()

    def _refresh_right_pane(self) -> None:
        """Populate only the visible view."""
        node = getattr(self, "_selected", self._root)
        if self._store is None or node < 0:
            return
        current = self.views.currentWidget()
        if current is self.details:
            self.details.show_children_of(self._store, node)
        elif current is self.chart:
            self.chart.set_scan(self._store, node)
        elif current is self.top_files:
            self.top_files.show_subtree(self._store, node, self._aggregates)
        elif current in (self.extensions, self.file_groups, self.users, self.ages):
            current.show_subtree(self._store, node, self._aggregates)

    def _drill_into(self, node: int) -> None:
        self._on_node_selected(node)

    def _go_up(self) -> None:
        node = getattr(self, "_selected", -1)
        if self._store is None or node < 0:
            return
        parent = self._store.parent[node]
        if 0 <= parent < len(self._store):
            self._on_node_selected(parent)
