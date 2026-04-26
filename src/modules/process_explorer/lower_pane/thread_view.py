# src/modules/process_explorer/lower_pane/thread_view.py
from __future__ import annotations
import logging
import threading
from typing import Optional

import psutil
from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

logger = logging.getLogger(__name__)

_HEADERS = ["TID", "CPU%", "User Time", "System Time"]


class ThreadView(QWidget):
    _data_ready = pyqtSignal(int, object)  # (pid, threads)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data_ready.connect(self._populate)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)
        self._pid: Optional[int] = None
        self._thread: Optional[threading.Thread] = None

    def cancel(self) -> None:
        self._pid = None

    def load_pid(self, pid: int):
        self.cancel()
        self._pid = pid
        self._table.setRowCount(0)
        self._thread = threading.Thread(target=self._load, args=(pid,), daemon=True)
        self._thread.start()

    def _refresh(self):
        if self._pid is not None:
            self.load_pid(self._pid)

    def _load(self, pid: int):
        try:
            threads = psutil.Process(pid).threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            threads = []
        self._data_ready.emit(pid, threads)

    @pyqtSlot(int, object)
    def _populate(self, pid: int, threads: list):
        if pid != self._pid:
            return  # stale result
        self._table.setRowCount(len(threads))
        for r, t in enumerate(threads):
            for c, val in enumerate([
                str(t.id),
                "—",  # TODO: Win32 OpenThread for per-thread CPU%
                f"{t.user_time:.3f}s",
                f"{t.system_time:.3f}s",
            ]):
                self._table.setItem(r, c, QTableWidgetItem(val))
