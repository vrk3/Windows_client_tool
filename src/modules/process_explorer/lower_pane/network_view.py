# src/modules/process_explorer/lower_pane/network_view.py
from __future__ import annotations
import logging
import socket
from typing import Optional

import psutil
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

logger = logging.getLogger(__name__)

_HEADERS = ["Protocol", "Local Address", "Local Port", "Remote Address", "Remote Port", "State"]


class NetworkView(QWidget):
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
        self._pid: Optional[int] = None

    def load_pid(self, pid: int):
        self._pid = pid
        self._refresh()

    def _refresh(self):
        self._table.setRowCount(0)
        if self._pid is None:
            return
        try:
            conns = psutil.net_connections()
        except psutil.AccessDenied:
            return
        rows = [c for c in conns if c.pid == self._pid]
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
