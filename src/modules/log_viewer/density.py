"""Where a log's records -- and its failures -- actually fall in time.

The data behind the density strip. On a 1.5-million-record archive, seeing
where the errors cluster is the difference between reading a log and hunting
through one.

Qt-free: painting the bars is the pane's business, deciding what they mean is
this module's.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .log_set import effective_time as _clock


@dataclass(frozen=True)
class Bucket:
    """One slice of the timeline, and what happened in it."""
    start: datetime
    end: datetime
    total: int
    errors: int


def buckets(entries, count: int = 120) -> list:
    """`count` equal slices of the span, each with its totals.

    Records with no clock are EXCLUDED rather than bucketed at the epoch:
    a continuation carries no timestamp, and placing one at year 1 would
    stretch the range back two millennia and squash the entire log into a
    single bar at the right-hand edge.

    The range is the MIN and MAX timestamp seen, not the first and last
    record. `setupact.log` jumps ten hours backwards mid-file, and taking
    the ends in file order would produce an inverted span.
    """
    if count <= 0:
        return []
    stamps = [when for when in (_clock(entry) for entry in entries or ())
              if when is not None]
    if not stamps:
        return []

    first, last = min(stamps), max(stamps)
    span = (last - first).total_seconds()
    # A log written inside one second is a real thing -- CBS emits thousands
    # of records in a burst -- and its span is legitimately zero.
    width = (span / count) if span > 0 else 0.0

    totals = [0] * count
    errors = [0] * count
    for entry in entries or ():
        when = _clock(entry)
        if when is None:
            continue
        if width:
            index = int((when - first).total_seconds() / width)
            # The newest record sits exactly on the upper edge and would
            # land one past the end. It is the record someone opened the log
            # for; it belongs in the last bucket.
            index = min(index, count - 1)
        else:
            index = 0
        totals[index] += 1
        if entry.level == "Error":
            errors[index] += 1

    made = []
    for index in range(count):
        start = first + timedelta(seconds=width * index)
        end = first + timedelta(seconds=width * (index + 1)) if width else last
        made.append(Bucket(start=start, end=end,
                           total=totals[index], errors=errors[index]))
    return made
