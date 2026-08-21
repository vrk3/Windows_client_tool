"""Windows Update as a Diagnose tab.

Everything specific to Windows Update is its parser and its search provider; the UI is
`LogPane` by way of `LogReaderModule`.
"""
import logging

from core.log_reader_module import LogReaderModule

from modules.windows_update.wu_parser import WUParser
from modules.windows_update.wu_search_provider import WUSearchProvider

logger = logging.getLogger(__name__)

WU_LOG_PATH = r"C:\Windows\SoftwareDistribution\ReportingEvents.log"


class WindowsUpdateModule(LogReaderModule):
    name = "Windows Update"
    icon = "🪟"
    description = "Windows Update reporting events"
    requires_admin = False
    provider_class = WUSearchProvider

    def load_entries(self, worker):
        parser = WUParser(WU_LOG_PATH)
        return parser.parse(
            progress_callback=lambda p: worker.signals.progress.emit(p)
        )