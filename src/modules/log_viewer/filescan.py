r"""Searching the part of a log that was never loaded.

The window holds 32 MB of a 380 MB archive, so a search over what is in
memory can answer "no match" about a file that contains the thing. That is
the worst answer a log viewer can give, because it is believed.

Two details carry this:

* **The reads overlap.** A needle straddling a block boundary is invisible
  otherwise, and it would fail silently -- the scan would simply report one
  fewer hit than there is. The overlap is carried as TEXT, after decoding,
  so a multi-byte character split across the seam is not mangled either.
* **Offsets are line starts.** A byte offset landing mid-line is not
  something the reader can seek to without losing the line it lands inside,
  which is the rule `LogReader._start` already follows.

No Qt: the pane decides what to do with a hit.
"""
import logging
import os
import re
from dataclasses import dataclass

from .log_reader import sniff_encoding

logger = logging.getLogger(__name__)

#: Read size. Big enough that the overlap is negligible, small enough that a
#: cancel is noticed promptly.
DEFAULT_BLOCK = 4 * 1024 * 1024

#: How much text is carried between blocks. Longer than any sane needle, and
#: the cost is one copy per block.
_OVERLAP = 4096

#: A scan of a 380 MB file can match a great many times; nobody reads more
#: than the first handful, and holding them all is pointless.
DEFAULT_LIMIT = 200


@dataclass(frozen=True)
class Hit:
    """Where a match is, and the line it is on."""
    offset: int
    line: str


def scan_file(path: str, needle: str, regex: bool = False,
              start: int = 0, end: int = None, limit: int = DEFAULT_LIMIT,
              block_size: int = DEFAULT_BLOCK, is_cancelled=None) -> list:
    """Every match of `needle` in `path` between `start` and `end`.

    `end` is what makes this useful: pass the byte offset the loaded window
    begins at and the scan covers exactly the part nobody has seen.

    A half-typed regex finds nothing rather than raising -- the same rule the
    Filter box follows, since this is driven from the same text.
    """
    if not needle:
        return []
    try:
        matcher = re.compile(needle if regex else re.escape(needle),
                             re.IGNORECASE)
    except re.error:
        return []

    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    stop = size if end is None else min(end, size)
    if start >= stop:
        return []

    codec, width = sniff_encoding(path)
    hits = []
    seen = set()
    carried = ""
    # Where `carried` begins in the file, so an offset can be worked back to
    # a real byte position.
    carried_at = start
    try:
        with open(path, "rb") as handle:
            handle.seek(start - start % width)
            position = start
            while position < stop:
                if is_cancelled is not None and is_cancelled():
                    return []
                chunk = handle.read(min(block_size, stop - position))
                if not chunk:
                    break
                text = carried + chunk.decode(codec, errors="replace")
                for match in matcher.finditer(text):
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.start())
                    line = text[line_start:
                                line_end if line_end != -1 else len(text)]
                    offset = carried_at + len(
                        text[:line_start].encode(codec))
                    # Deduplicated on the absolute LINE offset, never on
                    # "did this match start inside the carried text". That
                    # test is wrong: a needle STRADDLING the boundary also
                    # starts inside the overlap and has never been reported,
                    # so the guard would eat a real match -- the very case
                    # the overlap exists to catch.
                    if offset in seen:
                        continue
                    seen.add(offset)
                    # Every log under C:/Windows/Logs is UTF-8 WITH a
                    # BOM, and a hit on the first line carried the
                    # invisible U+FEFF along. LogReader strips it, so
                    # this must too or the two disagree about what
                    # the first line of a file says.
                    hits.append(Hit(offset=offset,
                                    line=line.strip().lstrip("﻿")))
                    if len(hits) >= limit:
                        return hits
                position += len(chunk)
                carried = text[-_OVERLAP:]
                carried_at = position - len(carried.encode(codec))
    except OSError:
        logger.warning("Could not scan %s", path, exc_info=True)
        return hits
    return hits
