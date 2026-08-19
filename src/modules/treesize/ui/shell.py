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
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..scan.filters import FilterSet
from ..scan.scanner import Scanner
from .directory_tree import DirectoryTree
from .formatting import Mode, Unit
from .panels import DriveList, ScanOverview, TreeSizeStatusBar, drive_space
from .ribbon import Ribbon
from .views.details import DetailsView

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
# Views that exist in phase 2. The rest are tabs in the spec's strip and land
# in phase 3; they are not shown yet rather than shown empty.
VIEW_TABS = ("Details",)


class TreeSizeShell(QWidget):
    scan_finished = pyqtSignal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._store = None
        self._root = -1
        self._result = None
        self._scanner: Scanner | None = None
        self._pool = QThreadPool.globalInstance()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.ribbon = Ribbon(self)
        layout.addWidget(self.ribbon)

        layout.addWidget(self._build_nav_bar())

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
        self.details = DetailsView(self.views)
        self.views.addTab(self.details, "Details")

        self.splitter.addWidget(left)
        self.splitter.addWidget(self.views)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        layout.addWidget(self.splitter, 1)

        self.status_bar = TreeSizeStatusBar(self)
        layout.addWidget(self.status_bar)

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

        for action_id, mode in MODE_ACTIONS.items():
            self.ribbon.action(action_id).triggered.connect(
                lambda _checked=False, m=mode: self.set_mode(m))
        for action_id, unit in UNIT_ACTIONS.items():
            self.ribbon.action(action_id).triggered.connect(
                lambda _checked=False, u=unit: self.set_unit(u))

        self.ribbon.action("scan.stop").triggered.connect(self.stop_scan)
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

        self.ribbon.action("mode.size").setChecked(True)
        self.ribbon.action("unit.auto").setChecked(True)
        self._set_scanning(False)

    # ---- state ----------------------------------------------------------

    def set_mode(self, mode: Mode) -> None:
        self.directory_tree.tree_model.set_mode(mode)
        for action_id, candidate in MODE_ACTIONS.items():
            self.ribbon.action(action_id).setChecked(candidate is mode)

    def set_unit(self, unit: Unit) -> None:
        self.directory_tree.tree_model.set_unit(unit)
        self.details.set_unit(unit)
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
        """Scan synchronously.

        Phase 2 runs the scan on the calling thread. The engine already emits
        batches and honours cancel/pause through callbacks, so moving this to a
        Worker is a wiring change here and nothing at all in the engine -- but
        it is not pretended to be done: the spec's threading contract (3.4)
        belongs with the incremental tree population, which is phase 3 work.
        """
        self.path_combo.setEditText(target)
        if self.path_combo.findText(target) < 0:
            self.path_combo.addItem(target)
        self._set_scanning(True)
        try:
            self._scanner = Scanner(target, filters=filters)
            result = self._scanner.scan()
        finally:
            self._set_scanning(False)
        self.show_result(result)

    def show_result(self, result) -> None:
        self._result = result
        self._store = result.store
        self._root = result.root
        self.directory_tree.set_scan(result.store, result.root)
        letter = result.store.name(result.root)[:1]
        total, free = drive_space(letter) if letter.isalpha() else (0, 0)
        self.status_bar.show_result(result, total, free)
        self._on_node_selected(result.root)
        self._set_scanning(False)
        self.scan_finished.emit(result)

    def stop_scan(self) -> None:
        self._set_scanning(False)

    def refresh_scan(self) -> None:
        target = self.path_combo.currentText().strip()
        if target:
            self.start_scan(target)

    def clear_scan(self) -> None:
        self._store = None
        self._root = -1
        self._result = None
        self.directory_tree.tree_model.clear()
        self.details.show_children_of(None, -1)
        self.scan_overview.clear()
        self.status_bar.clear()
        self._set_scanning(False)

    # ---- selection ------------------------------------------------------

    def _on_node_selected(self, node: int) -> None:
        self._selected = node
        self.scan_overview.show_node(self._store, node,
                                     self.directory_tree.tree_model.unit)
        self.details.show_children_of(self._store, node)

    def _refresh_right_pane(self) -> None:
        node = getattr(self, "_selected", self._root)
        if self._store is not None:
            self.details.show_children_of(self._store, node)

    def _drill_into(self, node: int) -> None:
        self._on_node_selected(node)

    def _go_up(self) -> None:
        node = getattr(self, "_selected", -1)
        if self._store is None or node < 0:
            return
        parent = self._store.parent[node]
        if 0 <= parent < len(self._store):
            self._on_node_selected(parent)
