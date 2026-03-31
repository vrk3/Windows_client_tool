import os
import datetime
from typing import List, Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                              QTableWidget, QTableWidgetItem, QTabWidget,
                              QHeaderView, QLabel, QProgressBar, QFileDialog,
                              QDialog, QTextEdit, QDialogButtonBox)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor, QFont

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.certificate_viewer.cert_reader import CertInfo, fetch_certs

COLUMNS = ["Subject CN", "Issuer", "Expiry", "Thumbprint", "Key Usage", "Has Private Key", "Status"]

STORES = [
    ("Personal",          "MY",   "user"),
    ("Computer",          "MY",   "machine"),
    ("Trusted Root",      "ROOT", "machine"),
    ("Intermediate CAs",  "CA",   "machine"),
]


class _CertTab(QWidget):
    def __init__(self, store_name: str, store_location: str, parent=None):
        super().__init__(parent)
        self._store_name = store_name
        self._store_location = store_location
        self._certs: List[CertInfo] = []
        self._loaded = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar row
        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._export_btn = QPushButton("Export .cer")
        self._view_btn = QPushButton("View Detail")
        self._status = QLabel("Click Refresh to load.")
        self._export_btn.setEnabled(False)
        self._view_btn.setEnabled(False)
        toolbar.addWidget(self._refresh_btn)
        toolbar.addWidget(self._export_btn)
        toolbar.addWidget(self._view_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status)
        layout.addLayout(toolbar)

        # Thin progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Certificate table
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, 1)

        # Connections
        self._refresh_btn.clicked.connect(self._load)
        self._export_btn.clicked.connect(self._export)
        self._view_btn.clicked.connect(self._view_detail)
        self._table.selectionModel().selectionChanged.connect(self._on_selection_changed)

    def _on_selection_changed(self):
        has_sel = bool(self._table.selectedItems())
        self._export_btn.setEnabled(has_sel)
        self._view_btn.setEnabled(has_sel)

    def _load(self):
        self._loaded = True
        self._refresh_btn.setEnabled(False)
        self._status.setText("Loading...")
        self._progress.show()
        self._table.setRowCount(0)
        self._certs.clear()

        sn = self._store_name
        sl = self._store_location

        # Worker passes itself as first arg — use _w to absorb it
        worker = Worker(lambda _w: fetch_certs(sn, sl))
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_result(self, certs: List[CertInfo]):
        self._certs = certs
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        today = datetime.datetime.utcnow()

        self._table.setRowCount(len(certs))
        for r, c in enumerate(certs):
            expiry_str = (c.expiry.strftime("%Y-%m-%d")
                          if c.expiry != datetime.datetime.min else "N/A")
            thumb_display = (c.thumbprint[:20] + "..."
                             if len(c.thumbprint) > 20 else c.thumbprint)
            vals = [
                c.subject_cn,
                c.issuer,
                expiry_str,
                thumb_display,
                c.key_usage,
                "Yes" if c.has_private_key else "No",
                c.flag,
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                self._table.setItem(r, col, item)

            # Color-code expired / expiring rows
            if "🔴" in c.flag:
                for col in range(len(COLUMNS)):
                    cell = self._table.item(r, col)
                    if cell:
                        cell.setForeground(QColor("#CC2222"))
            elif "🟠" in c.flag:
                for col in range(len(COLUMNS)):
                    cell = self._table.item(r, col)
                    if cell:
                        cell.setForeground(QColor("#CC7700"))

        expired = sum(1 for c in certs if c.days_until_expiry < 0)
        expiring = sum(1 for c in certs if 0 <= c.days_until_expiry <= 30)
        self._status.setText(
            f"{len(certs)} certs — {expired} expired, {expiring} expiring soon")

    def _on_error(self, err_str: str):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText(f"Error: {err_str}")

    def _selected_cert(self) -> Optional[CertInfo]:
        rows = {i.row() for i in self._table.selectedIndexes()}
        if rows:
            r = min(rows)
            if r < len(self._certs):
                return self._certs[r]
        return None

    def _export(self):
        cert = self._selected_cert()
        if not cert:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Certificate",
            f"{cert.subject_cn}.cer",
            "DER Certificate (*.cer)")
        if path:
            with open(path, "wb") as f:
                f.write(cert.raw_der)
            self._status.setText(f"Exported to {os.path.basename(path)}")

    def _view_detail(self):
        cert = self._selected_cert()
        if not cert:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Certificate Details")
        dlg.resize(600, 400)
        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))
        expiry_str = (cert.expiry.strftime("%Y-%m-%d %H:%M UTC")
                      if cert.expiry != datetime.datetime.min else "N/A")
        text.setPlainText(
            f"Subject:         {cert.subject_full}\n"
            f"Subject CN:      {cert.subject_cn}\n"
            f"Issuer:          {cert.issuer}\n"
            f"Expiry:          {expiry_str}\n"
            f"Days Remaining:  {cert.days_until_expiry}\n"
            f"Thumbprint:      {cert.thumbprint}\n"
            f"Key Usage:       {cert.key_usage}\n"
            f"Has Private Key: {cert.has_private_key}\n"
            f"Status:          {cert.flag or 'Valid'}\n"
        )
        layout.addWidget(text)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()


class CertModule(BaseModule):
    name = "Certificates"
    icon = "🔐"
    description = "View installed certificates"
    requires_admin = False
    group = ModuleGroup.MANAGE

    def create_widget(self) -> QWidget:
        self._tabs = QTabWidget()
        for label, store_name, store_location in STORES:
            self._tabs.addTab(_CertTab(store_name, store_location), label)
        return self._tabs

    def on_activate(self) -> None:
        if not hasattr(self, "_tabs"):
            return
        tab = self._tabs.currentWidget()
        if isinstance(tab, _CertTab) and not tab._loaded:
            tab._load()

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
