"""Duplicate File Finder — locate duplicate files by hash."""
import datetime
import hashlib
import os
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
import logging

logger = logging.getLogger(__name__)


class DuplicateFinderModule(BaseModule):
    name = "Duplicate Finder"
    icon = "🔍"
    description = "Find duplicate files by content hash"
    group = ModuleGroup.TOOLS
    requires_admin = False

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Folder selection row
        row = QHBoxLayout()
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText("Select folder to scan…")
        row.addWidget(self._path_input)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_folder)
        row.addWidget(browse_btn)
        scan_btn = QPushButton("Scan")
        scan_btn.setStyleSheet("font-weight: bold;")
        scan_btn.clicked.connect(self._start_scan)
        row.addWidget(scan_btn)
        layout.addLayout(row)

        # Progress
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._status_label)

        # Results tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Duplicate Group", "Size", "Files"])
        self._tree.setColumnWidth(0, 400)
        self._tree.setColumnWidth(1, 100)
        self._tree.setAlternatingRowColors(True)
        self._tree.setStyleSheet("""
            QTreeWidget { background: #2d2d2d; color: #e0e0e0; border: 1px solid #3c3c3c; border-radius: 4px; }
            QTreeWidget::item { padding: 4px; }
            QTreeWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0; padding: 4px; border: none; }
        """)
        layout.addWidget(self._tree)

        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def get_status_info(self) -> str:
        return f"Duplicate Finder — {self._tree.topLevelItemCount()} groups found"

    # ── implementation ──────────────────────────────────────────────────────

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self._widget, "Select Folder to Scan", ""
        )
        if folder:
            self._path_input.setText(folder)

    def _start_scan(self):
        folder = self._path_input.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self._widget, "Invalid Folder", "Please select a valid folder.")
            return

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._tree.clear()
        self._status_label.setText("Scanning files…")

        def do_scan(worker):
            files_by_size: Dict[int, List[str]] = {}
            # Phase 1: group by size
            for root, _, files in os.walk(folder):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(fpath)
                        if size > 0:
                            files_by_size.setdefault(size, []).append(fpath)
                    except OSError:
                        continue
            # Only keep groups with potential duplicates (same size)
            dupes = {s: paths for s, paths in files_by_size.items() if len(paths) > 1}

            # Phase 2: hash files with same size
            hash_groups: Dict[str, List[str]] = {}
            total = sum(len(v) for v in dupes.values())
            done = 0
            for paths in dupes.values():
                for fpath in paths:
                    if worker.is_cancelled:
                        return {}
                    try:
                        with open(fpath, 'rb') as f:
                            md5 = hashlib.md5(f.read()).hexdigest()
                        hash_groups.setdefault(md5, []).append(fpath)
                    except OSError:
                        continue
                    done += 1
                    if total > 0:
                        worker.signals.progress.emit(int(done / total * 100))
            # Only keep groups with actual duplicates
            return {h: p for h, p in hash_groups.items() if len(p) > 1}

        self._worker = Worker(do_scan)
        self._worker.signals.progress.connect(lambda p: self._progress.setValue(p))
        self._worker.signals.result.connect(self._on_results)
        self._worker.signals.error.connect(lambda e: self._status_label.setText(f"Error: {e}"))
        self.app.thread_pool.start(self._worker)

    def _on_results(self, hash_groups: Dict[str, List[str]]):
        self._progress.setVisible(False)
        if not hash_groups:
            self._status_label.setText("No duplicates found.")
            return

        total_wasted = 0
        for md5, paths in sorted(hash_groups.items(), key=lambda x: -len(x[1])):
            try:
                size = os.path.getsize(paths[0])
            except OSError:
                continue
            wasted = size * (len(paths) - 1)
            total_wasted += wasted

            parent = QTreeWidgetItem(self._tree)
            parent.setText(0, f"🔗 {len(paths)} duplicates — {wasted / 1024 / 1024:.1f} MB wasted")
            parent.setText(1, f"{wasted / 1024 / 1024:.1f} MB")
            parent.setText(2, str(len(paths)))
            parent.setExpanded(False)

            for fpath in paths:
                child = QTreeWidgetItem(parent)
                child.setText(0, fpath)
                try:
                    mtime = os.path.getmtime(fpath)
                    child.setText(2, datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d"))
                except OSError:
                    pass

        self._status_label.setText(
            f"Found {len(hash_groups)} duplicate groups — {total_wasted / 1024 / 1024:.1f} MB total wasted space"
        )
