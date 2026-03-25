import logging
from typing import Optional

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget, QProgressBar

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider
from core.worker import Worker
from ui.log_table_widget import LogTableWidget
from ui.detail_panel import DetailPanel
from modules.reliability.reliability_reader import read_reliability_records
from modules.reliability.reliability_search_provider import ReliabilitySearchProvider

logger = logging.getLogger(__name__)


class ReliabilityModule(BaseModule):
    name = "Reliability"
    icon = "reliability"
    description = "Windows Reliability Monitor records"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._table: Optional[LogTableWidget] = None
        self._detail: Optional[DetailPanel] = None
        self._progress: Optional[QProgressBar] = None
        self._search_provider = ReliabilitySearchProvider()

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Controls row
        controls = QHBoxLayout()
        controls.addStretch()
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        controls.addWidget(self._progress)
        layout.addLayout(controls)

        # Splitter: table + detail panel
        splitter = QSplitter()
        self._table = LogTableWidget()
        self._table.row_double_clicked.connect(self._on_row_double_clicked)
        self._table.row_selected.connect(self._on_row_selected)
        splitter.addWidget(self._table)

        self._detail = DetailPanel()
        splitter.addWidget(self._detail)
        splitter.setSizes([700, 300])

        layout.addWidget(splitter)
        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        if self._table and len(self._table.get_entries()) == 0:
            self._load_records()

    def on_deactivate(self) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def get_toolbar_actions(self) -> list:
        actions = []
        refresh = QAction("Refresh", None)
        refresh.triggered.connect(self._load_records)
        actions.append(refresh)

        export = QAction("Export CSV", None)
        export.triggered.connect(lambda: self._table.export_csv() if self._table else None)
        actions.append(export)

        return actions

    def get_status_info(self) -> str:
        count = len(self._table.get_entries()) if self._table else 0
        return f"Reliability — {count} records"

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._search_provider

    def _load_records(self) -> None:
        if self._progress:
            self._progress.setVisible(True)
            self._progress.setValue(0)

        def do_work(worker):
            return read_reliability_records(
                progress_callback=lambda p: worker.signals.progress.emit(p),
            )

        worker = Worker(do_work)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_records_loaded)
        worker.signals.error.connect(self._on_load_error)
        self._workers.append(worker)

        if self.app:
            self.app.thread_pool.start(worker)

    def _on_progress(self, value: int) -> None:
        if self._progress:
            self._progress.setValue(value)

    def _on_records_loaded(self, entries) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if self._table:
            self._table.set_entries(entries)
            self._search_provider.set_entries(entries)
            logger.info("Loaded %d reliability records", len(entries))

    def _on_load_error(self, error_info) -> None:
        if self._progress:
            self._progress.setVisible(False)
        logger.error("Failed to load reliability records: %s", error_info)

    def _on_row_double_clicked(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)

    def _on_row_selected(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)
