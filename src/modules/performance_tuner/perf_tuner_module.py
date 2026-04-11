# src/modules/performance_tuner/perf_tuner_module.py
import logging
from typing import Dict, List

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.performance_tuner.perf_checks import PERF_CHECKS

logger = logging.getLogger(__name__)

_STATUS_ICON = {"optimal": "✅", "suboptimal": "⚠️", "unknown": "❓"}
_STATUS_LABEL = {"optimal": "Optimal", "suboptimal": "Suboptimal", "unknown": "Unknown"}


class PerfTunerModule(BaseModule):
    name = "Performance Tuner"
    icon = "⚡"
    description = "Checklist of Windows performance best-practice settings with one-click apply."
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._widget: QWidget | None = None
        self._statuses: Dict[str, str] = {}

    def create_widget(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)

        # Toolbar
        toolbar = QHBoxLayout()
        self._scan_btn = QPushButton("🔍 Scan")
        self._scan_btn.clicked.connect(self._run_scan)
        toolbar.addWidget(self._scan_btn)
        self._apply_all_btn = QPushButton("✅ Apply All Recommended")
        self._apply_all_btn.setEnabled(False)
        self._apply_all_btn.clicked.connect(self._apply_all)
        toolbar.addWidget(self._apply_all_btn)
        toolbar.addStretch()
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(200)
        toolbar.addWidget(self._progress)
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Category", "Name", "Status", "Reboot?", "Action"])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self._table)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        self._widget = root
        self._populate_table()
        return root

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        for check in PERF_CHECKS:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(check["category"]))
            name_item = QTableWidgetItem(check["name"])
            name_item.setToolTip(check["description"])
            self._table.setItem(row, 1, name_item)
            status = self._statuses.get(check["id"], "unknown")
            icon = _STATUS_ICON[status]
            lbl = _STATUS_LABEL[status]
            status_item = QTableWidgetItem(f"{icon} {lbl}")
            self._table.setItem(row, 2, status_item)
            self._table.setItem(row, 3, QTableWidgetItem("Yes" if check["reboot"] else "No"))
            # Apply button per row
            apply_btn = QPushButton("Apply")
            apply_btn.setEnabled(status == "suboptimal")
            apply_btn.clicked.connect(lambda _, c=check: self._apply_single(c))
            self._table.setCellWidget(row, 4, apply_btn)

    def _run_scan(self) -> None:
        self._scan_btn.setEnabled(False)
        self._apply_all_btn.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setRange(0, len(PERF_CHECKS))
        self._progress.setValue(0)
        self._statuses.clear()

        checks = list(PERF_CHECKS)

        def work(worker):
            results = {}
            for i, check in enumerate(checks):
                if worker.is_cancelled:
                    break
                try:
                    results[check["id"]] = check["detect"]()
                except Exception:
                    results[check["id"]] = "unknown"
                worker.signals.progress.emit(i + 1)
            return results

        def on_result(results):
            self._statuses = results
            self._populate_table()
            suboptimal = sum(1 for s in results.values() if s == "suboptimal")
            self._status_label.setText(
                f"Scan complete — {suboptimal} item(s) could be improved."
            )
            self._apply_all_btn.setEnabled(suboptimal > 0)

        def on_done():
            self._scan_btn.setEnabled(True)
            self._progress.setVisible(False)

        w = Worker(work)
        w.signals.result.connect(on_result)
        w.signals.finished.connect(on_done)
        w.signals.progress.connect(self._progress.setValue)
        self._workers.append(w)
        QThreadPool.globalInstance().start(w)

    def _apply_single(self, check: Dict) -> None:
        if self.app is None or not hasattr(self.app, "backup"):
            return
        from modules.tweaks.tweak_engine import TweakEngine
        engine = TweakEngine(self.app.backup)
        rp_id = self.app.backup.create_restore_point(f"PerfTuner: {check['name']}", "PerfTuner")
        tweak = {"id": check["id"], "steps": check["apply"]}
        success = engine.apply_tweak(tweak, rp_id)
        if success:
            self._statuses[check["id"]] = "optimal"
            self._status_label.setText(f"Applied: {check['name']}")
        else:
            self._status_label.setText(f"Failed to apply: {check['name']}")
        self._populate_table()

    def _apply_all(self) -> None:
        suboptimal = [c for c in PERF_CHECKS if self._statuses.get(c["id"]) == "suboptimal"]
        for check in suboptimal:
            self._apply_single(check)

    def get_status_info(self) -> str:
        return "Performance Tuner"

    def get_refresh_interval(self) -> Optional[int]:
        return 120_000

    def refresh_data(self) -> None:
        self._run_scan()

    def on_activate(self) -> None:
        self._run_scan()

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
