"""Event Viewer as a Diagnose tab.

The only one of the six with its own toolbar control: a time-range combo the
loader reads before it starts, which is what `LogPane`'s extra-controls hook
exists for.
"""
import logging

from PyQt6.QtWidgets import QComboBox, QLabel

from core.log_reader_module import LogReaderModule

from modules.event_viewer.event_reader import read_all_logs
from modules.event_viewer.event_search_provider import EventViewerSearchProvider

logger = logging.getLogger(__name__)

HOURS_MAP = {
    "1 hour": 1, "6 hours": 6, "12 hours": 12,
    "24 hours": 24, "48 hours": 48, "7 days": 168,
}


class EventViewerModule(LogReaderModule):
    name = "Event Viewer"
    icon = "📋"
    description = "Windows event logs across every channel"
    requires_admin = False
    provider_class = EventViewerSearchProvider

    def build_controls(self, toolbar, extra) -> None:
        toolbar.addWidget(QLabel("Time Range:"))
        combo = QComboBox()
        combo.addItems(list(HOURS_MAP))
        combo.setCurrentIndex(3)  # Default: 24 hours
        toolbar.addWidget(combo)
        extra["hours_combo"] = combo

    def load_entries(self, worker):
        # The combo is read here, on the way in, so the worker never touches a
        # widget from its own thread.
        hours_back = 24
        if self._pane is not None:
            combo = self._pane.extra.get("hours_combo")
            if combo is not None:
                hours_back = HOURS_MAP.get(combo.currentText(), 24)
        return read_all_logs(
            hours_back=hours_back,
            max_events_per_log=2000,
            progress_callback=lambda p: worker.signals.progress.emit(p),
        )
