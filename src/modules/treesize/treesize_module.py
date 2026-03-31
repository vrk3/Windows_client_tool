import os
import csv
import string
import threading
from typing import Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeView,
    QLabel, QComboBox, QLineEdit, QProgressBar, QMenu, QSpinBox,
    QHeaderView, QMessageBox, QFileDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtGui import QAction

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

    def create_widget(self, parent=None) -> QWidget:
        w = QWidget(parent)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ── top toolbar ──────────────────────────────────────────────────────
        top = QHBoxLayout()
        drive_cb = QComboBox()
        drive_cb.setFixedWidth(80)
        for d in _get_drives():
            drive_cb.addItem(d)

        path_edit = QLineEdit()
        path_edit.setPlaceholderText("Path to scan…")
        if drive_cb.count():
            path_edit.setText(drive_cb.currentText())

        scan_btn = QPushButton("Scan")
        stop_btn = QPushButton("Stop")
        stop_btn.setEnabled(False)

        progress = QProgressBar()
        progress.setTextVisible(False)
        progress.setFixedHeight(4)
        progress.hide()

        top.addWidget(QLabel("Drive:"))
        top.addWidget(drive_cb)
        top.addWidget(QLabel("Path:"))
        top.addWidget(path_edit, 1)
        top.addWidget(scan_btn)
        top.addWidget(stop_btn)
        layout.addLayout(top)
        layout.addWidget(progress)

        # ── filter + export bar ───────────────────────────────────────────────
        fbar = QHBoxLayout()
        min_spin = QSpinBox()
        min_spin.setRange(0, 100_000)
        min_spin.setSuffix(" MB")
        min_spin.setFixedWidth(100)
        apply_filter_btn = QPushButton("Apply Filter")
        export_btn = QPushButton("Export CSV")
        fbar.addWidget(QLabel("Min size:"))
        fbar.addWidget(min_spin)
        fbar.addWidget(apply_filter_btn)
        fbar.addStretch()
        fbar.addWidget(export_btn)
        layout.addLayout(fbar)

        # ── breadcrumb ────────────────────────────────────────────────────────
        breadcrumb = QLabel("")
        breadcrumb.setWordWrap(False)
        layout.addWidget(breadcrumb)

        # ── tree view ─────────────────────────────────────────────────────────
        model = DiskTreeModel()
        tree = QTreeView()
        tree.setModel(model)
        delegate = SizeBarDelegate()
        tree.setItemDelegateForColumn(1, delegate)
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        tree.header().resizeSection(1, 160)
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        layout.addWidget(tree, 1)

        # ── status bar ────────────────────────────────────────────────────────
        status_lbl = QLabel("Ready")
        layout.addWidget(status_lbl)

        # ── state ─────────────────────────────────────────────────────────────
        scanner_ref: list = [None]   # [DiskScanner | None]
        thread_ref: list = [None]    # [threading.Thread | None]

        # ── helpers ───────────────────────────────────────────────────────────
        def do_scan():
            path = path_edit.text().strip()
            if not path or not os.path.isdir(path):
                status_lbl.setText("Invalid path.")
                return
            breadcrumb.setText(path)
            model.clear()
            scan_btn.setEnabled(False)
            stop_btn.setEnabled(True)
            progress.setRange(0, 0)
            progress.show()
            status_lbl.setText("Scanning…")

            scanner = DiskScanner()
            scanner_ref[0] = scanner
            scanner.signals.batch_ready.connect(model.add_batch)
            scanner.signals.progress.connect(lambda n: status_lbl.setText(f"Scanned {n} nodes…"))
            scanner.signals.finished.connect(on_scan_finished)
            scanner.signals.error.connect(on_scan_error)

            t = threading.Thread(target=scanner.scan, args=(path,), daemon=True)
            thread_ref[0] = t
            t.start()

        def on_scan_finished():
            scan_btn.setEnabled(True)
            stop_btn.setEnabled(False)
            progress.hide()
            roots = model._roots
            total_size = sum(r.size for r in roots)
            total_files = sum(r.file_count for r in roots)
            status_lbl.setText(
                f"{len(roots)} item(s) — {format_size(total_size)} — {total_files:,} files"
            )
            tree.expandToDepth(0)

        def on_scan_error(msg: str):
            scan_btn.setEnabled(True)
            stop_btn.setEnabled(False)
            progress.hide()
            status_lbl.setText(f"Error: {msg}")

        def do_stop():
            if scanner_ref[0]:
                scanner_ref[0].cancel()
            stop_btn.setEnabled(False)

        def on_drive_changed(text: str):
            path_edit.setText(text)

        def on_double_click(index):
            node = model.data(index, Qt.ItemDataRole.UserRole)
            if node and node.is_dir:
                path_edit.setText(node.path)
                do_scan()

        def on_context_menu(pos):
            index = tree.indexAt(pos)
            if not index.isValid():
                return
            node = model.data(index, Qt.ItemDataRole.UserRole)
            if not node:
                return
            menu = QMenu(tree)
            open_act = menu.addAction("Open in Explorer")
            del_act = menu.addAction("Delete…")
            menu.addSeparator()
            prop_act = menu.addAction("Properties")
            chosen = menu.exec(tree.viewport().mapToGlobal(pos))
            if chosen == open_act:
                target = node.path if node.is_dir else os.path.dirname(node.path)
                os.startfile(target)
            elif chosen == del_act:
                reply = QMessageBox.question(
                    w, "Delete", f"Delete '{node.path}'?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    try:
                        import shutil
                        if node.is_dir:
                            shutil.rmtree(node.path, ignore_errors=True)
                        else:
                            os.remove(node.path)
                        do_scan()
                    except OSError as e:
                        QMessageBox.warning(w, "Delete failed", str(e))
            elif chosen == prop_act:
                QMessageBox.information(
                    w, "Properties",
                    f"Path: {node.path}\nSize: {format_size(node.size)}\nFiles: {node.file_count}",
                )

        def do_export():
            path, _ = QFileDialog.getSaveFileName(w, "Export CSV", "", "CSV files (*.csv)")
            if not path:
                return
            def _collect(node, rows):
                import datetime
                mod = datetime.datetime.fromtimestamp(node.last_modified).strftime(
                    "%Y-%m-%d %H:%M") if node.last_modified else ""
                rows.append([node.path, format_size(node.size), node.file_count, mod])
                for child in node.children:
                    _collect(child, rows)
            rows = [["Path", "Size", "Files", "Last Modified"]]
            for root in model._roots:
                _collect(root, rows)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            status_lbl.setText(f"Exported {len(rows)-1} rows to {os.path.basename(path)}")

        def do_apply_filter():
            mb = min_spin.value()
            model.set_min_size_filter(mb * 1024 * 1024)

        # ── connections ───────────────────────────────────────────────────────
        scan_btn.clicked.connect(do_scan)
        stop_btn.clicked.connect(do_stop)
        drive_cb.currentTextChanged.connect(on_drive_changed)
        tree.doubleClicked.connect(on_double_click)
        tree.customContextMenuRequested.connect(on_context_menu)
        export_btn.clicked.connect(do_export)
        apply_filter_btn.clicked.connect(do_apply_filter)

        return w

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        pass
