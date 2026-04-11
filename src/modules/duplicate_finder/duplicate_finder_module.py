"""Duplicate File Finder — locate and remove duplicate files by hash."""
import datetime
import hashlib
import os
import shutil
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QMessageBox, QProgressBar, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtGui import QCursor

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
import logging

logger = logging.getLogger(__name__)

# Column indices
COL_PATH, COL_SIZE, COL_DATE = range(3)
COL_HEADERS = ["File Path", "Size", "Modified"]


class DuplicateFinderModule(BaseModule):
    name = "Duplicate Finder"
    icon = "🔍"
    description = "Find and remove duplicate files by content hash"
    group = ModuleGroup.TOOLS
    requires_admin = False

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._worker: Optional[Worker] = None
        self._scan_folder: str = ""

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # ── Folder selection row ─────────────────────────────────────────────
        folder_row = QHBoxLayout()
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText("Select a folder to scan for duplicates…")
        folder_row.addWidget(self._path_input, 1)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_btn)

        self._scan_btn = QPushButton("🔍 Scan")
        self._scan_btn.setStyleSheet("font-weight: bold;")
        self._scan_btn.clicked.connect(self._start_scan)
        folder_row.addWidget(self._scan_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop_scan)
        folder_row.addWidget(self._stop_btn)

        layout.addLayout(folder_row)

        # ── Progress bar ────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        self._progress.setFormat("Scanning… %p%")
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        self._phase_lbl = QLabel("")
        self._phase_lbl.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._phase_lbl)

        # ── Action toolbar ──────────────────────────────────────────────────
        action_row = QHBoxLayout()

        self._select_oldest_btn = QPushButton("☑ Select Duplicates (Keep Oldest)")
        self._select_oldest_btn.setEnabled(False)
        self._select_oldest_btn.clicked.connect(self._select_keep_oldest)
        action_row.addWidget(self._select_oldest_btn)

        self._select_newest_btn = QPushButton("☑ Select Duplicates (Keep Newest)")
        self._select_newest_btn.setEnabled(False)
        self._select_newest_btn.clicked.connect(self._select_keep_newest)
        action_row.addWidget(self._select_newest_btn)

        action_row.addStretch()

        self._delete_btn = QPushButton("🗑 Delete Selected")
        self._delete_btn.setStyleSheet("color: #FF6B6B; font-weight: bold;")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._delete_selected)
        action_row.addWidget(self._delete_btn)

        layout.addLayout(action_row)

        # ── Results tree ────────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(COL_HEADERS)
        self._tree.setColumnWidth(COL_PATH, 420)
        self._tree.setAlternatingRowColors(True)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemChanged.connect(self._on_item_check_changed)
        self._tree.setStyleSheet("""
            QTreeWidget {
                background: #2d2d2d; color: #e0e0e0;
                border: 1px solid #3c3c3c; border-radius: 4px;
            }
            QTreeWidget::item { padding: 3px 4px; }
            QTreeWidget::item:selected { background: #094771; }
            QTreeWidget::item > td { border: none; }
            QHeaderView::section {
                background: #3c3c3c; color: #b0b0b0;
                padding: 4px; border: none;
            }
        """)
        layout.addWidget(self._tree, 1)

        # ── Status bar ─────────────────────────────────────────────────────
        status_row = QHBoxLayout()
        self._status_lbl = QLabel("Ready — select a folder and click Scan")
        self._status_lbl.setStyleSheet("color: #888; font-size: 12px;")
        status_row.addWidget(self._status_lbl)

        status_row.addStretch()

        self._freed_lbl = QLabel("Freed: —")
        self._freed_lbl.setStyleSheet("color: #4CAF50; font-size: 12px; font-weight: bold;")
        status_row.addWidget(self._freed_lbl)

        layout.addLayout(status_row)

        return self._widget

    # ── lifecycle ────────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        self._stop_scan()

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self._stop_scan()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self._widget, "Select Folder to Scan", "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if folder:
            self._path_input.setText(folder)

    def _start_scan(self):
        folder = self._path_input.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(
                self._widget, "Invalid Folder",
                "Please select a valid folder to scan.",
            )
            return

        self._scan_folder = folder
        self._tree.clear()
        self._freed_lbl.setText("Freed: —")
        self._delete_btn.setEnabled(False)
        self._select_oldest_btn.setEnabled(False)
        self._select_newest_btn.setEnabled(False)
        self._status_lbl.setText("Phase 1: Grouping files by size…")
        self._phase_lbl.setText("Scanning directory tree…")
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        self._progress.setFormat("Discovering files… %p%")
        self._scan_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)

        def do_scan(worker):
            # ── Phase 1: group by size ─────────────────────────────────────
            files_by_size: Dict[int, List[str]] = {}
            for root, dirs, files in os.walk(folder):
                if worker.is_cancelled:
                    return None
                for fname in files:
                    fpath = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(fpath)
                        if size > 0:
                            files_by_size.setdefault(size, []).append(fpath)
                    except OSError:
                        continue

            # Filter to only groups with 2+ files (potential dupes)
            candidates = {s: p for s, p in files_by_size.items() if len(p) > 1}
            total_files = sum(len(v) for v in candidates.values())
            worker.signals.progress.emit(0)

            if total_files == 0:
                return {}

            # ── Phase 2: hash duplicate-size files ──────────────────────────
            hash_groups: Dict[str, List[str]] = {}
            done = 0
            for size, paths in candidates.items():
                if worker.is_cancelled:
                    return None
                for fpath in paths:
                    try:
                        with open(fpath, "rb") as f:
                            md5 = hashlib.md5(f.read()).hexdigest()
                        hash_groups.setdefault(md5, []).append(fpath)
                    except OSError:
                        continue
                    done += 1
                    if done % 20 == 0:
                        worker.signals.progress.emit(int(done / total_files * 100))

            worker.signals.progress.emit(100)
            # Keep only true duplicates
            return {h: p for h, p in hash_groups.items() if len(p) > 1}

        self._worker = Worker(do_scan)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.result.connect(self._on_results)
        self._worker.signals.error.connect(self._on_error)
        self.app.thread_pool.start(self._worker)

    def _stop_scan(self):
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._phase_lbl.setText("")

    def _on_progress(self, pct: int):
        self._progress.setFormat(f"Hashing files… {pct}%")

    def _on_error(self, msg: str):
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._phase_lbl.setText("")
        self._status_lbl.setText(f"Error: {msg}")

    # ── results display ──────────────────────────────────────────────────────

    def _on_results(self, hash_groups):
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._progress.setVisible(False)
        self._phase_lbl.setText("")
        self._worker = None

        if hash_groups is None:
            self._status_lbl.setText("Scan cancelled.")
            return

        if not hash_groups:
            self._status_lbl.setText("No duplicates found in this folder.")
            return

        self._hash_groups = hash_groups
        total_wasted = 0

        for md5, paths in sorted(hash_groups.items(), key=lambda x: -len(x[1])):
            try:
                size = os.path.getsize(paths[0])
            except OSError:
                continue
            wasted = size * (len(paths) - 1)
            total_wasted += wasted

            # Parent group row — not a checkbox (always "group header")
            parent = QTreeWidgetItem(self._tree)
            parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            parent.setText(COL_PATH, f"  🔗  {len(paths)} duplicates — {self._fmt_size(wasted)} wasted")
            parent.setText(COL_SIZE, self._fmt_size(wasted))
            parent.setText(COL_DATE, f"{len(paths)} files")
            parent.setExpanded(False)

            # Sort children by mtime
            path_times = []
            for fpath in paths:
                try:
                    mtime = os.path.getmtime(fpath)
                except OSError:
                    mtime = 0
                path_times.append((mtime, fpath))
            path_times.sort()

            for mtime, fpath in path_times:
                child = QTreeWidgetItem(parent)
                child.setFlags(
                    child.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                )
                child.setCheckState(COL_PATH, Qt.CheckState.Unchecked)
                child.setText(COL_PATH, fpath)
                child.setText(COL_SIZE, self._fmt_size(size))
                child.setText(COL_DATE, datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"))
                # Store path in UserRole for retrieval
                child.setData(COL_PATH, Qt.ItemDataRole.UserRole, fpath)

        self._tree.setCurrentItem(None)
        self._delete_btn.setEnabled(True)
        self._select_oldest_btn.setEnabled(True)
        self._select_newest_btn.setEnabled(True)
        self._status_lbl.setText(
            f"Found {len(hash_groups)} duplicate groups — "
            f"{self._fmt_size(total_wasted)} wasted across {sum(len(v) for v in hash_groups.values())} files"
        )

    # ── selection helpers ───────────────────────────────────────────────────

    def _select_keep_oldest(self):
        """Check all but the oldest file in each group."""
        self._select_keep_by_mtime(ascending=True)

    def _select_keep_newest(self):
        """Check all but the newest file in each group."""
        self._select_keep_by_mtime(ascending=False)

    def _select_keep_by_mtime(self, ascending: bool):
        """Check duplicate children, leaving only min/max mtime unchecked."""
        self._tree.blockSignals(True)
        try:
            for i in range(self._tree.topLevelItemCount()):
                group = self._tree.topLevelItem(i)
                children = [group.child(j) for j in range(group.childCount())]
                if not children:
                    continue
                # Sort by mtime
                rows = []
                for c in children:
                    fpath = c.data(COL_PATH, Qt.ItemDataRole.UserRole) or ""
                    try:
                        mtime = os.path.getmtime(fpath)
                    except OSError:
                        mtime = 0
                    rows.append((mtime, c))
                rows.sort(key=lambda x: x[0], reverse=not ascending)
                # Check all except first (oldest/newest)
                for _, child in rows[1:]:
                    child.setCheckState(COL_PATH, Qt.CheckState.Checked)
        finally:
            self._tree.blockSignals(False)
        self._update_freed_preview()

    def _on_item_check_changed(self, item, column):
        if item.parent() is None:
            return  # group header, ignore
        self._update_freed_preview()

    def _update_freed_preview(self):
        """Sum up sizes of checked (to-delete) items."""
        total = 0
        count = 0
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.checkState(COL_PATH) == Qt.CheckState.Checked:
                    fpath = child.data(COL_PATH, Qt.ItemDataRole.UserRole) or ""
                    try:
                        total += os.path.getsize(fpath)
                        count += 1
                    except OSError:
                        pass
        if count > 0:
            self._freed_lbl.setText(f"🗑 To delete: {count} files ({self._fmt_size(total)})")
        else:
            self._freed_lbl.setText("Freed: —")

    # ── deletion ─────────────────────────────────────────────────────────────

    def _delete_selected(self):
        checked_paths = []
        for i in range(self._tree.topLevelItemCount()):
            group = self._tree.topLevelItem(i)
            for j in range(group.childCount()):
                child = group.child(j)
                if child.checkState(COL_PATH) == Qt.CheckState.Checked:
                    fpath = child.data(COL_PATH, Qt.ItemDataRole.UserRole) or ""
                    if fpath:
                        checked_paths.append(fpath)

        if not checked_paths:
            QMessageBox.information(
                self._widget, "Nothing Selected",
                "Select some duplicate files to delete using the checkboxes.",
            )
            return

        total_size = sum(os.path.getsize(p) for p in checked_paths if os.path.exists(p))
        reply = QMessageBox.warning(
            self._widget,
            "Delete Files",
            f"Permanently delete {len(checked_paths)} file(s) ({self._fmt_size(total_size)})?\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = 0
        failed = 0
        freed = 0
        for fpath in checked_paths:
            if not os.path.exists(fpath):
                continue
            try:
                os.remove(fpath)
                freed += os.path.getsize(fpath) if os.path.exists(fpath) else 0
                deleted += 1
                # Remove from tree
                for i in range(self._tree.topLevelItemCount()):
                    group = self._tree.topLevelItem(i)
                    for j in range(group.childCount()):
                        child = group.child(j)
                        if child.data(COL_PATH, Qt.ItemDataRole.UserRole) == fpath:
                            group.removeChild(child)
                            break
            except OSError as e:
                logger.warning("Failed to delete %s: %s", fpath, e)
                failed += 1

        # Remove empty groups
        for i in range(self._tree.topLevelItemCount() - 1, -1, -1):
            group = self._tree.topLevelItem(i)
            if group.childCount() == 0:
                self._tree.takeTopLevelItem(i)
            elif group.childCount() == 1:
                # Only one file left — no longer duplicate, remove group
                self._tree.takeTopLevelItem(i)

        self._freed_lbl.setText(
            f"✅ Deleted {deleted} file(s) — {self._fmt_size(freed)} freed"
        )
        remaining = self._tree.topLevelItemCount()
        self._status_lbl.setText(
            f"Deleted {deleted} file(s). {remaining} duplicate group(s) remain."
        )

    # ── context menu ───────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None:
            return
        # Only show for child items (files), not group headers
        if item.parent() is None:
            # Group header — show "collapse all / expand all"
            menu = QMenu(self._tree)
            menu.addAction("Expand All Groups", self._tree.expandAll)
            menu.addAction("Collapse All Groups", self._tree.collapseAll)
            menu.exec(QCursor.pos())
            return

        menu = QMenu(self._tree)
        menu.addAction("Open File Location", lambda: self._open_location(item))
        menu.addAction("Delete This File", lambda: self._delete_single(item))
        menu.addSeparator()
        menu.addAction("Select All in Group", lambda: self._select_group(item, True))
        menu.addAction("Deselect All in Group", lambda: self._select_group(item, False))
        menu.exec(QCursor.pos())

    def _open_location(self, item: QTreeWidgetItem):
        fpath = item.data(COL_PATH, Qt.ItemDataRole.UserRole) or ""
        if fpath and os.path.isfile(fpath):
            os.startfile(os.path.dirname(fpath))

    def _delete_single(self, item: QTreeWidgetItem):
        fpath = item.data(COL_PATH, Qt.ItemDataRole.UserRole) or ""
        if not fpath:
            return
        reply = QMessageBox.warning(
            self._widget,
            "Delete File",
            f"Delete this file?\n\n{fpath}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            size = os.path.getsize(fpath)
            os.remove(fpath)
            parent = item.parent()
            if parent:
                parent.removeChild(item)
                self._freed_lbl.setText(f"✅ Deleted — {self._fmt_size(size)} freed")
        except OSError as e:
            QMessageBox.warning(self._widget, "Delete Failed", str(e))

    def _select_group(self, item: QTreeWidgetItem, checked: bool):
        parent = item.parent()
        if parent is None:
            return
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(parent.childCount()):
            parent.child(i).setCheckState(COL_PATH, state)
        self._update_freed_preview()

    # ── util ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
