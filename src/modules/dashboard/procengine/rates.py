"""Counters into rates.

The kernel reports totals since a process started; every column Task Manager
shows as CPU%, Disk or Network is a RATE, which needs two readings and the
time between them.

This is the bug in the collector being replaced: `ProcessNode` is handed
`disk_read_bps=float(io_counters.read_bytes)`, a cumulative total wearing a
per-second name. A process that read a gigabyte an hour ago and nothing since
sits at a permanent gigabyte per second.

**An unmeasured rate is `None`, never `0.0`.** The first time a process is
seen there is no rate yet, and rendering that as zero paints an idle machine
for the first second rather than saying "not measured yet". It is the same
rule the Security Dashboard and Group Policy already follow: a value we could
not read is not a value of zero.

Qt-free, like the syscall beside it.
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

#: Kernel CPU time is counted in 100-nanosecond ticks, so this many per
#: second. Named because `10_000_000` in the middle of a division is the kind
#: of constant that gets "corrected".
HUNDRED_NS = 10_000_000


@dataclass(frozen=True, slots=True)
class Rates:
    """What a process is doing right now, or `None` where we cannot yet say."""

    cpu_percent: Optional[float] = None
    read_bps: Optional[float] = None
    write_bps: Optional[float] = None
    other_bps: Optional[float] = None


@dataclass(frozen=True, slots=True)
class _Sample:
    create_time: int
    cpu_time: int
    read_bytes: int
    write_bytes: int
    other_bytes: int
    at: float


class RateTracker:
    """Holds the previous reading so the next one can be a rate.

    One per pane. `cores` is injectable so the arithmetic can be pinned in a
    test rather than depending on the machine running it.
    """

    def __init__(self, cores: Optional[int] = None) -> None:
        self._cores = cores or os.cpu_count() or 1
        self._previous: Dict[int, _Sample] = {}

    def tracked(self) -> int:
        """How many processes are remembered. A machine that churns
        processes would otherwise grow this forever, so the test that pins
        the pruning needs to see it."""
        return len(self._previous)

    def update(self, rows: List, now: float) -> Dict[int, Rates]:
        """Rates for every process in `rows`, and forget the ones that went.

        `now` is passed in rather than read here: the caller already knows
        when it took the snapshot, and the gap that matters is the one
        between the two READINGS, not between two calls to this function.
        """
        out: Dict[int, Rates] = {}
        current: Dict[int, _Sample] = {}

        for row in rows:
            sample = _Sample(
                create_time=row.create_time,
                cpu_time=row.kernel_time + row.user_time,
                read_bytes=row.read_bytes,
                write_bytes=row.write_bytes,
                other_bytes=row.other_bytes,
                at=now,
            )
            current[row.pid] = sample
            out[row.pid] = self._rate(self._previous.get(row.pid), sample)

        # Replaced wholesale rather than updated: a pid missing from `rows`
        # is a process that ended, and keeping it would leak.
        self._previous = current
        return out

    def _rate(self, before: Optional[_Sample], after: _Sample) -> Rates:
        if before is None:
            return Rates()
        if before.create_time != after.create_time:
            # Windows reuses pids freely. Subtracting the dead process's
            # counters from its successor's yields a wild number -- usually
            # negative, occasionally a plausible-looking spike, which is
            # worse. Treat it as a process seen for the first time.
            return Rates()

        elapsed = after.at - before.at
        if elapsed <= 0:
            # Two ticks inside the clock's resolution. Windows' default timer
            # granularity is ~15.6 ms, so this is a real case, not a
            # theoretical one.
            return Rates()

        return Rates(
            cpu_percent=self._cpu(before, after, elapsed),
            read_bps=_per_second(before.read_bytes, after.read_bytes, elapsed),
            write_bps=_per_second(before.write_bytes, after.write_bytes,
                                  elapsed),
            other_bps=_per_second(before.other_bytes, after.other_bytes,
                                  elapsed),
        )

    def _cpu(self, before: _Sample, after: _Sample,
             elapsed: float) -> Optional[float]:
        used = after.cpu_time - before.cpu_time
        if used < 0:
            return None
        available = elapsed * HUNDRED_NS * self._cores
        if available <= 0:
            return None
        # Capped: timer granularity can hand back a CPU delta slightly wider
        # than the wall clock it is divided by, and "104%" in a column reads
        # as a broken tool rather than as rounding.
        return min(100.0, used / available * 100.0)


def _per_second(before: int, after: int, elapsed: float) -> Optional[float]:
    """Bytes per second, or `None` if the counter went backwards.

    Belt and braces with the create-time check: whatever the counters did, a
    rate is never reported below zero.
    """
    moved = after - before
    if moved < 0:
        return None
    return moved / elapsed
