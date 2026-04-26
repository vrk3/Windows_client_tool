# src/modules/process_explorer/lower_pane/handle_view.py
from __future__ import annotations
import ctypes
import ctypes.wintypes
import logging
import threading
from typing import List

from PyQt6.QtCore import pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView, QLabel)

logger = logging.getLogger(__name__)

_HEADERS = ["Type", "Name", "Handle Value", "Object Address", "Access"]

_ntdll = ctypes.windll.ntdll
_kernel32 = ctypes.windll.kernel32

SystemHandleInformation = 16
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class _SYSTEM_HANDLE_ENTRY(ctypes.Structure):
    _fields_ = [
        ("UniqueProcessId", ctypes.wintypes.USHORT),
        ("CreatorBackTraceIndex", ctypes.wintypes.USHORT),
        ("ObjectTypeIndex", ctypes.wintypes.BYTE),
        ("HandleAttributes", ctypes.wintypes.BYTE),
        ("HandleValue", ctypes.wintypes.USHORT),
        ("Object", ctypes.c_void_p),
        ("GrantedAccess", ctypes.wintypes.ULONG),
    ]


class _SYSTEM_HANDLE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ctypes.wintypes.ULONG),
        ("Handles", _SYSTEM_HANDLE_ENTRY * 1),
    ]


def _query_handles(pid: int) -> List[dict]:
    """Query all handles for pid via NtQuerySystemInformation."""
    size = 0x10000
    while True:
        buf = (ctypes.c_byte * size)()
        ret_len = ctypes.wintypes.ULONG()
        status = _ntdll.NtQuerySystemInformation(
            SystemHandleInformation, buf, size, ctypes.byref(ret_len)
        )
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size *= 2
            continue
        if status != 0:
            return []
        break

    info = ctypes.cast(buf, ctypes.POINTER(_SYSTEM_HANDLE_INFORMATION)).contents
    count = info.NumberOfHandles
    entry_size = ctypes.sizeof(_SYSTEM_HANDLE_ENTRY)
    base = ctypes.addressof(info.Handles)

    results = []
    for i in range(count):
        entry = _SYSTEM_HANDLE_ENTRY.from_address(base + i * entry_size)
        if entry.UniqueProcessId != pid:
            continue
        results.append({
            "type_index": entry.ObjectTypeIndex,
            "handle": entry.HandleValue,
            "object": entry.Object,
            "access": entry.GrantedAccess,
        })
    return results


class HandleView(QWidget):
    _handles_ready = pyqtSignal(object)  # emits List[dict] from background thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._handles_ready.connect(self._populate)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("Select a process to view handles")
        layout.addWidget(self._label)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.hide()
        layout.addWidget(self._table)
        self._thread: Optional[threading.Thread] = None

    def cancel(self) -> None:
        self._label.setText("Select a process to view handles")
        self._table.hide()
        self._thread = None

    def load_pid(self, pid: int):
        self.cancel()
        self._label.setText(f"Loading handles for PID {pid}…")
        self._table.hide()
        self._thread = threading.Thread(target=self._load, args=(pid,), daemon=True)
        self._thread.start()

    def _load(self, pid: int):
        try:
            handles = _query_handles(pid)
        except Exception as e:
            logger.warning("Handle query failed for %d: %s", pid, e)
            handles = []
        # Marshal back to main thread via signal (thread-safe)
        self._handles_ready.emit(handles)

    @pyqtSlot(object)
    def _populate(self, handles: List[dict]):
        self._table.setRowCount(len(handles))
        for r, h in enumerate(handles):
            for c, val in enumerate([
                str(h["type_index"]),
                "—",                        # name resolution omitted for safety
                hex(h["handle"]),
                hex(h["object"] or 0),
                hex(h["access"]),
            ]):
                self._table.setItem(r, c, QTableWidgetItem(val))
        self._label.setText(f"{len(handles)} handles")
        self._table.show()
