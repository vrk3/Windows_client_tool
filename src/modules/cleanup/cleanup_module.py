"""
Cleanup module — 8-tab overhaul.

Tabs: Overview · System Junk · Browser Caches · App & Game Caches ·
      Windows Update · Logs & Reports · Large Items · Dev Tools

Cross-cutting: auto-scan on first tab switch, safety colour-coding,
age filter per tab, running-process guard, >500 MB confirmation,
error panel, freed-session counter, DISM button on Large Items.
"""
import os
import subprocess
from typing import List, Optional, Tuple

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget,
    QTreeWidgetItem, QLabel, QTabWidget, QProgressBar, QMenu,
    QHeaderView, QFrame, QSpinBox, QMessageBox, QTableWidget,
    QTableWidgetItem, QTextEdit,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.cleanup import cleanup_scanner as cs
from modules.cleanup import browser_scanner as bs


# ── Safety colour helpers ─────────────────────────────────────────────────────

SAFETY_STYLES = {
    "safe":    ("#4caf50", "Safe"),
    "caution": ("#ff9800", "Caution"),
    "danger":  ("#f44336", "Risky"),
}

CONFIRM_BYTES = 500 * 1024 * 1024   # 500 MB


def _sc(level: str) -> str:
    return SAFETY_STYLES.get(level, ("#888888", ""))[0]


def _confirm_large(parent: QWidget, nbytes: int) -> bool:
    if nbytes < CONFIRM_BYTES:
        return True
    mb = QMessageBox(parent)
    mb.setWindowTitle("Confirm Delete")
    mb.setIcon(QMessageBox.Icon.Warning)
    mb.setText(
        f"You are about to permanently delete <b>{cs.format_size(nbytes)}</b>."
        "<br>This cannot be undone."
    )
    mb.setStandardButtons(
        QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
    )
    mb.setDefaultButton(QMessageBox.StandardButton.Cancel)
    return mb.exec() == QMessageBox.StandardButton.Ok


# ── _ScanTab ──────────────────────────────────────────────────────────────────

class _ScanTab(QWidget):
    """
    Generic scan/clean tab supporting multiple scanners.

    scanners: dict  { scanner_fn: (display_label, safety_level) }
    wu_cache: True if wuauserv must be stopped during clean.
    """
    freed_bytes = pyqtSignal(int)

    def __init__(self, scanners: dict, wu_cache: bool = False, parent=None):
        super().__init__(parent)
        self._scanners = scanners
        self._wu_cache = wu_cache
        self._result: Optional[cs.ScanResult] = None
        self._scanning = False
        self._cleaning = False
        self._scanned  = False
        self._pending_freed = 0
        self._workers: list = []   # track ALL workers (scan + clean) for cancellation
        self._thread_pool = QThreadPool.globalInstance()
        self._setup_ui()

    # ── Setup ──

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        tb = QHBoxLayout()
        self._scan_btn   = QPushButton("Scan")
        self._clean_btn  = QPushButton("Clean Selected")
        self._quick_btn  = QPushButton("Quick Clean (Safe Only)")
        self._sel_btn    = QPushButton("Select All")
        self._desel_btn  = QPushButton("Deselect All")
        self._age_lbl    = QLabel("Age filter:")
        self._age_spin   = QSpinBox()
        self._age_spin.setRange(0, 3650)
        self._age_spin.setValue(0)
        self._age_spin.setSuffix(" days")
        self._age_spin.setToolTip(
            "Only include files/folders older than this many days (0 = no filter)"
        )
        self._status     = QLabel("Ready — click Scan or switch to this tab")
        self._clean_btn.setEnabled(False)
        self._quick_btn.setEnabled(False)

        for w in (self._scan_btn, self._clean_btn, self._quick_btn,
                  self._sel_btn, self._desel_btn):
            tb.addWidget(w)
        tb.addStretch()
        tb.addWidget(self._age_lbl)
        tb.addWidget(self._age_spin)
        tb.addWidget(self._status)
        layout.addLayout(tb)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Tree
        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Path / Category", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._ctx_menu)
        layout.addWidget(self._tree, 1)

        # Safety legend
        legend = QHBoxLayout()
        legend.setSpacing(12)
        for level, (color, label) in SAFETY_STYLES.items():
            dot = QLabel(f"<span style='color:{color};font-size:16px'>●</span>")
            lbl = QLabel(f"<span style='color:{color}'>{label}</span>")
            lbl.setStyleSheet("font-size:11px")
            legend.addWidget(dot)
            legend.addWidget(lbl)
        legend.addStretch()
        layout.addLayout(legend)

        # Error label
        self._err_lbl = QLabel()
        self._err_lbl.setStyleSheet("color: #f44336;")
        self._err_lbl.setWordWrap(True)
        self._err_lbl.hide()
        layout.addWidget(self._err_lbl)

        self._scan_btn.clicked.connect(self._do_scan)
        self._clean_btn.clicked.connect(self._do_clean)
        self._quick_btn.clicked.connect(self._do_quick_clean)
        self._sel_btn.clicked.connect(self._select_all)
        self._desel_btn.clicked.connect(self._deselect_all)

    # ── Public ──

    def auto_scan(self):
        """Scan automatically on first activation."""
        if not self._scanned:
            self._do_scan()

    # ── Scan ──

    def _do_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scanned  = True
        self._scan_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        self._quick_btn.setEnabled(False)
        self._tree.clear()
        self._err_lbl.hide()
        self._status.setText("Scanning…")
        self._progress.setRange(0, 0)
        self._progress.show()

        min_age = self._age_spin.value()
        scanner_fns = list(self._scanners.keys())

        def _run(_w):
            per: dict = {}
            for fn in scanner_fns:
                try:
                    r = fn(min_age_days=min_age)
                    if r:
                        per[fn] = r
                except Exception:
                    pass
            merged = cs.ScanResult()
            for r in per.values():
                merged.items.extend(r.items)
                merged.total_size += r.total_size
            return merged, per

        self._worker = Worker(_run)
        self._worker.signals.result.connect(self._on_scan_result)
        self._worker.signals.error.connect(self._on_scan_error)
        self._workers.append(self._worker)
        self._thread_pool.start(self._worker)

    def _on_scan_result(self, data):
        merged, per_scanner = data
        self._result  = merged
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._tree.clear()

        # Build path → (label, safety) lookup
        path_info: dict = {}
        for fn, (label, safety) in self._scanners.items():
            r = per_scanner.get(fn)
            if r:
                for item in r.items:
                    path_info[item.path] = (label, safety)

        # Group by scanner label → collapsible parent nodes
        grouped: dict = {}
        for item in merged.items:
            label, safety = path_info.get(item.path, ("Other", item.safety))
            if label not in grouped:
                grouped[label] = {"safety": safety, "items": []}
            grouped[label]["items"].append(item)

        # Sort groups by total size descending
        for label, group in sorted(
            grouped.items(),
            key=lambda kv: sum(i.size for i in kv[1]["items"]),
            reverse=True,
        ):
            safety = group["safety"]
            items  = sorted(group["items"], key=lambda x: x.size, reverse=True)
            color  = _sc(safety)
            total  = sum(i.size for i in items)

            parent = QTreeWidgetItem(
                [f"{label}  ({len(items)} item(s))", cs.format_size(total)]
            )
            parent.setCheckState(0, Qt.CheckState.Checked)
            parent.setFlags(
                parent.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            parent.setForeground(0, QBrush(QColor(color)))
            parent.setForeground(1, QBrush(QColor(color)))
            parent.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._tree.addTopLevelItem(parent)
            parent.setExpanded(True)

            for item in items:
                child = QTreeWidgetItem([item.path, cs.format_size(item.size)])
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setData(0, Qt.ItemDataRole.UserRole, item)
                child.setForeground(0, QBrush(QColor(color)))
                child.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                parent.addChild(child)

        total_safe = sum(1 for i in merged.items if i.safety == "safe")
        self._status.setText(
            f"{len(merged.items)} item(s)  ({total_safe} safe) — "
            f"{cs.format_size(merged.total_size)}"
        )
        self._clean_btn.setEnabled(len(merged.items) > 0)
        self._quick_btn.setEnabled(total_safe > 0)

    def _on_scan_error(self, err: str):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText(f"Scan error: {err}")

    # ── Clean ──

    def _get_selected_items(self) -> List[cs.ScanItem]:
        items = []
        for i in range(self._tree.topLevelItemCount()):
            tw = self._tree.topLevelItem(i)
            for j in range(tw.childCount()):
                child = tw.child(j)
                si: cs.ScanItem = child.data(0, Qt.ItemDataRole.UserRole)
                if si is not None:
                    si.selected = child.checkState(0) == Qt.CheckState.Checked
                    items.append(si)
        return items

    def _do_clean(self):
        if self._cleaning or self._result is None:
            return
        selected = self._get_selected_items()
        to_delete = [i for i in selected if i.selected]
        if not to_delete:
            return

        total = sum(i.size for i in to_delete)
        if not _confirm_large(self, total):
            return

        self._cleaning = True
        self._pending_freed = total
        self._clean_btn.setEnabled(False)
        self._quick_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._status.setText("Cleaning…")
        self._err_lbl.hide()
        self._progress.setRange(0, 0)
        self._progress.show()

        wu = self._wu_cache

        def _run(_w):
            return cs.delete_items(selected, stop_wuauserv=wu)

        self._worker = Worker(_run)
        self._worker.signals.result.connect(self._on_clean_done)
        self._worker.signals.error.connect(self._on_clean_error)
        self._workers.append(self._worker)
        self._thread_pool.start(self._worker)

    def _on_clean_done(self, result: Tuple[int, int]):
        deleted, errors = result
        self._cleaning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        msg = f"Cleaned {deleted} item(s)"
        if errors:
            msg += f" — {errors} could not be deleted"
            self._err_lbl.setText(
                f"⚠ {errors} file(s) could not be deleted (in use or access denied)."
            )
            self._err_lbl.show()
        self._status.setText(msg)
        self._clean_btn.setEnabled(False)
        self._quick_btn.setEnabled(False)
        self.freed_bytes.emit(self._pending_freed)
        self._pending_freed = 0
        self._do_scan()

    def _on_clean_error(self, err: str):
        self._cleaning = False
        self._scan_btn.setEnabled(True)
        self._clean_btn.setEnabled(self._result is not None and len(self._result.items) > 0)
        self._quick_btn.setEnabled(
            self._result is not None and any(i.safety == "safe" for i in self._result.items)
        )
        self._progress.hide()
        self._status.setText(f"Clean error: {err}")

    def _do_quick_clean(self):
        """Select only safe items then clean."""
        if self._result is None:
            return
        for i in range(self._tree.topLevelItemCount()):
            tw = self._tree.topLevelItem(i)
            for j in range(tw.childCount()):
                child = tw.child(j)
                si: cs.ScanItem = child.data(0, Qt.ItemDataRole.UserRole)
                if si is not None:
                    checked = Qt.CheckState.Checked if si.safety == "safe" else Qt.CheckState.Unchecked
                    child.setCheckState(0, checked)
        self._do_clean()

    # ── Selection helpers ──

    def _select_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    def _deselect_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)
    def _cancel_all(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()

    def _ctx_menu(self, pos):
        item = self._tree.itemAt(pos)
        if not item:
            return
        si: cs.ScanItem = item.data(0, Qt.ItemDataRole.UserRole)
        if not si:
            return
        menu = QMenu(self)
        open_act = menu.addAction("Open in Explorer")
        if menu.exec(self._tree.viewport().mapToGlobal(pos)) == open_act:
            target = si.path if si.is_dir else os.path.dirname(si.path)
            os.startfile(target)


# ── _BrowserCleanupTab ────────────────────────────────────────────────────────

class _BrowserCleanupTab(QWidget):
    """3-level tree: Browser → Profile → Cache Category."""
    freed_bytes = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scanning = False
        self._cleaning = False
        self._scanned  = False
        self._workers: list = []   # track ALL workers for cancellation
        self._thread_pool = QThreadPool.globalInstance()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        tb = QHBoxLayout()
        self._scan_btn  = QPushButton("Scan")
        self._clean_btn = QPushButton("Delete Selected")
        self._sel_btn   = QPushButton("Select All")
        self._desel_btn = QPushButton("Deselect All")
        self._status    = QLabel("Ready")
        self._clean_btn.setEnabled(False)
        for w in (self._scan_btn, self._clean_btn, self._sel_btn, self._desel_btn):
            tb.addWidget(w)
        tb.addStretch()
        tb.addWidget(self._status)
        layout.addLayout(tb)

        self._warn = QLabel()
        self._warn.setStyleSheet("color: #ff9800; font-weight: bold;")
        self._warn.hide()
        layout.addWidget(self._warn)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["Browser / Profile / Cache Type", "Size"])
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._tree, 1)

        self._scan_btn.clicked.connect(self._do_scan)
        self._clean_btn.clicked.connect(self._do_clean)
        self._sel_btn.clicked.connect(self._select_all)
        self._desel_btn.clicked.connect(self._deselect_all)

    def auto_scan(self):
        if not self._scanned:
            self._do_scan()

    def _do_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scanned  = True
        self._scan_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        self._tree.clear()
        self._warn.hide()
        self._status.setText("Scanning browsers…")
        self._progress.setRange(0, 0)
        self._progress.show()

        self._worker = Worker(lambda _w: bs.detect_browsers())
        self._worker.signals.result.connect(self._on_scan_result)
        self._worker.signals.error.connect(self._on_scan_error)
        self._workers.append(self._worker)
        self._thread_pool.start(self._worker)

    def _on_scan_result(self, browsers):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._tree.clear()

        running = [b.name for b in browsers if b.is_running]
        if running:
            self._warn.setText(
                f"⚠  Running: {', '.join(running)} — close before deleting cache."
            )
            self._warn.show()
        else:
            self._warn.hide()

        total_all = 0
        total_cats = 0
        active = 0
        for browser in browsers:
            if browser.total_bytes == 0:
                continue
            active += 1
            b_item = QTreeWidgetItem([browser.name, cs.format_size(browser.total_bytes)])
            b_item.setCheckState(0, Qt.CheckState.Checked)
            b_item.setFlags(
                b_item.flags()
                | Qt.ItemFlag.ItemIsAutoTristate
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            b_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._tree.addTopLevelItem(b_item)
            b_item.setExpanded(True)
            total_all += browser.total_bytes

            for profile in browser.profiles:
                if profile.total_bytes == 0:
                    continue
                p_item = QTreeWidgetItem([profile.name, cs.format_size(profile.total_bytes)])
                p_item.setCheckState(0, Qt.CheckState.Checked)
                p_item.setFlags(
                    p_item.flags()
                    | Qt.ItemFlag.ItemIsAutoTristate
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                p_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                b_item.addChild(p_item)
                p_item.setExpanded(True)

                for cat in profile.categories:
                    if not cat.exists or cat.size_bytes == 0:
                        continue
                    c_item = QTreeWidgetItem([cat.label, cs.format_size(cat.size_bytes)])
                    c_item.setCheckState(0, Qt.CheckState.Checked)
                    c_item.setFlags(c_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    c_item.setData(0, Qt.ItemDataRole.UserRole, cat)
                    c_item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    p_item.addChild(c_item)
                    total_cats += 1

        if active == 0:
            self._status.setText("No browser caches found.")
        else:
            self._status.setText(
                f"{active} browser(s) — {total_cats} cache(s) — {cs.format_size(total_all)}"
            )
        self._clean_btn.setEnabled(total_cats > 0)

    def _on_scan_error(self, err: str):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText(f"Error: {err}")

    def _collect_checked(self) -> list:
        cats = []
        for i in range(self._tree.topLevelItemCount()):
            b = self._tree.topLevelItem(i)
            for j in range(b.childCount()):
                p = b.child(j)
                for k in range(p.childCount()):
                    c = p.child(k)
                    if c.checkState(0) == Qt.CheckState.Checked:
                        cat = c.data(0, Qt.ItemDataRole.UserRole)
                        if cat is not None:
                            cats.append(cat)
        return cats

    def _do_clean(self):
        if self._cleaning:
            return
        cats = self._collect_checked()
        if not cats:
            return
        total = sum(c.size_bytes for c in cats)
        if not _confirm_large(self, total):
            return
        self._cleaning = True
        self._clean_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._status.setText("Deleting…")
        self._progress.setRange(0, 0)
        self._progress.show()

        self._worker = Worker(lambda _w: bs.delete_selected(cats))
        self._worker.signals.result.connect(self._on_clean_done)
        self._worker.signals.error.connect(self._on_clean_error)
        self._workers.append(self._worker)
        self._thread_pool.start(self._worker)

    def _on_clean_done(self, result):
        freed, errors = result
        self._cleaning = False
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        msg = f"Freed {cs.format_size(freed)}"
        if errors:
            msg += f" ({errors} error(s))"
        self._status.setText(msg)
        self._clean_btn.setEnabled(False)
        self.freed_bytes.emit(freed)
        self._do_scan()

    def _on_clean_error(self, err: str):
        self._cleaning = False
        self._scan_btn.setEnabled(True)
        self._clean_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText(f"Error: {err}")

    def _select_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Checked)

    def _deselect_all(self):
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.CheckState.Unchecked)

    def _cancel_all(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()


# ── _LargeItemsTab ────────────────────────────────────────────────────────────

class _LargeItemsTab(QWidget):
    """Large Items scan tab + DISM Component Store Cleanup button."""
    freed_bytes = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main scan tab
        large_scanners = {
            cs.scan_windows_old:           ("Windows.old",           "caution"),
            cs.scan_recycle_bin:           ("Recycle Bin",           "safe"),
            cs.scan_installer_patch_cache: ("Installer Patch Cache", "danger"),
        }
        self._scan_tab = _ScanTab(large_scanners)
        self._scan_tab.freed_bytes.connect(self.freed_bytes)
        layout.addWidget(self._scan_tab, 1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #444;")
        layout.addWidget(sep)

        # DISM section
        dism = QWidget()
        dism_lay = QVBoxLayout(dism)
        dism_lay.setContentsMargins(8, 6, 8, 8)

        dism_row = QHBoxLayout()
        dism_title = QLabel("<b>DISM Component Store Cleanup</b>")
        self._dism_btn = QPushButton("Run DISM Cleanup")
        self._dism_btn.setToolTip(
            "Runs: DISM /Online /Cleanup-Image /StartComponentCleanup\n"
            "Removes superseded Windows components from WinSxS.\n"
            "Can reclaim 2–10 GB. Takes several minutes. Requires admin."
        )
        dism_row.addWidget(dism_title)
        dism_row.addStretch()
        dism_row.addWidget(self._dism_btn)
        dism_lay.addLayout(dism_row)

        dism_desc = QLabel(
            "Removes superseded Windows update components from the WinSxS store. "
            "Can reclaim 2–10 GB on systems with many cumulative updates. "
            "Takes several minutes and requires administrator privileges."
        )
        dism_desc.setWordWrap(True)
        dism_desc.setStyleSheet("color: #888; font-size: 11px;")
        dism_lay.addWidget(dism_desc)

        self._dism_out = QTextEdit()
        self._dism_out.setReadOnly(True)
        self._dism_out.setFixedHeight(90)
        self._dism_out.hide()
        dism_lay.addWidget(self._dism_out)

        layout.addWidget(dism)
        self._dism_btn.clicked.connect(self._run_dism)
        self._dism_worker: Optional[Worker] = None
        self._dism_thread_pool = QThreadPool.globalInstance()

    def auto_scan(self):
        self._scan_tab.auto_scan()

    def _run_dism(self):
        self._dism_btn.setEnabled(False)
        self._dism_out.clear()
        self._dism_out.show()
        self._dism_out.append("Starting DISM Component Store Cleanup…")
        self._dism_out.append("(This may take several minutes — please wait.)\n")

        def _do(_w):
            proc = subprocess.run(
                ["dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
                capture_output=True, text=True, timeout=600,
                creationflags=0x08000000,   # CREATE_NO_WINDOW
            )
            return (proc.stdout or "") + (proc.stderr or "")

        def _done(output: str):
            self._dism_btn.setEnabled(True)
            self._dism_out.append(output or "(No output)")

        def _err(e: str):
            self._dism_btn.setEnabled(True)
            self._dism_out.append(f"Error: {e}")

        self._dism_worker = Worker(_do)
        self._dism_worker.signals.result.connect(_done)
        self._dism_worker.signals.error.connect(_err)
        self._dism_thread_pool.start(self._dism_worker)

    def _cancel_all(self) -> None:
        self._scan_tab._cancel_all()
        if self._dism_worker is not None:
            self._dism_worker.cancel()
            self._dism_worker = None


# ── _OverviewTab ──────────────────────────────────────────────────────────────

_OV_GROUPS = [
    ("System Junk", [
        cs.scan_temp_files, cs.scan_prefetch, cs.scan_thumbnail_cache, cs.scan_user_crash_dumps,
    ]),
    ("Browser Caches", None),    # handled specially via bs.detect_browsers()
    ("App & Game Caches", [
        cs.scan_app_caches, cs.scan_d3d_shader_cache, cs.scan_appdata_autodiscover,
        cs.scan_steam_cache, cs.scan_stremio_cache, cs.scan_outlook_cache,
        cs.scan_winget_packages, cs.scan_store_app_caches,
    ]),
    ("Windows Update", [
        cs.scan_wu_cache, cs.scan_delivery_optimization,
    ]),
    ("Logs & Reports", [
        cs.scan_windows_logs, cs.scan_event_logs, cs.scan_wer_reports,
        cs.scan_memory_dumps, cs.scan_panther_logs, cs.scan_dmf_logs,
        cs.scan_onedrive_logs, cs.scan_defender_history,
    ]),
    ("Large Items", [
        cs.scan_windows_old, cs.scan_recycle_bin, cs.scan_installer_patch_cache,
    ]),
    ("Dev Tools", [
        cs.scan_dev_tool_caches,
    ]),
]

_OV_COLS = ["Group", "Total Size", "Safe Size", "Items", "Status"]


class _OverviewTab(QWidget):
    """Summary of all cleanup categories — scans all in parallel on first activation."""
    freed_bytes = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: dict = {}    # group_name -> (total_size, safe_size, item_count)
        self._pending  = 0
        self._scanning = False
        self._scanned  = False
        self._scan_workers: list = []
        self._worker: Optional[Worker] = None
        self._thread_pool = QThreadPool.globalInstance()
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        tb = QHBoxLayout()
        self._scan_btn  = QPushButton("Scan All")
        self._clean_btn = QPushButton("Clean All Safe")
        self._status    = QLabel("")
        self._clean_btn.setEnabled(False)
        tb.addWidget(self._scan_btn)
        tb.addWidget(self._clean_btn)
        tb.addStretch()
        tb.addWidget(self._status)
        lay.addLayout(tb)

        self._prog = QProgressBar()
        self._prog.setFixedHeight(4)
        self._prog.setTextVisible(False)
        self._prog.hide()
        lay.addWidget(self._prog)

        # Table
        self._table = QTableWidget(0, len(_OV_COLS))
        self._table.setHorizontalHeaderLabels(_OV_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        lay.addWidget(self._table, 1)

        self._scan_btn.clicked.connect(self._do_scan_all)
        self._clean_btn.clicked.connect(self._do_clean_safe)

    def _build_table(self):
        self._table.setRowCount(0)
        for name, _ in _OV_GROUPS:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem("—"))
            self._table.setItem(row, 2, QTableWidgetItem("—"))
            self._table.setItem(row, 3, QTableWidgetItem("—"))
            status = QTableWidgetItem("Pending…")
            status.setForeground(QColor("#888888"))
            self._table.setItem(row, 4, status)

    def _update_row(self, group_name: str, total: int, safe: int, count: int):
        for row in range(self._table.rowCount()):
            if self._table.item(row, 0).text() == group_name:
                sz = QTableWidgetItem(cs.format_size(total))
                sz.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                sz.setForeground(QColor("#5cb85c" if total == 0 else "#cccccc"))
                self._table.setItem(row, 1, sz)

                sf = QTableWidgetItem(cs.format_size(safe))
                sf.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, 2, sf)

                ct = QTableWidgetItem(str(count))
                ct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, 3, ct)

                status_text = "✓ Clean" if total == 0 else f"{cs.format_size(total)} found"
                st = QTableWidgetItem(status_text)
                st.setForeground(QColor("#5cb85c" if total == 0 else "#cccccc"))
                self._table.setItem(row, 4, st)
                break

    def auto_scan(self):
        if not self._scanned:
            self._build_table()
            self._do_scan_all()

    def _do_scan_all(self):
        if self._scanning:
            return
        self._scanning = True
        self._scanned  = True
        self._results.clear()
        self._scan_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        self._prog.setRange(0, 0)
        self._prog.show()
        self._status.setText("Scanning all categories…")

        # Reset status column
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 4)
            if item:
                item.setText("Scanning…")
                item.setForeground(QColor("#f0ad4e"))

        self._pending = len(_OV_GROUPS)

        for group_name, scanners in _OV_GROUPS:
            def _make_cb(gname=group_name, fns=scanners):
                def _run(_w):
                    total = safe = count = 0
                    if fns is None:
                        # Browser caches — use detect_browsers()
                        try:
                            browsers = bs.detect_browsers()
                            for b in browsers:
                                total += b.total_bytes
                                safe  += b.total_bytes   # browsers are always "safe"
                                count += sum(len(p.categories) for p in b.profiles)
                        except Exception:
                            pass
                    else:
                        for fn in fns:
                            try:
                                r = fn(min_age_days=0)
                                total += r.total_size
                                safe  += sum(i.size for i in r.items if i.safety == "safe")
                                count += len(r.items)
                            except Exception:
                                pass
                    return gname, total, safe, count

                def _res(data):
                    gn, tot, sf, cnt = data
                    self._results[gn] = (tot, sf, cnt)
                    self._pending -= 1
                    self._update_row(gn, tot, sf, cnt)
                    if self._pending == 0:
                        self._scan_done()

                def _err(_e):
                    self._pending -= 1
                    self._update_row(gname, 0, 0, 0)
                    if self._pending == 0:
                        self._scan_done()

                return _run, _res, _err

            run_fn, res_fn, err_fn = _make_cb()
            w = Worker(run_fn)
            w.signals.result.connect(res_fn)
            w.signals.error.connect(err_fn)
            self._scan_workers.append(w)
            self._thread_pool.start(w)

    def _scan_done(self):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._prog.hide()
        total = sum(t for t, _, _ in self._results.values())
        safe  = sum(s for _, s, _ in self._results.values())
        self._status.setText(
            f"Total: {cs.format_size(total)} found — "
            f"{cs.format_size(safe)} in Safe categories"
        )
        self._clean_btn.setEnabled(safe > 0)

    def _do_clean_safe(self):
        """Clean all Safe-tagged items across all scanned categories (non-browser)."""
        all_items: List[cs.ScanItem] = []
        needs_wu = False
        total = 0

        for group_name, scanners in _OV_GROUPS:
            if scanners is None:
                continue  # skip browser (handled by its own tab)
            for fn in scanners:
                try:
                    r = fn(min_age_days=0)
                    for item in r.items:
                        if item.safety == "safe":
                            item.selected = True
                            all_items.append(item)
                            total += item.size
                    if fn == cs.scan_wu_cache:
                        needs_wu = True
                except Exception:
                    pass

        if not all_items:
            return
        if not _confirm_large(self, total):
            return

        self._clean_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._prog.setRange(0, 0)
        self._prog.show()
        self._status.setText("Cleaning Safe categories…")

        def _run(_w):
            return cs.delete_items(all_items, stop_wuauserv=needs_wu)

        def _done(result):
            deleted, errors = result
            self._prog.hide()
            self._scan_btn.setEnabled(True)
            self._status.setText(
                f"Cleaned {deleted} item(s)"
                + (f" — {errors} error(s)" if errors else "")
            )
            self.freed_bytes.emit(total)
            # Re-scan overview
            self._scanned = False
            self._build_table()
            self._do_scan_all()

        def _err(e: str):
            self._prog.hide()
            self._scan_btn.setEnabled(True)
            self._clean_btn.setEnabled(True)
            self._status.setText(f"Error: {e}")

        self._worker = Worker(_run)
        self._worker.signals.result.connect(_done)
        self._worker.signals.error.connect(_err)
        self._thread_pool.start(self._worker)

    def _cancel_all(self) -> None:
        for w in self._scan_workers:
            w.cancel()
        self._scan_workers.clear()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

class CleanupModule(BaseModule):
    name = "Cleanup"
    icon = "🗑️"
    description = "Scan and remove junk files, caches, logs, and more"
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def create_widget(self) -> QWidget:
        outer = QWidget()
        main_lay = QVBoxLayout(outer)
        main_lay.setContentsMargins(4, 4, 4, 4)
        main_lay.setSpacing(4)

        # ── Module-level toolbar ──
        header = QHBoxLayout()
        self._freed_lbl = QLabel("Freed this session: 0 B")
        self._freed_lbl.setStyleSheet("color: #4caf50; font-weight: bold; padding: 2px 6px;")
        self._freed_bytes = 0
        header.addStretch()
        header.addWidget(self._freed_lbl)
        main_lay.addLayout(header)

        # ── Tabs ──
        self._tabs = QTabWidget()
        main_lay.addWidget(self._tabs, 1)

        # 1. Overview
        self._overview = _OverviewTab()
        self._tabs.addTab(self._overview, "Overview")

        # 2. System Junk
        sys_scanners = {
            cs.scan_temp_files:       ("Temp Files",       "safe"),
            cs.scan_prefetch:         ("Prefetch",          "caution"),
            cs.scan_thumbnail_cache:  ("Thumbnail Cache",   "safe"),
            cs.scan_user_crash_dumps: ("User Crash Dumps",  "caution"),
        }
        self._sys_tab = _ScanTab(sys_scanners)
        self._tabs.addTab(self._sys_tab, "System Junk")

        # 3. Browser Caches
        self._browser = _BrowserCleanupTab()
        self._tabs.addTab(self._browser, "Browser Caches")

        # 4. App & Game Caches
        app_scanners = {
            cs.scan_app_caches:           ("App Caches",             "safe"),
            cs.scan_store_app_caches:     ("Store / UWP Caches",     "safe"),
            cs.scan_d3d_shader_cache:     ("GPU Shader Cache",        "safe"),
            cs.scan_appdata_autodiscover: ("Auto-discovered Caches",  "caution"),
            cs.scan_steam_cache:          ("Steam Cache",             "safe"),
            cs.scan_stremio_cache:        ("Stremio Cache",           "safe"),
            cs.scan_outlook_cache:        ("Outlook Cache",           "safe"),
            cs.scan_winget_packages:      ("WinGet Packages",         "safe"),
        }
        self._app_tab = _ScanTab(app_scanners)
        self._tabs.addTab(self._app_tab, "App & Game Caches")

        # 5. Windows Update
        wu_scanners = {
            cs.scan_wu_cache:              ("WU Download Cache",   "caution"),
            cs.scan_delivery_optimization: ("Delivery Opt. Cache", "safe"),
        }
        self._wu_tab = _ScanTab(wu_scanners, wu_cache=True)
        self._tabs.addTab(self._wu_tab, "Windows Update")

        # 6. Logs & Reports
        log_scanners = {
            cs.scan_windows_logs:    ("Windows Logs",      "caution"),
            cs.scan_event_logs:      ("Event Log Files",   "caution"),
            cs.scan_wer_reports:     ("WER Crash Reports", "caution"),
            cs.scan_memory_dumps:    ("Memory Dumps",      "caution"),
            cs.scan_panther_logs:    ("Panther Logs",       "caution"),
            cs.scan_dmf_logs:        ("DMF Logs",           "caution"),
            cs.scan_onedrive_logs:   ("OneDrive Logs",      "safe"),
            cs.scan_defender_history:("Defender History",   "safe"),
        }
        self._logs_tab = _ScanTab(log_scanners)
        self._tabs.addTab(self._logs_tab, "Logs & Reports")

        # 7. Large Items + DISM
        self._large = _LargeItemsTab()
        self._tabs.addTab(self._large, "Large Items")

        # 8. Dev Tools
        dev_scanners = {
            cs.scan_dev_tool_caches: ("Dev Tool Caches", "safe"),
        }
        self._dev_tab = _ScanTab(dev_scanners)
        self._tabs.addTab(self._dev_tab, "Dev Tools")

        # ── Wire signals ──
        for tab in (
            self._overview, self._sys_tab, self._browser, self._app_tab,
            self._wu_tab, self._logs_tab, self._large, self._dev_tab,
        ):
            tab.freed_bytes.connect(self._on_freed)

        self._tabs.currentChanged.connect(self._on_tab_changed)

        return outer

    # ── Freed-session counter ──

    def _on_freed(self, nbytes: int):
        self._freed_bytes += nbytes
        self._freed_lbl.setText(f"Freed this session: {cs.format_size(self._freed_bytes)}")

    # ── Auto-scan on tab switch ──

    def _on_tab_changed(self, index: int):
        tab = self._tabs.widget(index)
        if hasattr(tab, "auto_scan"):
            tab.auto_scan()

    # ── BaseModule lifecycle ──

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self._cancel_all_tabs()
        self.cancel_all_workers()

    def on_activate(self) -> None:
        """Auto-scan the overview when the module is first opened."""
        self._overview.auto_scan()

    def on_deactivate(self) -> None:
        self._cancel_all_tabs()

    def _cancel_all_tabs(self) -> None:
        for tab in (
            self._overview, self._sys_tab, self._browser, self._app_tab,
            self._wu_tab, self._logs_tab, self._large, self._dev_tab,
        ):
            if hasattr(tab, "_cancel_all"):
                tab._cancel_all()

    def get_status_info(self) -> str:
        return "Cleanup"
