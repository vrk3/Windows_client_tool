"""_ScanTab — generic scan/clean tab supporting multiple scanners."""
import os
from typing import Optional

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget,
    QTreeWidgetItem, QLabel, QSpinBox, QProgressBar, QMenu,
    QHeaderView,
)

from core.worker import Worker
from modules.cleanup import cleanup_scanner as cs


# ── Safety colour helpers (shared with other tabs) ────────────────────────────

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
    from PyQt6.QtWidgets import QMessageBox
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
                except Exception as e:
                    logger.warning(f"Scan function {fn.__name__} failed: {e}")
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

    def _get_selected_items(self) -> list:
        items = []
        for i in range(self._tree.topLevelItemCount()):
            tw = self._tree.topLevelItem(i)
            for j in range(tw.childCount()):
                child = tw.child(j)
                si = child.data(0, Qt.ItemDataRole.UserRole)
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

    def _on_clean_done(self, result: tuple):
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
                si = child.data(0, Qt.ItemDataRole.UserRole)
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
        si = item.data(0, Qt.ItemDataRole.UserRole)
        if not si:
            return
        menu = QMenu(self)
        open_act = menu.addAction("Open in Explorer")
        if menu.exec(self._tree.viewport().mapToGlobal(pos)) == open_act:
            target = si.path if si.is_dir else os.path.dirname(si.path)
            os.startfile(target)
