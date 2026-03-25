# src/modules/process_explorer/lower_pane/memory_map_view.py
from __future__ import annotations
import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView)
from PyQt6.QtGui import QColor
import psutil

logger = logging.getLogger(__name__)

_HEADERS = ["Path", "RSS", "Size", "Permissions", "Private"]


class MemoryMapView(QWidget):
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

    def _fmt(self, n: int) -> str:
        if n < 1024**2:
            return f"{n//1024}K"
        return f"{n//1024**2}M"

    def load_pid(self, pid: int):
        self._table.setRowCount(0)
        try:
            maps = psutil.Process(pid).memory_maps(grouped=False)
        except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError):
            return
        self._table.setRowCount(len(maps))
        for r, m in enumerate(maps):
            perms = getattr(m, "perms", "")
            private = self._fmt(getattr(m, "private", 0))
            for c, val in enumerate([m.path, self._fmt(m.rss), "—", perms, private]):
                item = QTableWidgetItem(val)
                # Highlight W^X (writable+executable) in yellow
                if perms and "w" in perms and "x" in perms:
                    item.setBackground(QColor(255, 255, 153))
                self._table.setItem(r, c, item)
