"""One log-reading pane: toolbar, table, detail panel, error banner.

Six diagnostic tabs and six standalone modules were two implementations of
this widget. The Diagnose one had a Refresh button, an empty state, lazy
loading and an error banner; the module one had none of them. This is the
Diagnose one, extracted, so there is exactly one.

The pane knows nothing about what it is reading. `loader` is an ordinary
worker function — it receives the `Worker` and returns a list of `LogEntry` —
so a caller supplies a parser and nothing else.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QProgressBar, QPushButton, QSplitter,
    QStackedWidget, QVBoxLayout, QWidget,
)

from core.worker import Worker
from ui.detail_panel import DetailPanel
from ui.error_banner import ErrorBanner
from ui.log_table_widget import LogTableWidget

logger = logging.getLogger(__name__)

_PAGE_TABLE = 0
_PAGE_EMPTY = 1


class LogPane(QWidget):
    """A table of log entries with a detail panel, fed by `loader`."""

    entry_selected = pyqtSignal(object)
    entry_activated = pyqtSignal(object)
    entries_loaded = pyqtSignal(object)

    def __init__(
        self,
        loader: Callable[[Worker], list],
        *,
        empty_text: str = "No data — click Refresh",
        extra_controls: Optional[Callable[[QHBoxLayout, dict], None]] = None,
        thread_pool=None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._loader = loader
        self._thread_pool = thread_pool
        self._worker: Optional[Worker] = None
        self._entries: List[object] = []
        self.extra: dict = {}
        self.loaded = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(4)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        if extra_controls is not None:
            extra_controls(toolbar, self.extra)
        toolbar.addStretch()

        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        toolbar.addWidget(self._progress)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setObjectName("refreshBtn")
        self._refresh_btn.clicked.connect(lambda: self.load(force=True))
        toolbar.addWidget(self._refresh_btn)
        root.addLayout(toolbar)

        self._error_banner = ErrorBanner(parent=self)
        root.addWidget(self._error_banner)

        splitter = QSplitter()
        self._table = LogTableWidget()
        splitter.addWidget(self._table)
        self._detail = DetailPanel()
        splitter.addWidget(self._detail)
        splitter.setSizes([700, 300])

        self._stack = QStackedWidget()
        self._stack.addWidget(splitter)
        empty = QLabel(empty_text)
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color: #888; font-size: 14px;")
        self._stack.addWidget(empty)
        self._stack.setCurrentIndex(_PAGE_EMPTY)
        root.addWidget(self._stack, 1)

        self._table.row_selected.connect(self._on_row_selected)
        self._table.row_double_clicked.connect(self.entry_activated.emit)

    # -- loading ---------------------------------------------------------
    def load(self, force: bool = False) -> None:
        """Run `loader` on a worker and fill the table with what it returns."""
        if self.loaded and not force:
            return
        if self._worker is not None:
            self._worker.cancel()

        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._error_banner.clear()

        worker = Worker(self._loader)
        worker.signals.progress.connect(self._progress.setValue)
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        self._worker = worker
        pool = self._thread_pool
        if pool is None:
            from PyQt6.QtCore import QThreadPool
            pool = QThreadPool.globalInstance()
        pool.start(worker)

    def cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    def _on_result(self, entries) -> None:
        self._worker = None
        self.loaded = True
        self.set_entries(entries or [])
        self.entries_loaded.emit(self._entries)

    def _on_error(self, error_info) -> None:
        self._worker = None
        self.show_error(str(error_info))

    # -- content ---------------------------------------------------------
    def set_entries(self, entries) -> None:
        self._entries = list(entries or [])
        self._progress.setVisible(False)
        self._table.set_entries(self._entries)
        self._stack.setCurrentIndex(_PAGE_TABLE if self._entries else _PAGE_EMPTY)

    def show_error(self, message: str) -> None:
        self._progress.setVisible(False)
        self._error_banner.set_error(message)

    def clear_error(self) -> None:
        self._error_banner.clear()

    def _on_row_selected(self, entry) -> None:
        self._detail.show_entry(entry)
        self.entry_selected.emit(entry)

    # -- introspection, for tests and for get_status_info ----------------
    def entries(self) -> List[object]:
        return list(self._entries)

    def row_count(self) -> int:
        return len(self._entries)

    def is_showing_empty_state(self) -> bool:
        return self._stack.currentIndex() == _PAGE_EMPTY

    def is_showing_error(self) -> bool:
        # isHidden(), NOT isVisible(). A child of a parent that has never been
        # shown is not "visible" no matter what you call on it, so isVisible()
        # is False even right after set_error(). show() clears the explicit
        # hide flag, which is what isHidden() reports.
        return not self._error_banner.isHidden()

    def error_text(self) -> str:
        return self._error_banner.text()
