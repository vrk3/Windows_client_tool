import logging
from typing import Optional

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget, QProgressBar

from core.base_module import BaseModule
from core.search_provider import SearchProvider
from core.worker import Worker
from ui.log_table_widget import LogTableWidget
from ui.detail_panel import DetailPanel
from modules.cbs_log.cbs_parser import CBSParser
from modules.cbs_log.cbs_search_provider import CBSSearchProvider

logger = logging.getLogger(__name__)

CBS_LOG_PATH = r"C:\Windows\Logs\CBS\CBS.log"


class CBSLogModule(BaseModule):
    name = "CBS Log"
    icon = "cbs_log"
    description = "Component-Based Servicing log parser"
    requires_admin = False

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._table: Optional[LogTableWidget] = None
        self._detail: Optional[DetailPanel] = None
        self._progress: Optional[QProgressBar] = None
        self._search_provider = CBSSearchProvider()

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Controls row with progress bar
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
            self._load_log()

    def on_deactivate(self) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def get_toolbar_actions(self) -> list:
        actions = []
        refresh = QAction("Refresh", None)
        refresh.triggered.connect(self._load_log)
        actions.append(refresh)

        export = QAction("Export CSV", None)
        export.triggered.connect(lambda: self._table.export_csv() if self._table else None)
        actions.append(export)

        return actions

    def get_status_info(self) -> str:
        count = len(self._table.get_entries()) if self._table else 0
        return f"CBS Log — {count} entries"

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._search_provider

    def _load_log(self) -> None:
        if self._progress:
            self._progress.setVisible(True)
            self._progress.setValue(0)

        def do_work(worker):
            parser = CBSParser(CBS_LOG_PATH)
            return parser.parse(progress_callback=lambda p: worker.signals.progress.emit(p))

        worker = Worker(do_work)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_log_loaded)
        worker.signals.error.connect(self._on_load_error)
        self._workers.append(worker)

        if self.app:
            self.app.thread_pool.start(worker)
        else:
            # Run synchronously when no app context (e.g. tests)
            worker.run()

    def _on_progress(self, value: int) -> None:
        if self._progress:
            self._progress.setValue(value)

    def _on_log_loaded(self, entries) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if self._table:
            self._table.set_entries(entries)
            self._search_provider.set_entries(entries)
            logger.info("Loaded %d CBS log entries", len(entries))

    def _on_load_error(self, error_info) -> None:
        if self._progress:
            self._progress.setVisible(False)
        logger.error("Failed to load CBS log: %s", error_info)

    def _on_row_double_clicked(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)

    def _on_row_selected(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)
