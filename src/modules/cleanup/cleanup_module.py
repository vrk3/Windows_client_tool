import os
from typing import List, Optional, Callable, Tuple

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget,
    QTreeWidgetItem, QLabel, QTabWidget, QProgressBar, QMenu, QSizePolicy,
    QHeaderView,
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QAction

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.cleanup import cleanup_scanner as cs


class _ScanTab(QWidget):
    """Generic scan/clean tab. Configured with a scanner function."""

    def __init__(self, scanner_fn: Callable[[], cs.ScanResult],
                 wu_cache: bool = False, parent=None):
        super().__init__(parent)
        self._scanner_fn = scanner_fn
        self._wu_cache = wu_cache
        self._result: Optional[cs.ScanResult] = None
        self._scanning = False
        self._cleaning = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        self._scan_btn = QPushButton("Scan")
        self._clean_btn = QPushButton("Clean Selected")
        self._select_all_btn = QPushButton("Select All")
        self._deselect_btn = QPushButton("Deselect All")
        self._status_label = QLabel("Ready")
        self._clean_btn.setEnabled(False)
        toolbar.addWidget(self._scan_btn)
        toolbar.addWidget(self._clean_btn)
        toolbar.addWidget(self._select_all_btn)
        toolbar.addWidget(self._deselect_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status_label)
        layout.addLayout(toolbar)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Path", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._tree)

        self._scan_btn.clicked.connect(self._do_scan)
        self._clean_btn.clicked.connect(self._do_clean)
        self._select_all_btn.clicked.connect(self._select_all)
        self._deselect_btn.clicked.connect(self._deselect_all)

    def _do_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        self._tree.clear()
        self._status_label.setText("Scanning...")
        self._progress.setRange(0, 0)
        self._progress.show()

        scanner_fn = self._scanner_fn

        def _run(worker):
            return scanner_fn()

        worker = Worker(_run)
        worker.signals.result.connect(self._on_scan_result)
        worker.signals.error.connect(self._on_scan_error)
        QThreadPool.globalInstance().start(worker)

    def _on_scan_result(self, result: cs.ScanResult):
        self._result = result
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._progress.setRange(0, 1)
        self._tree.clear()
        for item in result.items:
            tw = QTreeWidgetItem([item.path, cs.format_size(item.size)])
            tw.setCheckState(0, Qt.CheckState.Checked)
            tw.setData(0, Qt.ItemDataRole.UserRole, item)
            tw.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._tree.addTopLevelItem(tw)
        self._status_label.setText(
            f"Found {len(result.items)} items — {cs.format_size(result.total_size)}")
        self._clean_btn.setEnabled(len(result.items) > 0)

    def _on_scan_error(self, error_str: str):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._status_label.setText(f"Error: {error_str}")

    def _get_selected_items(self) -> List[cs.ScanItem]:
        items = []
        for i in range(self._tree.topLevelItemCount()):
            tw = self._tree.topLevelItem(i)
            scan_item: cs.ScanItem = tw.data(0, Qt.ItemDataRole.UserRole)
            if scan_item is not None:
                scan_item.selected = tw.checkState(0) == Qt.CheckState.Checked
                items.append(scan_item)
        return items

    def _do_clean(self):
        if self._cleaning or self._result is None:
            return
        self._cleaning = True
        self._clean_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._status_label.setText("Cleaning...")
        self._progress.setRange(0, 0)
        self._progress.show()

        selected = self._get_selected_items()
        wu = self._wu_cache

        def _run(worker):
            return cs.delete_items(selected, stop_wuauserv=wu)

        worker = Worker(_run)
        worker.signals.result.connect(self._on_clean_done)
        worker.signals.error.connect(self._on_clean_error)
        QThreadPool.globalInstance().start(worker)

    def _on_clean_done(self, result: Tuple[int, int]):
        deleted, errors = result
        self._cleaning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        msg = f"Cleaned {deleted} item(s)"
        if errors:
            msg += f" ({errors} error(s))"
        self._status_label.setText(msg)
        self._clean_btn.setEnabled(False)
        # Re-scan to refresh
        self._do_scan()

    def _on_clean_error(self, error_str: str):
        self._cleaning = False
        self._scan_btn.setEnabled(True)
        self._clean_btn.setEnabled(True)
        self._progress.hide()
        self._status_label.setText(f"Clean error: {error_str}")

    def _select_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    def _deselect_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)

    def _show_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        scan_item: cs.ScanItem = item.data(0, Qt.ItemDataRole.UserRole)
        if not scan_item:
            return
        menu = QMenu(self)
        open_action = menu.addAction("Open in Explorer")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == open_action:
            target = scan_item.path if scan_item.is_dir else os.path.dirname(scan_item.path)
            os.startfile(target)


class CleanupModule(BaseModule):
    name = "cleanup"
    icon = "🗑"
    description = "Scan and remove temporary files, caches, and junk"
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def create_widget(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(_ScanTab(cs.scan_temp_files), "Temp Files")
        tabs.addTab(_ScanTab(cs.scan_browser_caches), "Browser Caches")
        tabs.addTab(_ScanTab(cs.scan_wu_cache, wu_cache=True), "Windows Update Cache")
        tabs.addTab(_ScanTab(cs.scan_prefetch), "Prefetch")
        tabs.addTab(_ScanTab(cs.scan_recycle_bin), "Recycle Bin")
        tabs.addTab(_ScanTab(cs.scan_event_logs), "Event Log Cleanup")
        return tabs

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def get_status_info(self) -> str:
        return "Cleanup"
