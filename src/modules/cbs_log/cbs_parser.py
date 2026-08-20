import re
import logging
from datetime import datetime
from typing import Optional

from core.log_parser_base import LogParserBase
from core.types import LogEntry

logger = logging.getLogger(__name__)

_CBS_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}), (\w+)\s+(\S+)\s+(.+)$"
)


class CBSParser(LogParserBase):
    """Parser for C:\\Windows\\Logs\\CBS\\CBS.log."""

    def __init__(self, file_path: str) -> None:
        super().__init__(file_path)
        # Carried so a continuation line can inherit the record it belongs to.
        self._last_timestamp = datetime.min
        self._last_source = ""


    def parse_line(self, line: str) -> Optional[LogEntry]:
        m = _CBS_PATTERN.match(line)
        if not m:
            return self._continuation(line)
        timestamp_str, level, component, message = m.groups()
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.debug("Unparseable timestamp: %s", timestamp_str)
            return None
        self._last_timestamp = timestamp
        self._last_source = component
        return LogEntry(
            timestamp=timestamp,
            source=component,
            level=level.capitalize() if level.lower() in ("info", "warning", "error", "debug") else level,
            message=message.strip(),
            raw={"component": component, "raw_level": level},
        )

    def _continuation(self, line: str):
        """A line that is not a new record, but belongs to the one above.

        Returning None here drops it. On a real CBS.log that is 7.4% of the
        file -- the indented detail under a message, which is usually the
        part that says WHY. It inherits the timestamp and component of the
        record it continues, because that is when and where it happened, but
        NOT the severity: inheriting "Error" would colour a detail line as an
        error of its own and inflate any count of them.
        """
        text = line.strip()
        if not text:
            return None
        return LogEntry(
            timestamp=self._last_timestamp,
            source=self._last_source,
            level="Info",
            message=line.rstrip(),
            raw={"continuation": True},
        )
