import logging
import os
from abc import ABC, abstractmethod
from typing import List, Callable, Optional

from core.types import LogEntry

logger = logging.getLogger(__name__)


class LogParserBase(ABC):
    """Abstract base for parsing text-based log files (CBS, DISM, WU)."""

    def __init__(self, file_path: str):
        self._file_path = file_path

    @property
    def file_path(self) -> str:
        return self._file_path

    def file_exists(self) -> bool:
        return os.path.isfile(self._file_path)

    def file_size(self) -> int:
        try:
            return os.path.getsize(self._file_path)
        except OSError:
            return 0

    def parse(self, progress_callback: Optional[Callable[[int], None]] = None) -> List[LogEntry]:
        """Parse the log file and return entries. Runs on worker thread."""
        if not self.file_exists():
            logger.warning("Log file not found: %s", self._file_path)
            return []

        entries = []
        try:
            with open(self._file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            total = len(lines)
            for i, line in enumerate(lines):
                entry = self.parse_line(line.rstrip("\n\r"))
                if entry is not None:
                    entries.append(entry)
                if progress_callback and total > 0 and i % 1000 == 0:
                    progress_callback(int((i / total) * 100))

            if progress_callback:
                progress_callback(100)

        except OSError as e:
            logger.error("Failed to read %s: %s", self._file_path, e)

        return entries

    @abstractmethod
    def parse_line(self, line: str) -> Optional[LogEntry]:
        """Parse a single line. Return LogEntry or None if line should be skipped."""
        ...
