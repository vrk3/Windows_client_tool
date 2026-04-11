"""Category group widget for expandable cleanup categories.

Provides:
- Expand/collapse tree sections
- Auto-refresh support (external control — start/stop via public methods)
- Batch selection
- Context menus
- Background scan via Worker threads
"""
import os

from PyQt6.QtCore import Qt, QTimer, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QPushButton, QSizePolicy, QLabel, QMenu, QToolButton, QHeaderView,
    QScrollArea,
)

from core.worker import Worker

try:
    from modules.cleanup.cleanup_scanner import ScanResult, ScanItem, format_size
except ImportError:
    ScanResult = object
    ScanItem = object
    format_size = lambda s: str(s)


class CategoryGroup(QWidget):
    """Expandable category group with tree view and background scan.

    Lifecycle:
        - Auto-refresh is controlled externally via start_auto_refresh() /
          stop_auto_refresh(). Do NOT start timers in __init__.
        - scan() and clean_all() run in background workers.
    """

    # Emitted when scan completes: (item_count, total_size)
    scan_done = pyqtSignal(int, int)

    def __init__(
        self,
        group_name: str,
        scanner_fn,
        auto_refresh: bool = False,
        refresh_interval_ms: int = 30_000,
        parent=None,
    ):
        super().__init__(parent)
        self._group_name = group_name
        self._scanner_fn = scanner_fn
        self._results = None
        self._scanning = False
        self._cleaning = False
        self._auto_refresh_enabled = auto_refresh
        self._refresh_interval_ms = refresh_interval_ms
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_timer_refresh)
        self._workers = []
        self._setup_ui()

    # ── Public API ────────────────────────────────────────────────────────────

    def start_auto_refresh(self) -> None:
        """Start the auto-refresh timer. Safe to call even if already started."""
        if not self._refresh_timer.isActive():
            self._refresh_timer.start(self._refresh_interval_ms)

    def stop_auto_refresh(self) -> None:
        """Stop the auto-refresh timer."""
        self._refresh_timer.stop()

    def is_auto_refresh_enabled(self) -> bool:
        return self._auto_refresh_enabled

    def scan(self) -> None:
        """Trigger a background scan. Idempotent — ignores if already scanning."""
        if self._scanning:
            return
        self._do_scan()

    def clean_all(self) -> None:
        """Clean all checked items in the tree."""
        self._do_clean_all()

    def cancel(self) -> None:
        """Cancel any in-flight workers."""
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("Scan")

    # ── Setup ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        self._expand_btn = QToolButton()
        self._expand_btn.setText("🗂️ " + self._group_name + " ▼")
        self._expand_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._expand_btn.setFixedHeight(32)
        self._expand_btn.pressed.connect(self._toggle_expand)
        toolbar.addWidget(self._expand_btn)

        self._scan_btn = QPushButton("Scan")
        self._scan_btn.clicked.connect(self.scan)
        self._scan_btn.setFixedHeight(32)
        toolbar.addWidget(self._scan_btn)

        self._clean_all_btn = QPushButton("Clean All")
        self._clean_all_btn.clicked.connect(self.clean_all)
        self._clean_all_btn.setEnabled(False)
        self._clean_all_btn.setFixedHeight(32)
        toolbar.addWidget(self._clean_all_btn)

        self._expand_all_btn = QToolButton()
        self._expand_all_btn.setText("Expand All")
        self._expand_all_btn.clicked.connect(self._expand_all)
        self._expand_all_btn.setFixedHeight(32)
        toolbar.addWidget(self._expand_all_btn)

        self._collapse_all_btn = QToolButton()
        self._collapse_all_btn.setText("Collapse All")
        self._collapse_all_btn.clicked.connect(self._collapse_all)
        self._collapse_all_btn.setFixedHeight(32)
        toolbar.addWidget(self._collapse_all_btn)

        self._status_label = QLabel("Ready")
        self._status_label.setFixedWidth(200)
        toolbar.addWidget(self._status_label)

        layout.addLayout(toolbar)

        # Tree in scroll area
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Path", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        content_layout.addWidget(self._tree)
        self._scroll_area.setWidget(content)
        layout.addWidget(self._scroll_area)

        # Error label
        self._err_lbl = QLabel()
        self._err_lbl.setStyleSheet("color: #f44336;")
        self._err_lbl.setWordWrap(True)
        self._err_lbl.hide()
        layout.addWidget(self._err_lbl)

    # ── Auto-refresh ─────────────────────────────────────────────────────────

    def _on_timer_refresh(self):
        """Timer-fired refresh — skips if already scanning or cleaning."""
        if self._scanning or self._cleaning:
            return
        self._scan_btn.setText("Scanning...")
        self._scan_btn.setEnabled(False)
        self._do_scan()

    # ── Scan ─────────────────────────────────────────────────────────────────

    def _do_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("Scan")
        self._tree.clear()
        self._err_lbl.hide()
        self._status_label.setText("Scanning...")
        self._clean_all_btn.setEnabled(False)

        def _run(_worker):
            # scanner_fn may be a plain function or a callable
            result = self._scanner_fn()
            return result

        w = Worker(_run)
        w.signals.result.connect(self._on_scan_result)
        w.signals.error.connect(self._on_scan_error)
        self._workers.append(w)
        QThreadPool.globalInstance().start(w)

    def _on_scan_result(self, result):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("Scan")
        self._results = result

        if result is None:
            result = ScanResult(items=[], total_size=0)

        if result.items:
            root = QTreeWidgetItem([
                self._group_name,
                format_size(result.total_size),
            ])
            root.setCheckState(0, Qt.CheckState.Checked)
            root.setFlags(
                root.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            root.setExpanded(True)
            self._tree.addTopLevelItem(root)

            for item in result.items:
                child = QTreeWidgetItem([item.path, format_size(item.size)])
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setData(0, Qt.ItemDataRole.UserRole, item)
                child.setTextAlignment(
                    1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                root.addChild(child)

            self._status_label.setText(
                f"Found {len(result.items)} item(s) — {format_size(result.total_size)}"
            )
            self._clean_all_btn.setEnabled(True)
        else:
            self._status_label.setText("No items found.")

        self.scan_done.emit(len(result.items), result.total_size)

        # Trim completed workers
        self._workers = [w for w in self._workers if not w.cancelled]

    def _on_scan_error(self, err: str):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("Scan")
        self._status_label.setText(f"Scan error: {err}")
        self._workers = [w for w in self._workers if not w.cancelled]

    # ── Clean ────────────────────────────────────────────────────────────────

    def _do_clean_all(self):
        if self._cleaning or not self._results:
            return

        checked: list = []
        for i in range(self._tree.topLevelItemCount()):
            root = self._tree.topLevelItem(i)
            for j in range(root.childCount()):
                child = root.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    item = child.data(0, Qt.ItemDataRole.UserRole)
                    if item is not None:
                        checked.append(item)

        if not checked:
            return

        self._cleaning = True
        self._clean_all_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._status_label.setText("Cleaning...")

        def _run(_worker):
            from modules.cleanup import cleanup_scanner as cs
            return cs.delete_items(checked, stop_wuauserv=False)

        def _done(result):
            deleted, errors = result
            self._cleaning = False
            self._scan_btn.setEnabled(True)
            msg = f"Cleaned {deleted} item(s)"
            if errors:
                msg += f" — {errors} could not be deleted"
                self._err_lbl.setText(f"⚠ {errors} file(s) could not be deleted.")
                self._err_lbl.show()
            self._status_label.setText(msg)
            # Rescan to refresh
            self._do_scan()

        def _err(err: str):
            self._cleaning = False
            self._scan_btn.setEnabled(True)
            self._status_label.setText(f"Clean error: {err}")

        w = Worker(_run)
        w.signals.result.connect(_done)
        w.signals.error.connect(_err)
        self._workers.append(w)
        QThreadPool.globalInstance().start(w)

    # ── Tree helpers ─────────────────────────────────────────────────────────

    def _toggle_expand(self):
        """Toggle expand/collapse of the tree root items."""
        is_collapsed = self._expand_btn.text().endswith(" ▼")
        if is_collapsed:
            self._expand_btn.setText("🗂️ " + self._group_name + " ▶")
            self._expand_all()
        else:
            self._expand_btn.setText("🗂️ " + self._group_name + " ▼")
            self._collapse_all()

    def _expand_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setExpanded(True)

    def _collapse_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setExpanded(False)

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        scan_item = item.data(0, Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        open_action = menu.addAction("Open in Explorer")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == open_action and scan_item:
            target = scan_item.path if scan_item.is_dir else os.path.dirname(scan_item.path)
            os.startfile(target)
