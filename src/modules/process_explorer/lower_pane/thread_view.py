# src/modules/process_explorer/lower_pane/thread_view.py
from __future__ import annotations
import logging
from typing import Optional

import psutil
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

logger = logging.getLogger(__name__)

_HEADERS = ["TID", "CPU%", "User Time", "System Time"]


class ThreadView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def load_pid(self, pid: int):
        self._table.setRowCount(0)
        try:
            threads = psutil.Process(pid).threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        self._table.setRowCount(len(threads))
        for r, t in enumerate(threads):
            for c, val in enumerate([
                str(t.id),
                "—",                          # cpu% per-thread not available via psutil
                f"{t.user_time:.3f}s",
                f"{t.system_time:.3f}s",
            ]):
                self._table.setItem(r, c, QTableWidgetItem(val))
