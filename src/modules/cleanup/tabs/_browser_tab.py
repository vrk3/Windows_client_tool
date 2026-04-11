"""_BrowserCleanupTab — 3-level tree: Browser → Profile → Cache Category."""
from typing import Optional

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTreeWidget,
    QTreeWidgetItem, QLabel, QProgressBar,
    QHeaderView,
)

from core.worker import Worker
from modules.cleanup.tabs._scan_tab import _confirm_large
from modules.cleanup import cleanup_scanner as cs
from modules.cleanup import browser_scanner as bs


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
