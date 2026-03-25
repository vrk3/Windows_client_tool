import logging
import os
import struct
from datetime import datetime
from typing import List, Optional, Callable

from core.types import LogEntry

logger = logging.getLogger(__name__)

MINIDUMP_DIR = r"C:\Windows\Minidump"


def read_crash_dumps(
    dump_dir: str = MINIDUMP_DIR,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> List[LogEntry]:
    """List minidump files and extract basic metadata."""
    entries = []

    if not os.path.isdir(dump_dir):
        logger.warning("Minidump directory not found: %s", dump_dir)
        return entries

    try:
        files = [f for f in os.listdir(dump_dir) if f.lower().endswith(".dmp")]
    except PermissionError:
        logger.error("Permission denied reading %s", dump_dir)
        return entries

    total = len(files)
    for i, filename in enumerate(files):
        filepath = os.path.join(dump_dir, filename)
        try:
            stat = os.stat(filepath)
            file_time = datetime.fromtimestamp(stat.st_mtime)
            file_size = stat.st_size

            # Try to read minidump signature and basic header
            bug_check = "Unknown"
            try:
                with open(filepath, "rb") as f:
                    header = f.read(32)
                    if len(header) >= 32:
                        signature = header[:4]
                        if signature == b"MDMP":
                            # Minidump header - try to extract bug check code
                            # at offset 0x20 in full dumps, but minidumps vary
                            bug_check = "MINIDUMP"
            except (PermissionError, OSError):
                bug_check = "Access Denied"

            entries.append(LogEntry(
                timestamp=file_time,
                source="Minidump",
                level="Error",
                message=f"{filename} ({file_size // 1024}KB) — {bug_check}",
                raw={
                    "filename": filename,
                    "filepath": filepath,
                    "file_size": file_size,
                    "bug_check": bug_check,
                },
            ))
        except OSError as e:
            logger.warning("Could not read dump file %s: %s", filename, e)

        if progress_callback and total > 0:
            progress_callback(min(int(((i + 1) / total) * 100), 99))

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    if progress_callback:
        progress_callback(100)
    return entries
