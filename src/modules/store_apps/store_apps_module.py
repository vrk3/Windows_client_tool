"""AppX/Microsoft Store App Manager — list and uninstall Store apps."""
import json
import subprocess
from typing import List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLineEdit, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
import logging

logger = logging.getLogger(__name__)

# Known system packages that should NOT be removable
SYSTEM_PACKAGES = {
    "Microsoft.Windows", "Microsoft.WindowsStore", "Microsoft.WindowsAppRuntime",
    "Microsoft.UI", "Microsoft.VCLibs", "Microsoft.NET", "Microsoft.DesktopAppInstaller"
}


class StoreAppsModule(BaseModule):
    name = "Store Apps"
    icon = "📦"
    description = "Manage Microsoft Store (AppX) applications"
    group = ModuleGroup.MANAGE
    requires_admin = True

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._apps: List[dict] = []

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._load_apps)
        toolbar.addWidget(refresh_btn)
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        toolbar.addWidget(self._progress)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search apps…")
        self._search.textChanged.connect(self._filter_apps)
        toolbar.addWidget(self._search)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Name", "Publisher", "Version", "Size", "User-Removable"])
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 200)
        self._table.setColumnWidth(2, 100)
        self._table.setColumnWidth(3, 80)
        self._table.setColumnWidth(4, 100)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0; border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 3px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0; padding: 4px; border: none; }
        """)
        layout.addWidget(self._table)

        # Bottom toolbar
        bottom = QHBoxLayout()
        uninstall_btn = QPushButton("🗑️ Uninstall Selected")
        uninstall_btn.setStyleSheet("color: #f48771; font-weight: bold;")
        uninstall_btn.clicked.connect(self._uninstall)
        bottom.addWidget(uninstall_btn)
        bottom.addStretch()
        layout.addLayout(bottom)

        return self._widget

    def on_start(self, app) -> None:
        self.app = app
        # Don't auto-load here — _progress is created in create_widget() which runs after on_start

    def get_status_info(self) -> str:
        return f"Store Apps — {len(self._apps)} installed"

    # ── implementation ──────────────────────────────────────────────────────

    def _load_apps(self):
        self._progress.setVisible(True)
        self._table.setRowCount(0)

        def do_load(worker):
            del worker
            result = subprocess.run([
                "powershell", "-Command",
                "Get-AppxPackage -AllUsers | Select-Object Name, Publisher, Version, IsFramework, IsResourcePackage, IsPartiallyStaged | ConvertTo-Json -Compress"
            ], capture_output=True, text=True, timeout=60)
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    data = [data]
                return [
                    a for a in data
                    if not a.get("IsFramework")
                    and not a.get("IsResourcePackage")
                    and not a.get("IsPartiallyStaged")
                ]
            except json.JSONDecodeError:
                logger.warning("Failed to parse AppxPackage output")
                return []

        self._worker = Worker(do_load)
        self._worker.signals.result.connect(self._on_apps_loaded)
        self._worker.signals.error.connect(lambda _: self._progress.setVisible(False))
        self.app.thread_pool.start(self._worker)

    def _on_apps_loaded(self, apps: List[dict]):
        self._progress.setVisible(False)
        self._apps = apps

        for i, app in enumerate(sorted(apps, key=lambda a: a.get("Name", "").lower())):
            name = app.get("Name", "")
            publisher = app.get("Publisher", "")
            version = app.get("Version", "")

            is_system = any(name.startswith(p) for p in SYSTEM_PACKAGES)

            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(publisher))
            self._table.setItem(row, 2, QTableWidgetItem(version[:20] if version else ""))
            self._table.setItem(row, 3, QTableWidgetItem("—"))
            removable = "✅ Yes" if not is_system else "❌ System"
            self._table.setItem(row, 4, QTableWidgetItem(removable))
            self._table.item(row, 4).setToolTip(
                "System packages cannot be uninstalled without breaking Windows"
            )

    def _filter_apps(self, text: str):
        for row in range(self._table.rowCount()):
            name = self._table.item(row, 0).text().lower() if self._table.item(row, 0) else ""
            self._table.setRowHidden(row, text.lower() not in name)

    def _uninstall(self):
        row = self._table.currentRow()
        if row < 0:
            QMessageBox.warning(self._widget, "No Selection", "Select an app to uninstall.")
            return

        name = self._table.item(row, 0).text()
        removable = self._table.item(row, 4).text()

        if "System" in removable:
            QMessageBox.warning(self._widget, "System App", "System apps cannot be uninstalled.")
            return

        reply = QMessageBox.warning(
            self._widget, "Uninstall App",
            f"Uninstall '{name}'?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def do_uninstall(worker):
            del worker
            result = subprocess.run([
                "powershell", "-Command",
                f"Get-AppxPackage '{name}' | Remove-AppxPackage -AllUsers"
            ], capture_output=True, text=True, timeout=120)
            return result.returncode == 0, result.stdout + result.stderr

        self._progress.setVisible(True)
        self._worker = Worker(do_uninstall)
        self._worker.signals.result.connect(lambda res: self._on_uninstall_done(res, name))
        self._worker.signals.error.connect(lambda _: self._progress.setVisible(False))
        self.app.thread_pool.start(self._worker)

    def _on_uninstall_done(self, result, name):
        self._progress.setVisible(False)
        success, output = result
        if success:
            QMessageBox.information(self._widget, "Uninstalled", f"'{name}' has been uninstalled.")
            self._load_apps()
        else:
            QMessageBox.critical(self._widget, "Failed", f"Could not uninstall '{name}'.\n{output}")
