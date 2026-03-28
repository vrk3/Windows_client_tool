import csv
import os
import subprocess
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit, QLabel,
    QProgressBar, QFileDialog,
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.driver_manager.driver_reader import DriverInfo, fetch_drivers

COLUMNS = ["Device Name", "Class", "Version", "Date", "Publisher", "Signed", "Status"]


class DriverModule(BaseModule):
    name = "driver_manager"
    icon = "📜"
    description = "View and manage installed drivers"
    requires_admin = False
    group = ModuleGroup.SYSTEM

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._table: Optional[QTableWidget] = None
        self._progress: Optional[QProgressBar] = None
        self._status_lbl: Optional[QLabel] = None
        self._filter_edit: Optional[QLineEdit] = None
        self._refresh_btn: Optional[QPushButton] = None
        self._drivers_ref: list = [[]]  # [list of DriverInfo]

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        export_btn = QPushButton("Export CSV")
        devmgr_btn = QPushButton("Open Device Manager")
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name or class...")
        self._status_lbl = QLabel("Click Refresh to load drivers.")
        toolbar.addWidget(self._refresh_btn)
        toolbar.addWidget(export_btn)
        toolbar.addWidget(devmgr_btn)
        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self._filter_edit, 1)
        toolbar.addWidget(self._status_lbl)
        layout.addLayout(toolbar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(COLUMNS)):
            self._table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, 1)

        self._refresh_btn.clicked.connect(self._do_refresh)
        export_btn.clicked.connect(self._do_export)
        devmgr_btn.clicked.connect(self._open_devmgr)
        self._filter_edit.textChanged.connect(
            lambda txt: self._populate(self._drivers_ref[0], txt)
        )

        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_workers()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate(self, drivers: List[DriverInfo], filter_text: str = "") -> None:
        if self._table is None:
            return
        ft = filter_text.lower()
        visible = [
            d for d in drivers
            if not ft or ft in d.device_name.lower() or ft in d.driver_class.lower()
        ]
        self._table.setRowCount(len(visible))
        for r, d in enumerate(visible):
            items = [
                d.device_name, d.driver_class, d.version, d.date,
                d.publisher, "✓" if d.signed else "✗", d.flags,
            ]
            for c, val in enumerate(items):
                item = QTableWidgetItem(str(val))
                self._table.setItem(r, c, item)
            if d.error_code != 0 or not d.signed:
                for c in range(len(COLUMNS)):
                    cell = self._table.item(r, c)
                    if cell:
                        cell.setForeground(QColor("#CC2222"))

    def _do_refresh(self) -> None:
        if self._refresh_btn:
            self._refresh_btn.setEnabled(False)
        if self._status_lbl:
            self._status_lbl.setText("Loading...")
        if self._progress:
            self._progress.show()
        if self._table:
            self._table.setRowCount(0)

        # Worker passes itself as first arg — use a wrapper
        worker = Worker(lambda _w: fetch_drivers())

        def on_result(data: List[DriverInfo]) -> None:
            self._drivers_ref[0] = data
            if self._refresh_btn:
                self._refresh_btn.setEnabled(True)
            if self._progress:
                self._progress.hide()
            filter_text = self._filter_edit.text() if self._filter_edit else ""
            self._populate(data, filter_text)
            if self._status_lbl:
                issues = sum(1 for d in data if d.error_code != 0 or not d.signed)
                self._status_lbl.setText(f"{len(data)} drivers, {issues} with issues.")

        def on_error(err_str: str) -> None:
            if self._refresh_btn:
                self._refresh_btn.setEnabled(True)
            if self._progress:
                self._progress.hide()
            if self._status_lbl:
                self._status_lbl.setText(f"Error: {err_str}")

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        self._workers.append(worker)

        if self.app and hasattr(self.app, "thread_pool"):
            self.app.thread_pool.start(worker)
        else:
            QThreadPool.globalInstance().start(worker)

    def _do_export(self) -> None:
        if self._widget is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self._widget, "Export CSV", "drivers.csv", "CSV (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(COLUMNS)
            for d in self._drivers_ref[0]:
                writer.writerow([
                    d.device_name, d.driver_class, d.version, d.date,
                    d.publisher, d.signed, d.flags,
                ])
        if self._status_lbl:
            self._status_lbl.setText(f"Exported to {os.path.basename(path)}")

    def _open_devmgr(self) -> None:
        subprocess.Popen(["mmc", "devmgmt.msc"])
