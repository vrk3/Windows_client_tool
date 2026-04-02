"""Restore Manager UI — create and manage system restore points."""
import subprocess
import re
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QInputDialog,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
import logging

logger = logging.getLogger(__name__)


class RestoreManagerModule(BaseModule):
    name = "Restore Manager"
    icon = "♻️"
    description = "Create and manage Windows System Restore points"
    group = ModuleGroup.OPTIMIZE
    requires_admin = True

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._restore_points: List[dict] = []
        self._worker: Optional[Worker] = None

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        create_btn = QPushButton("➕ Create Restore Point")
        create_btn.setStyleSheet(
            "font-weight: bold; background: #094771; color: white; "
            "border-radius: 4px; padding: 6px 16px;"
        )
        create_btn.clicked.connect(self._create_restore_point)
        toolbar.addWidget(create_btn)

        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self._load_restore_points)
        toolbar.addWidget(refresh_btn)

        open_sysprops_btn = QPushButton("🔧 System Properties")
        open_sysprops_btn.clicked.connect(self._open_system_properties)
        toolbar.addWidget(open_sysprops_btn)

        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        toolbar.addWidget(self._progress)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Status info
        self._status_label = QLabel("System Restore is enabled")
        self._status_label.setStyleSheet("color: #888; font-size: 12px; padding: 4px;")
        layout.addWidget(self._status_label)

        # Restore points table
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["Name", "Date", "Type", "Size"])
        self._table.setColumnWidth(0, 350)
        self._table.setColumnWidth(1, 160)
        self._table.setColumnWidth(2, 120)
        self._table.setColumnWidth(3, 80)
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0; border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0; padding: 4px; border: none; }
        """)
        layout.addWidget(self._table)

        # Info
        info = QLabel(
            "💡 System Restore monitors system files and registry for changes. "
            "Restore points let you revert Windows to a working state if problems occur."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            "color: #888; font-size: 11px; background: #252526; "
            "border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(info)

        self._load_restore_points()
        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        self._load_restore_points()

    def get_status_info(self) -> str:
        return f"Restore Manager — {len(self._restore_points)} points"

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def on_stop(self) -> None:
        self.cancel_all_workers()

    # ── implementation ──────────────────────────────────────────────────────

    def _load_restore_points(self):
        self._progress.setVisible(True)

        def do_load(worker):
            try:
                result = subprocess.run(
                    [
                        "powershell", "-Command",
                        "Get-ComputerRestorePoint | "
                        "Select-Object Description, RestorePointType, CreationTime | "
                        "ConvertTo-Json -Compress",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                import json

                data = json.loads(result.stdout) if result.stdout.strip() else []
                if isinstance(data, dict):
                    data = [data]
                return data
            except Exception as e:
                logger.warning("Failed to load restore points: %s", e)
                return []

        self._worker = Worker(do_load)
        self._worker.signals.result.connect(self._on_points_loaded)
        self._worker.signals.error.connect(lambda _: self._progress.setVisible(False))
        self._workers.append(self._worker)
        self.app.thread_pool.start(self._worker)

    def _on_points_loaded(self, points):
        self._progress.setVisible(False)
        self._restore_points = points
        self._table.setRowCount(0)

        for pt in points:
            row = self._table.rowCount()
            self._table.insertRow(row)
            name = pt.get("Description", "Unnamed restore point")
            ctime = pt.get("CreationTime", "")
            try:
                dt = datetime.strptime(ctime[:14], "%Y%m%d%H%M%S")
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = ctime[:14] if ctime else "Unknown"

            rptype = pt.get("RestorePointType", "Unknown")
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem(date_str))
            self._table.setItem(row, 2, QTableWidgetItem(rptype))
            self._table.setItem(row, 3, QTableWidgetItem("~"))

    def _create_restore_point(self):
        reply = QMessageBox.question(
            self._widget,
            "Create Restore Point",
            "This will create a new System Restore point.\n\n"
            "Enter a description for this restore point:",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        desc, ok = QInputDialog.getText(
            self._widget,
            "Restore Point Description",
            "Description:",
            QInputDialog.InputMode.TextInput,
        )
        if not ok or not desc.strip():
            desc = "Windows Client Tool Restore Point"

        self._progress.setVisible(True)
        self._status_label.setText("Creating restore point…")

        def do_create(worker):
            try:
                result = subprocess.run(
                    [
                        "powershell", "-Command",
                        f"Checkpoint-Computer -Description '{desc}' -RestorePointType 'MODIFY_SETTINGS'",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                return result.returncode == 0, result.stdout + result.stderr
            except Exception as e:
                return False, str(e)

        self._worker = Worker(do_create)
        self._worker.signals.result.connect(self._on_created)
        self._worker.signals.error.connect(lambda _: self._progress.setVisible(False))
        self._workers.append(self._worker)
        self.app.thread_pool.start(self._worker)

    def _on_created(self, result):
        self._progress.setVisible(False)
        success, output = result
        if success:
            QMessageBox.information(
                self._widget,
                "Restore Point Created",
                "System Restore point was created successfully.",
            )
            self._load_restore_points()
        else:
            QMessageBox.warning(
                self._widget,
                "Failed",
                f"Could not create restore point.\n{output}\n\n"
                "Note: Some Windows editions restrict restore point creation via scripts.",
            )
            self._status_label.setText("Restore point creation may be restricted by policy")

    def _open_system_properties(self):
        try:
            subprocess.Popen(["control.exe", "sysdm.cpl,,0"])
        except Exception as e:
            QMessageBox.warning(
                self._widget, "Error", f"Could not open System Properties: {e}"
            )
