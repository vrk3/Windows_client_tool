# src/modules/process_explorer/lower_pane/dll_view.py
from __future__ import annotations
import ctypes
import ctypes.wintypes
import logging
import os
from typing import List, Optional, Tuple

import psutil
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView, QLabel)
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

_HEADERS = ["Name", "Full Path", "Base Address", "Size", "Company", "Version"]

_psapi = ctypes.windll.psapi
_kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def _get_dll_list(pid: int) -> List[Tuple[str, str, int, int]]:
    """Returns list of (name, path, base_addr, size) for each module in pid."""
    results = []
    handle = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return results
    try:
        module_array = (ctypes.wintypes.HMODULE * 1024)()
        needed = ctypes.wintypes.DWORD()
        if not _psapi.EnumProcessModulesEx(
            handle, module_array, ctypes.sizeof(module_array),
            ctypes.byref(needed), 0x03  # LIST_MODULES_ALL
        ):
            return results
        count = needed.value // ctypes.sizeof(ctypes.wintypes.HMODULE)
        path_buf = ctypes.create_unicode_buffer(1024)
        for i in range(count):
            mod = module_array[i]
            _psapi.GetModuleFileNameExW(handle, mod, path_buf, 1024)
            path = path_buf.value
            name = os.path.basename(path)
            results.append((name, path, mod, 0))
    finally:
        _kernel32.CloseHandle(handle)
    return results


class DllView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def load_pid(self, pid: int):
        self._table.setRowCount(0)
        try:
            dlls = _get_dll_list(pid)
        except Exception as e:
            logger.warning("DLL enum failed for pid %d: %s", pid, e)
            return
        self._table.setRowCount(len(dlls))
        for r, (name, path, base, size) in enumerate(dlls):
            for c, val in enumerate([name, path, hex(base), str(size), "", ""]):
                self._table.setItem(r, c, QTableWidgetItem(val))
