# src/modules/process_explorer/lower_pane/network_view.py
from __future__ import annotations
import logging
import socket
import threading
from typing import List, Optional

import psutil
from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

logger = logging.getLogger(__name__)

_HEADERS = ["Protocol", "Local Address", "Local Port", "Remote Address", "Remote Port", "State"]


class NetworkView(QWidget):
    _data_ready = pyqtSignal(int, object)  # (pid, rows)

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

    def load_pid(self, pid: int):
        self._pid = pid
        self._table.setRowCount(0)
        threading.Thread(target=self._load, args=(pid,), daemon=True).start()

    def _load(self, pid: int):
        try:
            conns = psutil.net_connections()
            rows = [c for c in conns if c.pid == pid]
        except psutil.AccessDenied:
            rows = []
        except Exception as e:
            logger.warning("net_connections failed: %s", e)
            rows = []
        self._data_ready.emit(pid, rows)

    @pyqtSlot(int, object)
    def _populate(self, pid: int, rows: list):
        if pid != self._pid:
            return  # stale result from a previous selection
        self._table.setRowCount(len(rows))
        for r, conn in enumerate(rows):
            proto = "TCP" if conn.type == socket.SOCK_STREAM else "UDP"
            laddr = conn.laddr.ip if conn.laddr else ""
            lport = str(conn.laddr.port) if conn.laddr else ""
            raddr = conn.raddr.ip if conn.raddr else ""
            rport = str(conn.raddr.port) if conn.raddr else ""
            state = conn.status or ""
            for c, val in enumerate([proto, laddr, lport, raddr, rport, state]):
                self._table.setItem(r, c, QTableWidgetItem(val))
