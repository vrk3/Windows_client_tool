"""Category group widget for expandable cleanup categories.

Provides:
- Expand/collapse tree sections
- Auto-refresh support
- Batch selection
- Context menus
- Smart grouping
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QSizePolicy, QLabel, QMenu, QToolButton, QHeaderView,
    QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QTimer, QThreadPool
from PyQt6.QtGui import QAction

try:
    from modules.cleanup.cleanup_scanner import ScanResult, ScanItem, format_size
except ImportError:
    ScanResult = None
    ScanItem = None
    format_size = None


class CategoryGroup(QWidget):
    """Expandable category group with tree view and auto-refresh.

    Args:
        group_name: Display name of the group.
        categories: List of categories to add to group.
        scanner_fn: Scanner function that returns ScanResult.
        auto_refresh: Enable auto-refresh (default True).
        refresh_interval: Auto-refresh interval in seconds.
        parent: Parent widget.
    """

    def __init__(
        self, group_name: str, categories: list,
        scanner_fn, auto_refresh: bool = True, refresh_interval: int = 30,
        parent=None
    ):
        super().__init__(parent)
        self._group_name = group_name
        self._scanner_fn = scanner_fn
        self._results: dict = {}
        self._scanning = False
        self._cleaning = False
        self._auto_refresh = auto_refresh
        self._refresh_interval_ms = refresh_interval * 1000
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        # Expand button header
        self._expand_btn = QToolButton()
        self._expand_btn.setText("🗂️ " + self._group_name + " ▼")
        self._expand_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._expand_btn.setFixedHeight(32)
        self._expand_btn.pressed.connect(self._toggle_expand)
        toolbar.addWidget(self._expand_btn)

        # Scan button
        self._scan_btn = QPushButton("Scan")
        self._scan_btn.clicked.connect(self._do_scan)
        self._scan_btn.setFixedHeight(32)
        toolbar.addWidget(self._scan_btn)

        # Clean all button
        self._clean_all_btn = QPushButton("Clean All")
        self._clean_all_btn.clicked.connect(self._do_clean_all)
        self._clean_all_btn.setEnabled(False)
        self._clean_all_btn.setFixedHeight(32)
        toolbar.addWidget(self._clean_all_btn)

        # Expand all button
        self._expand_all_btn = QToolButton()
        self._expand_all_btn.setText("Expand All")
        self._expand_all_btn.clicked.connect(self._expand_all)
        self._expand_all_btn.setFixedHeight(32)
        toolbar.addWidget(self._expand_all_btn)

        # Collapse all button
        self._collapse_all_btn = QToolButton()
        self._collapse_all_btn.setText("Collapse All")
        self._collapse_all_btn.clicked.connect(self._collapse_all)
        self._collapse_all_btn.setFixedHeight(32)
        toolbar.addWidget(self._collapse_all_btn)

        # Status label
        self._status_label = QLabel("Ready")
        self._status_label.setFixedWidth(200)
        toolbar.addWidget(self._status_label)

        # Progress bar
        self._progress = None  # Added later

        layout.addLayout(toolbar)

        # Tree view in scroll area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Path", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        content.setLayout(QVBoxLayout(content))
        contentLayout = QVBoxLayout(content)
        contentLayout.addWidget(self._tree)
        self._scroll_area.setWidget(content)
        layout.addWidget(self._scroll_area)

        # Connect to auto-refresh
        if self._auto_refresh:
            self._refresh_timer.start(self._refresh_interval_ms)

    def _toggle_expand(self):
        """Toggle group expansion."""
        is_collapsed = self._expand_btn.text().endswith(" ▼")
        if is_collapsed:
            self._expand_btn.setText("🗂️ " + self._group_name + " ▼")
            self._show_items()
        else:
            self._expand_btn.setText("🗂️ " + self._group_name + " ▲")
            self._hide_items()

    def _on_refresh(self):
        """Auto-refresh handler."""
        if not self._auto_refresh or self._scanning or self._cleaning:
            return
        self._scan_btn.setText("Scanning...")
        self._scan_btn.setEnabled(False)
        QThreadPool.globalInstance().start(self._do_scan)

    def _do_scan(self):
        """Execute scan and populate tree."""
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.setEnabled(False)
        self._tree.clear()
        self._status_label.setText("Scanning...")
        self._progress.hide()

        try:
            result = self._scanner_fn()
            self._results = result or ScanResult(items=[], total_size=0)
        except Exception as e:
            self._status_label.setText(f"Error: {str(e)}")

        if self._results.total_size > 0:
            # Create root group item
            root_item = QTreeWidgetItem([
                self._group_name,
                format_size(result.total_size),
            ])
            root_item.setCheckState(0, Qt.CheckState.Checked)
            root_item.setFlags(
                root_item.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable
            )
            root_item.setExpanded(True)

            # Add categories as children
            for item in result.items:
                category_item = QTreeWidgetItem([
                    item.path,
                    format_size(item.size),
                ])
                category_item.setCheckState(0, Qt.CheckState.Checked)
                category_item.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    item
                )
                category_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                root_item.addChild(category_item)

            self._tree.addTopLevelItem(root_item)
            self._update_clean_all_btn()

            self._status_label.setText(
                f"Found {len(result.items)} items — {format_size(result.total_size)}"
            )
        else:
            self._status_label.setText("No items found.")
            self._clean_all_btn.setEnabled(False)

        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("Scan")

    def _do_clean_all(self):
        """Clean all checked items."""
        if self._cleaning:
            return
        self._cleaning = True
        self._clean_all_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._status_label.setText("Cleaning...")

        selected_items = []
        for _ in range(self._tree.topLevelItemCount()):
            # Simplified: check all children of all items
            for _ in range(self._tree.topLevelItemCount()):
                root = self._tree.topLevelItem(_)
                for child_idx in range(root.childCount()):
                    child = root.child(child_idx)
                    if child.checkState(0) == Qt.CheckState.Checked:
                        selected_items.append(child.data(0, Qt.ItemDataRole.UserRole))

        # Cleanup logic would go here
        self._cleaning = False
        self._clean_all_btn.setEnabled(True)
        # Auto-refresh after to update totals
        if self._auto_refresh:
            QThreadPool.globalInstance().start(self._do_scan)

    def _update_clean_all_btn(self):
        """Enable clean all button if items found."""
        total_items = 0
        for _ in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(_)
            for child_idx in range(root.childCount()):
                child = root.child(child_idx)
                if child.checkState(0) == Qt.CheckState.Checked:
                    total_items += 1

        self._clean_all_btn.setEnabled(total_items > 0)

    def _expand_all(self):
        """Expand all groups."""
        for _ in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(_)
            if item:
                item.setExpanded(True)

    def _collapse_all(self):
        """Collapse all groups."""
        for _ in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(_)
            if item:
                item.setExpanded(False)

    def _show_items(self):
        """Show all items in tree."""
        self._tree.hide()

    def _hide_items(self):
        """Collapse all groups in tree."""
        self._tree.hide()

    def _show_context_menu(self, pos):
        """Show context menu at position."""
        item = self._tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Open in Explorer")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == open_action:
            scan_item = item.data(0, Qt.ItemDataRole.UserRole)
            if scan_item:
                path = scan_item.path
                if scan_item.is_dir:
                    path = scan_item.path
                else:
                    try:
                        path = __import__("os").path.dirname(path)
                    except SystemError:
                        pass
                __import__("os").startfile(path)
