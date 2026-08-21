"""Crash Dumps as a Diagnose tab.

Everything specific to Crash Dumps is its parser and its search provider; the UI is
`LogPane` by way of `LogReaderModule`.
"""
import logging

from core.log_reader_module import LogReaderModule

from modules.crash_dumps.crash_dump_reader import read_crash_dumps
from modules.crash_dumps.crash_dump_search_provider import CrashDumpSearchProvider

logger = logging.getLogger(__name__)



class CrashDumpModule(LogReaderModule):
    name = "Crash Dumps"
    icon = "💥"
    description = "Application and system crash dumps"
    requires_admin = True
    provider_class = CrashDumpSearchProvider

    def load_entries(self, worker):
        return read_crash_dumps(
            progress_callback=lambda p: worker.signals.progress.emit(p)
        )