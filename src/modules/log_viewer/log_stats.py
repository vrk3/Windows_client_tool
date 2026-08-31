"""What is going wrong most often, and where.

Turns "something is wrong" into "this is wrong four thousand times". A real
CBS archive holds 138,683 records and a few hundred distinct sentences; the
counts are how you find which of them matters before reading any of it.

Everything here counts RECORDS, not rows. Folding is a reading convenience
and a filter is a question about what to look at; neither should change an
answer about what the log contains. The pane passes whichever set of entries
it means to summarise.

No Qt, like the reader, the parser and the merge engine it sits beside.
"""
from collections import Counter

from .cmtrace_parser import UNKNOWN_TIME
from .error_codes import _is_failure, find_codes

#: How many rows a panel shows before it stops being scannable.
DEFAULT_TOP_N = 10


def _ranked(counts, limit: int) -> list:
    """Most frequent first, ties broken by the value itself.

    The tie-break is not cosmetic: without it two codes with equal counts
    swap places between refreshes, and a panel that reorders under the
    cursor while you read it is worse than one that is merely arbitrary.
    """
    return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]


def top_codes(entries, limit: int = DEFAULT_TOP_N) -> list:
    """`(code, records)` for the FAILING error codes, most frequent first.

    Success codes are excluded: 4,427 of the 4,553 coded lines in a real
    CBS.log carry nothing but 0x00000000, and counting those would bury the
    handful of failures underneath them.

    Counted once per record even when a line repeats a code, because a row
    is one occurrence of a problem however many times it names the number.
    """
    counts = Counter()
    for entry in entries or ():
        for code in find_codes(entry.message):
            if _is_failure(code):
                counts[code] += 1
    return _ranked(counts, limit)


def top_components(entries, limit: int = DEFAULT_TOP_N) -> list:
    """`(component, records)`, most frequent first.

    A record with no component is not counted as a blank one -- an empty
    string at the top of the list is noise, not an answer.
    """
    counts = Counter(entry.source for entry in entries or () if entry.source)
    return _ranked(counts, limit)


def top_messages(entries, limit: int = DEFAULT_TOP_N, key=None) -> list:
    """`(message, records)`, most frequent first.

    Verbatim by default, which on real logs is almost all ones: CBS lines
    differ by GUID, package name and version. `key` is the seam for a
    normaliser that collapses those into one sentence -- supplying it is a
    task of its own, and this counts whatever it returns.
    """
    counts = Counter()
    for entry in entries or ():
        text = entry.message
        if not text:
            continue
        counts[key(text) if key else text] += 1
    return _ranked(counts, limit)


#: A silence shorter than this is just a log being a log.
DEFAULT_GAP_SECONDS = 30


def _clock(entry):
    """The moment a record happened, or None if it does not carry one.

    Prefers the effective timestamp a merged set assigns, because that is
    what the timeline was actually built on -- measuring a gap against
    anything else would describe an order the view is not in.
    """
    when = entry.raw.get("merge_time") or entry.timestamp
    return None if when == UNKNOWN_TIME else when


def gaps(entries, threshold_seconds: float = DEFAULT_GAP_SECONDS) -> list:
    """`(index, seconds)` for every silence longer than the threshold.

    Longest first, and the index points at the record AFTER the silence --
    the first thing that happened when it started again, which is the row
    worth being taken to.

    A hang leaves no error line; it leaves a hole in the timestamps. Two
    things are deliberately NOT holes:

    * A record with no clock of its own. Treating a continuation's absent
      timestamp as a moment would invent a gap back to the epoch.
    * A backwards step. `setupact.log` and `setuperr.log` both jump ten
      hours backwards at a setup phase boundary; that is a clock changing,
      not silence.
    """
    if threshold_seconds <= 0:
        # A control set to zero would otherwise report every row in the log.
        return []
    found = []
    previous = None
    for index, entry in enumerate(entries or ()):
        when = _clock(entry)
        if when is None:
            continue
        if previous is not None:
            seconds = (when - previous).total_seconds()
            if seconds >= threshold_seconds:
                found.append((index, seconds))
        previous = when
    return sorted(found, key=lambda pair: (-pair[1], pair[0]))
