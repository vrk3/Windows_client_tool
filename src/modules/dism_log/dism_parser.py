import re
import logging
from datetime import datetime
from typing import Optional

from core.log_parser_base import LogParserBase
from core.types import LogEntry

logger = logging.getLogger(__name__)

_DISM_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}), (\w+)\s+(\S+)\s+(.+)$"
)


class DISMParser(LogParserBase):
    """Parser for C:\\Windows\\Logs\\DISM\\dism.log."""

    def parse_line(self, line: str) -> Optional[LogEntry]:
        m = _DISM_PATTERN.match(line)
        if not m:
            return None
        timestamp_str, level, component, message = m.groups()
        try:
            timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            logger.debug("Unparseable timestamp: %s", timestamp_str)
            return None
        return LogEntry(
            timestamp=timestamp,
            source=component,
            level=level.capitalize() if level.lower() in ("info", "warning", "error", "debug") else level,
            message=message.strip(),
            raw={"component": component, "raw_level": level},
        )
