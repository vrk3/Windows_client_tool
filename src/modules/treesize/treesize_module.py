import csv
import os
import shutil
import string
import threading
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QTreeView, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from modules.treesize.disk_scanner import DiskScanner
from modules.treesize.disk_tree_model import DiskTreeModel, SizeBarDelegate, format_size


def _get_drives():
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


class TreeSizeModule(BaseModule):
    name = "Tree Size"
    icon = "📊"
    description = "Visualise disk usage by folder and file size"
    requires_admin = False
    group = ModuleGroup.TOOLS

    def __init__(self):
        super().__init__()
        self._widget: QWidget | None = None
        self._scanner: DiskScanner | None = None
        self._scan_thread: threading.Thread | None = None

    def create_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ── top toolbar ──────────────────────────────────────────────────────
        top = QHBoxLayout()
        self._drive_cb = QComboBox()
        self._drive_cb.setFixedWidth(80)
        for d in _get_drives():
            self._drive_cb.addItem(d)

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Path to scan…")
        if self._drive_cb.count():
            self._path_edit.setText(self._drive_cb.currentText())

        self._scan_btn = QPushButton("Scan")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()

        top.addWidget(QLabel("Drive:"))
        top.addWidget(self._drive_cb)
        top.addWidget(QLabel("Path:"))
        top.addWidget(self._path_edit, 1)
        top.addWidget(self._scan_btn)
        top.addWidget(self._stop_btn)
        layout.addLayout(top)
        layout.addWidget(self._progress)

        # ── filter + export bar ───────────────────────────────────────────────
        fbar = QHBoxLayout()
        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 100_000)
        self._min_spin.setSuffix(" MB")
        self._min_spin.setFixedWidth(100)
        apply_filter_btn = QPushButton("Apply Filter")
        export_btn = QPushButton("Export CSV")
        fbar.addWidget(QLabel("Min size:"))
        fbar.addWidget(self._min_spin)
        fbar.addWidget(apply_filter_btn)
        fbar.addStretch()
        fbar.addWidget(export_btn)
        layout.addLayout(fbar)

        # ── breadcrumb ────────────────────────────────────────────────────────
        self._breadcrumb = QLabel("")
        self._breadcrumb.setWordWrap(False)
        layout.addWidget(self._breadcrumb)

        # ── tree view ─────────────────────────────────────────────────────────
        self._model = DiskTreeModel()
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        delegate = SizeBarDelegate()
        self._tree.setItemDelegateForColumn(1, delegate)
        hdr = self._tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.resizeSection(1, 160)
        hdr.setStretchLastSection(False)
        hdr.setSortIndicatorShown(True)
        self._tree.setSortingEnabled(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(self._tree, 1)

        # ── status bar ────────────────────────────────────────────────────────
        self._status_lbl = QLabel("Ready")
        layout.addWidget(self._status_lbl)

        # ── connections ─────────────────────────────────────────────────────
        self._scan_btn.clicked.connect(self._do_scan)
        self._stop_btn.clicked.connect(self._do_stop)
        self._drive_cb.currentTextChanged.connect(self._on_drive_changed)
        self._tree.doubleClicked.connect(self._on_double_click)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        export_btn.clicked.connect(self._do_export)
        apply_filter_btn.clicked.connect(self._do_apply_filter)

        self._widget = w
        return w

    # ── scan helpers ─────────────────────────────────────────────────────────

    def _do_scan(self):
        path = self._path_edit.text().strip()
        if not path or not os.path.isdir(path):
            self._status_lbl.setText("Invalid path.")
            return
        self._breadcrumb.setText(path)
        self._model.clear()
        self._scan_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._progress.setRange(0, 0)
        self._progress.show()
        self._status_lbl.setText("Scanning…")

        self._scanner = DiskScanner()
        self._scanner.signals.batch_ready.connect(self._on_batch_ready)
        self._scanner.signals.node_replaced.connect(self._on_node_replaced)
        self._scanner.signals.progress.connect(
            lambda n: self._status_lbl.setText(f"Scanned {n} nodes…")
        )
        self._scanner.signals.finished.connect(self._on_scan_finished)
        self._scanner.signals.error.connect(self._on_scan_error)

        self._scan_thread = threading.Thread(
            target=self._scanner.scan, args=(path,), daemon=True
        )
        self._scan_thread.start()

    def _on_batch_ready(self, nodes):
        # add_batch is safe to call from the scanner's background thread
        # because Qt signals are delivered on the main thread
        self._model.add_batch(nodes)

    def _on_node_replaced(self, node):
        """Handle a fully-scanned subtree replacing its stub."""
        self._model.replace_node(node)

    def _on_scan_finished(self):
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.hide()
        roots = self._model._roots
        total_size = sum(r.size for r in roots)
        total_files = sum(r.file_count for r in roots)
        self._status_lbl.setText(
            f"{len(roots)} item(s) — {format_size(total_size)} — {total_files:,} files"
        )
        self._tree.expandToDepth(0)

    def _on_scan_error(self, msg: str):
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.hide()
        self._status_lbl.setText(f"Error: {msg}")

    def _do_stop(self):
        if self._scanner is not None:
            self._scanner.cancel()
        self._stop_btn.setEnabled(False)

    def _on_drive_changed(self, text: str):
        self._path_edit.setText(text)

    def _on_double_click(self, index):
        node = self._model.data(index, Qt.ItemDataRole.UserRole)
        if node and node.is_dir:
            self._path_edit.setText(node.path)
            self._do_scan()

    def _on_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        node = self._model.data(index, Qt.ItemDataRole.UserRole)
        if not node:
            return
        menu = QMenu(self._tree)
        open_act = menu.addAction("Open in Explorer")
        del_act = menu.addAction("Delete…")
        menu.addSeparator()
        prop_act = menu.addAction("Properties")
        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if chosen == open_act:
            target = node.path if node.is_dir else os.path.dirname(node.path)
            os.startfile(target)
        elif chosen == del_act:
            reply = QMessageBox.question(
                self._widget, "Delete", f"Delete '{node.path}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    if node.is_dir:
                        shutil.rmtree(node.path, ignore_errors=True)
                    else:
                        os.remove(node.path)
                    self._do_scan()
                except OSError as e:
                    QMessageBox.warning(self._widget, "Delete failed", str(e))
        elif chosen == prop_act:
            QMessageBox.information(
                self._widget, "Properties",
                f"Path: {node.path}\nSize: {format_size(node.size)}\nFiles: {node.file_count}",
            )

    def _do_export(self):
        if not self._widget:
            return
        path, _ = QFileDialog.getSaveFileName(
            self._widget, "Export CSV", "", "CSV files (*.csv)"
        )
        if not path:
            return

        def collect(node, rows):
            mod = ""
            if node.last_modified:
                import datetime
                mod = datetime.datetime.fromtimestamp(node.last_modified).strftime(
                    "%Y-%m-%d %H:%M"
                )
            rows.append([node.path, format_size(node.size), node.file_count, mod])
            for child in node.children:
                collect(child, rows)

        rows = [["Path", "Size", "Files", "Last Modified"]]
        for root in self._model._roots:
            collect(root, rows)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        self._status_lbl.setText(f"Exported {len(rows)-1} rows to {os.path.basename(path)}")

    def _do_apply_filter(self):
        mb = self._min_spin.value()
        self._model.set_min_size_filter(mb * 1024 * 1024)

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        self._do_stop()

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self._do_stop()
