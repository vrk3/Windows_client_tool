# src/modules/process_explorer/properties_dialog.py
from __future__ import annotations
import logging
import subprocess
from typing import Optional

import psutil
from PyQt6.QtWidgets import (QDialog, QTabWidget, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QTextEdit, QTableWidget,
                              QTableWidgetItem, QHeaderView, QPushButton,
                              QDialogButtonBox, QLineEdit)
from PyQt6.QtCore import Qt

from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.lower_pane.thread_view import ThreadView
from modules.process_explorer.lower_pane.network_view import NetworkView
from modules.process_explorer.lower_pane.strings_view import StringsView

logger = logging.getLogger(__name__)


class ProcessPropertiesDialog(QDialog):
    def __init__(self, node: ProcessNode, thread_pool=None, parent=None):
        super().__init__(parent)
        self._node = node
        self._thread_pool = thread_pool
        self.setWindowTitle(f"Properties — {node.name} (PID {node.pid})")
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._build_image_tab()
        self._build_threads_tab()
        self._build_network_tab()
        self._build_security_tab()
        self._build_environment_tab()
        self._build_strings_tab()

    def _row(self, label: str, value: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(f"<b>{label}:</b>")
        lbl.setFixedWidth(140)
        val = QLabel(value)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        val.setWordWrap(True)
        h.addWidget(lbl)
        h.addWidget(val, 1)
        return w

    def _build_image_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        n = self._node
        layout.addWidget(self._row("Image", n.exe))
        layout.addWidget(self._row("Command Line", n.cmdline or "—"))
        layout.addWidget(self._row("Working Dir", "—"))
        layout.addWidget(self._row("PID", str(n.pid)))
        layout.addWidget(self._row("Parent PID", str(n.parent_pid)))
        layout.addWidget(self._row("User", n.user))
        layout.addWidget(self._row("Status", n.status))
        layout.addWidget(self._row("Integrity", n.integrity_level))

        open_btn = QPushButton("Open File Location")
        open_btn.clicked.connect(lambda: subprocess.Popen(
            ["explorer", "/select,", n.exe]) if n.exe else None)
        layout.addWidget(open_btn)
        layout.addStretch()
        self._tabs.addTab(w, "Image")

    def _build_threads_tab(self):
        tv = ThreadView()
        tv.load_pid(self._node.pid)
        self._tabs.addTab(tv, "Threads")

    def _build_network_tab(self):
        nv = NetworkView()
        nv.load_pid(self._node.pid)
        self._tabs.addTab(nv, "TCP/IP")

    def _build_security_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        te = QTextEdit()
        te.setReadOnly(True)
        try:
            import win32security, win32api, win32con
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, self._node.pid)
            token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
            user_sid, attr = win32security.GetTokenInformation(token, win32security.TokenUser)
            name, domain, _ = win32security.LookupAccountSid(None, user_sid)
            te.setPlainText(f"User: {domain}\\{name}\nSID: {win32security.ConvertSidToStringSid(user_sid)}")
        except Exception as e:
            te.setPlainText(f"Security info unavailable: {e}\n(Requires elevated privileges)")
        layout.addWidget(te)
        self._tabs.addTab(w, "Security")

    def _build_environment_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        search = QLineEdit()
        search.setPlaceholderText("Filter…")
        layout.addWidget(search)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Variable", "Value"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(table)

        env_items = []
        try:
            env = psutil.Process(self._node.pid).environ()
            env_items = sorted(env.items())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        table.setRowCount(len(env_items))
        for r, (k, v) in enumerate(env_items):
            table.setItem(r, 0, QTableWidgetItem(k))
            table.setItem(r, 1, QTableWidgetItem(v))

        def _filter(text):
            f = text.lower()
            for row in range(table.rowCount()):
                k_item = table.item(row, 0)
                v_item = table.item(row, 1)
                visible = (not f or f in (k_item.text() if k_item else "").lower()
                           or f in (v_item.text() if v_item else "").lower())
                table.setRowHidden(row, not visible)

        search.textChanged.connect(_filter)
        self._tabs.addTab(w, "Environment")

    def _build_strings_tab(self):
        sv = StringsView()
        if self._thread_pool:
            sv.set_thread_pool(self._thread_pool)
        sv.load_exe(self._node.exe)
        self._tabs.addTab(sv, "Strings")
