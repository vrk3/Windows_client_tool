"""_LargeItemsTab — Large Items scan tab + DISM Component Store Cleanup button."""
import subprocess
from typing import Optional

from PyQt6.QtCore import QThreadPool, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFrame, QTextEdit,
)

from core.worker import Worker
from modules.cleanup.tabs._scan_tab import _ScanTab
from modules.cleanup import cleanup_scanner as cs


# Large-item scanners shared across overview and this tab
LARGE_SCANNERS = {
    cs.scan_windows_old:            ("Windows.old",            "caution"),
    cs.scan_recycle_bin:            ("Recycle Bin",            "safe"),
    cs.scan_installer_patch_cache:  ("Installer Patch Cache",  "danger"),
}


class _LargeItemsTab(QWidget):
    """Large Items scan tab + DISM Component Store Cleanup button."""
    freed_bytes = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Main scan tab
        self._scan_tab = _ScanTab(LARGE_SCANNERS)
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
