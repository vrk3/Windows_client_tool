import logging
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHBoxLayout, QSplitter, QStackedWidget, QVBoxLayout, QWidget, QComboBox, QLabel, QProgressBar

from ui.error_banner import ErrorBanner

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider
from core.worker import Worker
from ui.log_table_widget import LogTableWidget
from ui.detail_panel import DetailPanel
from modules.event_viewer.event_reader import read_all_logs
from modules.event_viewer.event_search_provider import EventViewerSearchProvider

logger = logging.getLogger(__name__)


class EventViewerModule(BaseModule):
    name = "Event Viewer"
    icon = "📋"
    description = "Windows Event Log viewer (System, Application, Security)"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._table: Optional[LogTableWidget] = None
        self._detail: Optional[DetailPanel] = None
        self._progress: Optional[QProgressBar] = None
        self._search_provider = EventViewerSearchProvider()
        self._hours_combo: Optional[QComboBox] = None
        self._error_banner: Optional[ErrorBanner] = None
        self._empty_label: Optional[QLabel] = None
        self._table_stack: Optional[QStackedWidget] = None

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Controls row
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Time Range:"))
        self._hours_combo = QComboBox()
        self._hours_combo.addItems(["1 hour", "6 hours", "12 hours", "24 hours", "48 hours", "7 days"])
        self._hours_combo.setCurrentIndex(3)  # Default: 24 hours
        controls.addWidget(self._hours_combo)
        controls.addStretch()
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        controls.addWidget(self._progress)
        layout.addLayout(controls)

        # Error banner
        self._error_banner = ErrorBanner(parent=self._widget)
        layout.addWidget(self._error_banner)

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

        # Empty state overlay
        self._table_stack = QStackedWidget()
        self._table_stack.addWidget(splitter)
        empty_page = QLabel("No data \u2014 click Refresh")
        empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_page.setStyleSheet("color: #888; font-size: 14px;")
        self._table_stack.addWidget(empty_page)
        self._empty_label = empty_page
        # Replace splitter in layout with stacked widget
        layout.removeWidget(splitter)
        layout.addWidget(self._table_stack)

        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        if self._table and len(self._table.get_entries()) == 0:
            self._load_events()

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def get_toolbar_actions(self) -> list:
        actions = []
        refresh = QAction("Refresh", None)
        refresh.triggered.connect(self._load_events)
        actions.append(refresh)

        export = QAction("Export CSV", None)
        export.triggered.connect(lambda: self._table.export_csv() if self._table else None)
        actions.append(export)

        return actions

    def get_status_info(self) -> str:
        count = len(self._table.get_entries()) if self._table else 0
        return f"Event Viewer — {count} events"

    def get_refresh_interval(self) -> int:
        return 10000  # 10 seconds

    def refresh_data(self) -> None:
        self._load_events()

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._search_provider

    def _get_hours_back(self) -> int:
        if not self._hours_combo:
            return 24
        text = self._hours_combo.currentText()
        mapping = {"1 hour": 1, "6 hours": 6, "12 hours": 12, "24 hours": 24, "48 hours": 48, "7 days": 168}
        return mapping.get(text, 24)

    def _load_events(self) -> None:
        if self._progress:
            self._progress.setVisible(True)
            self._progress.setValue(0)

        hours = self._get_hours_back()
        # Check if running as admin for Security log
        try:
            from core.admin_utils import is_admin
            include_security = is_admin()
        except Exception:
            include_security = False

        def do_work(worker):
            return read_all_logs(
                hours_back=hours,
                max_events_per_log=2000,
                include_security=include_security,
                progress_callback=lambda p: worker.signals.progress.emit(p),
            )

        worker = Worker(do_work)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_events_loaded)
        worker.signals.error.connect(self._on_load_error)
        self._workers.append(worker)

        if self.app:
            self.app.thread_pool.start(worker)

    def _on_progress(self, value: int) -> None:
        if self._progress:
            self._progress.setValue(value)

    def _on_events_loaded(self, entries) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if self._table:
            self._table.set_entries(entries)
            self._search_provider.set_entries(entries)
            logger.info("Loaded %d event log entries", len(entries))
        if self._table_stack:
            self._table_stack.setCurrentIndex(0 if entries else 1)

    def _on_load_error(self, error_info) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if self._error_banner:
            self._error_banner.set_error(str(error_info))
        logger.error("Failed to load events: %s", error_info)

    def _on_row_double_clicked(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)

    def _on_row_selected(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)
