r"""Hosts File Editor — manage C:\Windows\System32\drivers\etc\hosts entries."""
import os
import re
import shutil
import time
from typing import List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
import logging

logger = logging.getLogger(__name__)

HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"

# Pre-built telemetry blocklist
TELEMETRY_BLOCKLIST = [
    ("0.0.0.0", "vortex.data.microsoft.com", "Microsoft telemetry"),
    ("0.0.0.0", "settings-win.data.microsoft.com", "Microsoft settings sync"),
    ("0.0.0.0", "watson.telemetry.microsoft.com", "Microsoft Watson"),
    ("0.0.0.0", "telemetry.microsoft.com", "Microsoft telemetry"),
    ("0.0.0.0", "cdn-settings-win.data.microsoft.com", "Microsoft CDN"),
    ("0.0.0.0", "purchase-prod.adobe.com", "Adobe telemetry"),
    ("0.0.0.0", "ims-na1.adobelogin.com", "Adobe login"),
    ("0.0.0.0", "analytics.datoclick.com", "General analytics"),
    ("0.0.0.0", "stats.g.doubleclick.net", "Google Analytics"),
    ("0.0.0.0", "www.google-analytics.com", "Google Analytics"),
    ("0.0.0.0", "collector.google.com", "Google telemetry"),
    ("0.0.0.0", "display.ads.linkedin.com", "LinkedIn ads"),
    ("0.0.0.0", "pixel.facebook.com", "Facebook pixel"),
]


class HostsEditorModule(BaseModule):
    name = "Hosts Editor"
    icon = "🌐"
    description = "Edit the Windows hosts file to block telemetry and manage DNS"
    group = ModuleGroup.TOOLS
    requires_admin = True

    def __init__(self):
        super().__init__()
        self._widget: QWidget = None
        self._entries: List[Tuple[bool, str, str, str]] = []
        self._modified = False

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        save_btn = QPushButton("💾 Save")
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        backup_btn = QPushButton("📦 Backup")
        backup_btn.clicked.connect(self._backup)
        toolbar.addWidget(backup_btn)

        add_btn = QPushButton("➕ Add Entry")
        add_btn.clicked.connect(self._add_entry)
        toolbar.addWidget(add_btn)

        import_btn = QPushButton("📥 Import Blocklist")
        import_btn.setToolTip("Import telemetry blocklist")
        import_btn.clicked.connect(self._import_blocklist)
        toolbar.addWidget(import_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Enabled", "IP Address", "Hostname", "Comment"])
        self._table.setColumnWidth(0, 60)
        self._table.setColumnWidth(1, 160)
        self._table.setColumnWidth(2, 250)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0; border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 3px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0; padding: 4px; border: none; }
        """)
        layout.addWidget(self._table)

        self._load()
        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def get_status_info(self) -> str:
        enabled = sum(1 for e in self._entries if e[0])
        return f"Hosts Editor — {enabled}/{len(self._entries)} entries active"

    # ── implementation ──────────────────────────────────────────────────────

    def _load(self):
        self._entries = []
        self._table.setRowCount(0)
        if not os.path.exists(HOSTS_PATH):
            self._table.setRowCount(1)
            self._table.setItem(0, 1, QTableWidgetItem("Hosts file not found — run as admin"))
            return
        try:
            with open(HOSTS_PATH, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except PermissionError:
            self._table.setRowCount(1)
            self._table.setItem(0, 1, QTableWidgetItem("Permission denied — run as Administrator"))
            return

        for line in lines:
            line = line.rstrip()
            if not line.strip() or line.strip().startswith("#"):
                if line.strip().startswith("#") and " " in line.strip()[1:]:
                    parts = line.strip()[1:].split(None, 2)
                    if len(parts) >= 2:
                        self._entries.append((False, parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
                continue
            parts = line.split(None, 2)
            if len(parts) >= 2:
                self._entries.append((True, parts[0], parts[1], parts[2] if len(parts) > 2 else ""))

        for i, (enabled, ip, hostname, comment) in enumerate(self._entries):
            self._table.insertRow(i)
            cb = QCheckBox()
            cb.setChecked(enabled)
            cb.stateChanged.connect(lambda _, r=i: self._mark_modified(r))
            self._table.setCellWidget(i, 0, cb)
            self._table.setItem(i, 1, QTableWidgetItem(ip))
            self._table.setItem(i, 2, QTableWidgetItem(hostname))
            self._table.setItem(i, 3, QTableWidgetItem(comment))

    def _mark_modified(self, row):
        del row
        self._modified = True

    def _get_table_entries(self) -> List[Tuple[bool, str, str, str]]:
        entries = []
        for i in range(self._table.rowCount()):
            cb = self._table.cellWidget(i, 0)
            enabled = cb.isChecked() if cb else True
            ip = self._table.item(i, 1).text().strip() if self._table.item(i, 1) else ""
            hostname = self._table.item(i, 2).text().strip() if self._table.item(i, 2) else ""
            comment = self._table.item(i, 3).text().strip() if self._table.item(i, 3) else ""
            if hostname:
                entries.append((enabled, ip, hostname, comment))
        return entries

    def _save(self):
        entries = self._get_table_entries()
        # Validate IP format
        ip_pat = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$|^\[[\da-fA-F:]+\]$|^::1$|^fe80:.+$|^::')
        for enabled, ip, hostname, comment in entries:
            if not ip_pat.match(ip):
                QMessageBox.warning(self._widget, "Invalid IP", f"Invalid IP address: {ip}")
                return

        try:
            bak_path = HOSTS_PATH + ".bak"
            shutil.copy2(HOSTS_PATH, bak_path)
            with open(HOSTS_PATH, "w", encoding="utf-8") as f:
                f.write("# Hosts file managed by Windows Client Tool\n\n")
                for enabled, ip, hostname, comment in entries:
                    prefix = "" if enabled else "# "
                    cmt = f"  # {comment}" if comment else ""
                    f.write(f"{prefix}{ip}\t{hostname}{cmt}\n")
            QMessageBox.information(self._widget, "Saved", f"Hosts file saved.\nBackup: {bak_path}")
        except PermissionError:
            QMessageBox.critical(self._widget, "Permission Denied", "Run as Administrator to save hosts file.")
        except Exception as e:
            QMessageBox.critical(self._widget, "Error", str(e))

    def _backup(self):
        try:
            bak = HOSTS_PATH + f".backup_{int(time.time())}.txt"
            shutil.copy2(HOSTS_PATH, bak)
            QMessageBox.information(self._widget, "Backup Created", f"Backed up to:\n{bak}")
        except Exception as e:
            QMessageBox.warning(self._widget, "Backup Failed", str(e))

    def _add_entry(self):
        row = self._table.rowCount()
        self._table.insertRow(row)
        cb = QCheckBox()
        cb.setChecked(True)
        cb.stateChanged.connect(lambda _: self._mark_modified(row))
        self._table.setCellWidget(row, 0, cb)
        self._table.setItem(row, 1, QTableWidgetItem("0.0.0.0"))
        self._table.setItem(row, 2, QTableWidgetItem("example.com"))
        self._table.setItem(row, 3, QTableWidgetItem(""))
        self._modified = True

    def _import_blocklist(self):
        reply = QMessageBox.question(
            self._widget, "Import Blocklist",
            "This will add the telemetry blocklist entries. Some may already exist.\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for enabled, ip, hostname, comment in TELEMETRY_BLOCKLIST:
            existing = any(h == hostname for _, _, h, _ in self._get_table_entries())
            if existing:
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            cb = QCheckBox()
            cb.setChecked(bool(enabled))
            cb.stateChanged.connect(lambda _, r=row: self._mark_modified(r))
            self._table.setCellWidget(row, 0, cb)
            self._table.setItem(row, 1, QTableWidgetItem(ip))
            self._table.setItem(row, 2, QTableWidgetItem(hostname))
            self._table.setItem(row, 3, QTableWidgetItem(comment))
        self._modified = True
        QMessageBox.information(self._widget, "Import Complete", f"Added {len(TELEMETRY_BLOCKLIST)} entries.")
