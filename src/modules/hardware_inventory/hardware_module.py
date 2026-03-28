import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QHeaderView, QLabel,
    QFileDialog, QProgressBar,
)
from PyQt6.QtCore import QThreadPool

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import COMWorker
from modules.hardware_inventory import hardware_reader as hr


def _make_kv_table(parent=None) -> QTableWidget:
    t = QTableWidget(0, 2, parent)
    t.setHorizontalHeaderLabels(["Property", "Value"])
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return t


def _fill_kv(table: QTableWidget, rows):
    table.setRowCount(len(rows))
    for r, (k, v) in enumerate(rows):
        table.setItem(r, 0, QTableWidgetItem(str(k)))
        table.setItem(r, 1, QTableWidgetItem(str(v)))


def _make_dict_table(columns, parent=None) -> QTableWidget:
    t = QTableWidget(0, len(columns), parent)
    t.setHorizontalHeaderLabels(columns)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return t


def _fill_dict(table: QTableWidget, rows, columns):
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, col in enumerate(columns):
            table.setItem(r, c, QTableWidgetItem(str(row.get(col, ""))))


class _LoadingTab(QWidget):
    """Generic tab: shows loading state, loads data in COMWorker, fills a table."""

    def __init__(self, loader_fn, setup_table_fn, parent=None):
        super().__init__(parent)
        self._loader = loader_fn
        self._setup_fn = setup_table_fn

        layout = QVBoxLayout(self)
        self._status = QLabel("Click Refresh to load.")
        self._refresh_btn = QPushButton("Refresh")
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._refresh_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._status)
        layout.addLayout(btn_row)
        layout.addWidget(self._progress)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._content, 1)

        self._refresh_btn.clicked.connect(self._load)

    def _load(self):
        self._refresh_btn.setEnabled(False)
        self._status.setText("Loading...")
        self._progress.show()
        # COMWorker initialises COM STA on the thread — required for WMI calls.
        # Worker passes itself as first arg to the loader function.
        worker = COMWorker(self._loader)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_result(self, data):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText("Loaded.")
        # Clear old content widgets
        for i in reversed(range(self._content_layout.count())):
            item = self._content_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._setup_fn(self._content_layout, data)

    def _on_error(self, err):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText(f"Error: {err}")


class HardwareModule(BaseModule):
    name = "hardware_inventory"
    icon = "🖥"
    description = "Hardware and system information"
    requires_admin = False
    group = ModuleGroup.SYSTEM

    def create_widget(self) -> QWidget:
        outer = QWidget()
        vbox = QVBoxLayout(outer)
        vbox.setContentsMargins(0, 0, 0, 0)

        # Export button row
        export_btn = QPushButton("Export HTML Report")
        export_btn.setFixedWidth(160)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(export_btn)
        vbox.addLayout(btn_row)

        tabs = QTabWidget()
        vbox.addWidget(tabs, 1)

        # ── Overview ────────────────────────────────────────────────────────
        def setup_overview(layout, data):
            t = _make_kv_table()
            _fill_kv(t, data)
            layout.addWidget(t)

        tabs.addTab(_LoadingTab(hr.get_overview, setup_overview), "Overview")

        # ── CPU ─────────────────────────────────────────────────────────────
        def setup_cpu(layout, data):
            t = _make_kv_table()
            _fill_kv(t, data)
            layout.addWidget(t)

        tabs.addTab(_LoadingTab(hr.get_cpu_info, setup_cpu), "CPU")

        # ── Memory ──────────────────────────────────────────────────────────
        def setup_mem(layout, data):
            summary, sticks = data
            lbl = QLabel("Summary")
            lbl.setStyleSheet("font-weight:bold")
            layout.addWidget(lbl)
            t1 = _make_kv_table()
            _fill_kv(t1, summary)
            t1.setMaximumHeight(100)
            layout.addWidget(t1)
            lbl2 = QLabel("Memory Sticks")
            lbl2.setStyleSheet("font-weight:bold")
            layout.addWidget(lbl2)
            cols = ["Bank", "Capacity", "Speed", "Manufacturer", "PartNumber"]
            t2 = _make_dict_table(cols)
            _fill_dict(t2, sticks, cols)
            layout.addWidget(t2)

        tabs.addTab(_LoadingTab(hr.get_memory_info, setup_mem), "Memory")

        # ── Storage ─────────────────────────────────────────────────────────
        def setup_storage(layout, data):
            drives, partitions = data
            lbl = QLabel("Physical Drives")
            lbl.setStyleSheet("font-weight:bold")
            layout.addWidget(lbl)
            cols = ["Model", "Size", "Interface", "Serial", "Partitions"]
            t1 = _make_dict_table(cols)
            _fill_dict(t1, drives, cols)
            t1.setMaximumHeight(150)
            layout.addWidget(t1)
            lbl2 = QLabel("Partitions")
            lbl2.setStyleSheet("font-weight:bold")
            layout.addWidget(lbl2)
            cols2 = ["Mount", "FS", "Total", "Used", "Free", "Use%"]
            t2 = _make_dict_table(cols2)
            _fill_dict(t2, partitions, cols2)
            layout.addWidget(t2)

        tabs.addTab(_LoadingTab(hr.get_storage_info, setup_storage), "Storage")

        # ── GPU ─────────────────────────────────────────────────────────────
        def setup_gpu(layout, data):
            cols = ["Name", "RAM", "Driver Version", "Driver Date", "Resolution"]
            t = _make_dict_table(cols)
            _fill_dict(t, data, cols)
            layout.addWidget(t)

        tabs.addTab(_LoadingTab(hr.get_gpu_info, setup_gpu), "GPU")

        # ── Network Adapters ────────────────────────────────────────────────
        def setup_net(layout, data):
            cols = ["Name", "IP", "MAC", "Speed", "Up"]
            t = _make_dict_table(cols)
            _fill_dict(t, data, cols)
            layout.addWidget(t)

        tabs.addTab(_LoadingTab(hr.get_network_info, setup_net), "Network Adapters")

        # ── BIOS/Firmware ───────────────────────────────────────────────────
        def setup_bios(layout, data):
            t = _make_kv_table()
            _fill_kv(t, data)
            layout.addWidget(t)

        tabs.addTab(_LoadingTab(hr.get_bios_info, setup_bios), "BIOS/Firmware")

        # ── Export ──────────────────────────────────────────────────────────
        def do_export():
            path, _ = QFileDialog.getSaveFileName(
                outer, "Export Report", "hardware_report.html", "HTML (*.html)"
            )
            if path:
                html = hr.generate_html_report()
                with open(path, "w", encoding="utf-8") as f:
                    f.write(html)
                os.startfile(path)

        export_btn.clicked.connect(do_export)

        return outer

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
