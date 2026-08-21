"""Reliability as a Diagnose tab.

Everything specific to Reliability is its parser and its search provider; the UI is
`LogPane` by way of `LogReaderModule`.
"""
import logging

from core.log_reader_module import LogReaderModule

from modules.reliability.reliability_reader import read_reliability_records
from modules.reliability.reliability_search_provider import ReliabilitySearchProvider

logger = logging.getLogger(__name__)



class ReliabilityModule(LogReaderModule):
    name = "Reliability"
    icon = "📊"
    description = "Windows reliability records"
    requires_admin = False
    provider_class = ReliabilitySearchProvider

    def load_entries(self, worker):
        return read_reliability_records(
            max_records=1000,
            progress_callback=lambda p: worker.signals.progress.emit(p),
        )