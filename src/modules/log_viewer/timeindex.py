r"""Roughly where in a file a moment lives.

Paging is byte-based, so "go to 09:00 in a 380 MB archive" means walking
there from the window. A sparse index of offset-to-time turns that into a
seek.

**Sparse and approximate on purpose.** It samples the file rather than
reading it, so it answers "start reading here and you will not have missed
it" rather than "the record is at this byte". That is all a seek needs, and
all a log can honestly support: real logs are not sorted by time.
`setupact.log` jumps ten hours backwards at a phase boundary, so any index
over it is a hint, and this one is built and used as one.

Every mark sits on a LINE boundary, the same rule `LogReader._start`
follows -- a byte offset that is not one costs the line it lands inside.

No Qt.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from .cmtrace_parser import UNKNOWN_TIME, parse
from .log_reader import sniff_encoding

logger = logging.getLogger(__name__)

#: How far apart the samples are. 4 MB over the real 84.5 MB archive is 21
#: marks -- enough to land within one window of any moment, cheap enough to
#: build without reading the file.
DEFAULT_STRIDE = 4 * 1024 * 1024

#: How much is read at each sample to find a line with a timestamp on it. A
#: CSI continuation block can run to 1,260 undated lines, so one line is not
#: enough to be sure of finding one.
_PROBE = 64 * 1024


@dataclass(frozen=True)
class Mark:
    """A byte offset, and the moment the record starting there happened."""
    offset: int
    when: datetime


def _first_time(chunk: str) -> Optional[datetime]:
    """The first real timestamp in `chunk`, or None."""
    for entry in parse(chunk):
        if entry.timestamp != UNKNOWN_TIME:
            return entry.timestamp
    return None


def build_index(path: str, every_bytes: int = DEFAULT_STRIDE) -> list:
    """`Mark`s through `path`, one every `every_bytes` or so.

    Each sample seeks to a stride boundary, skips forward to the next line
    so the offset is usable, and reads enough to find a dated record.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    if not size:
        return []

    codec, width = sniff_encoding(path)
    newline = "\n".encode(codec)
    marks = []
    try:
        with open(path, "rb") as handle:
            offset = 0
            while offset < size:
                # Char-aligned, or a UTF-16 read lands mid-character and the
                # whole probe decodes as CJK.
                offset -= offset % width
                handle.seek(offset)
                data = handle.read(_PROBE)
                if not data:
                    break
                start = 0
                if offset:
                    # Mid-file: skip to the next line so the offset is a
                    # boundary someone can actually seek to.
                    cut = data.find(newline)
                    if cut == -1:
                        offset += every_bytes
                        continue
                    start = cut + len(newline)
                when = _first_time(data[start:].decode(codec,
                                                       errors="replace"))
                if when is not None:
                    marks.append(Mark(offset=offset + start, when=when))
                offset += every_bytes
    except OSError:
        logger.warning("Could not index %s", path, exc_info=True)
        return marks
    return marks


def offset_at_or_before(marks: List[Mark], when: datetime) -> int:
    """Where to start reading to be sure of not having missed `when`.

    The LAST mark at or before the moment. A linear walk rather than a
    bisect for the reason `row_at_or_after` is: the marks are not guaranteed
    sorted, because the file they came from need not be.
    """
    if not marks:
        return 0
    best = marks[0].offset
    for mark in marks:
        if mark.when <= when:
            best = mark.offset
    return best
