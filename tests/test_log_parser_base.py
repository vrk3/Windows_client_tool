import os
import tempfile
from datetime import datetime
from typing import Optional

from core.log_parser_base import LogParserBase
from core.types import LogEntry


class SimpleParser(LogParserBase):
    def parse_line(self, line: str) -> Optional[LogEntry]:
        if not line.strip():
            return None
        return LogEntry(
            timestamp=datetime(2026, 1, 1),
            source="test",
            level="Info",
            message=line,
        )


def test_parse_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("line one\nline two\n\nline three\n")
        path = f.name
    try:
        parser = SimpleParser(path)
        entries = parser.parse()
        assert len(entries) == 3
        assert entries[0].message == "line one"
        assert entries[2].message == "line three"
    finally:
        os.unlink(path)


def test_file_not_found():
    parser = SimpleParser("/nonexistent/file.log")
    entries = parser.parse()
    assert entries == []


def test_progress_callback():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        for i in range(2000):
            f.write(f"line {i}\n")
        path = f.name
    try:
        progress_values = []
        parser = SimpleParser(path)
        entries = parser.parse(progress_callback=lambda p: progress_values.append(p))
        assert len(entries) == 2000
        assert 100 in progress_values  # Final progress
    finally:
        os.unlink(path)
