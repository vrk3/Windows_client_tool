r"""One process, watched over time -- the properties dialog's data source.

Process Explorer's Properties window has five tabs that are all the same
question asked about one process: Performance, Performance Graph, Disk and
Network, GPU Graph, and the counters on Job. This is what feeds them.

It looks wasteful and is not. `system_processes()` returns EVERY process in
2.6 ms, so watching one process by filtering the bulk syscall costs the same
as watching all of them -- and it costs less than `psutil.Process(pid)`
reading the same fields one at a time, which was measured at 667.9 ms for
the whole machine in wave 1. There is no cheaper per-process path; the
syscall is the cheap path.

**A process can exit while its properties window is open**, which is not an
error and is the normal end of watching something. `sample()` returns `None`
from then on and `alive` goes False, so the dialog can say "this process has
exited" instead of freezing on its last reading or blanking to zeros.

**A pid can also be REUSED while the window is open**, which is worse than
exiting because the window would silently start reporting a different
program under the old one's title. The watch is pinned to
`(pid, create_time)` -- the same key the detail cache uses, for the same
reason -- and treats a changed create time as the process having gone.

Qt-free, like the rest of the engine.
"""
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from .ntquery import system_processes
from .rates import RateTracker

logger = logging.getLogger(__name__)

#: Samples kept for the graphs. 60 at one a second is the window Task
#: Manager and Process Explorer both show.
HISTORY = 60


@dataclass(frozen=True, slots=True)
class ProcessSample:
    """One reading of one process."""

    pid: int
    at: float
    raw: object
    cpu_percent: Optional[float] = None
    read_bps: Optional[float] = None
    write_bps: Optional[float] = None
    other_bps: Optional[float] = None
    gpu_percent: Optional[float] = None
    gpu_dedicated: Optional[int] = None
    gpu_shared: Optional[int] = None

    @property
    def io_total_bps(self) -> Optional[float]:
        """Read + write + other, or `None` if any part is unmeasured.

        Not a sum treating gaps as zero: that reports a total smaller than
        the real traffic while looking like a reading.
        """
        parts = (self.read_bps, self.write_bps, self.other_bps)
        if any(part is None for part in parts):
            return None
        return sum(parts)


@dataclass
class Series:
    """A bounded history of one figure, `None` for the gaps.

    A gap is kept as `None` rather than dropped or zeroed: the graphs draw
    it as a break, which is the honest picture of a tick where there was no
    rate yet.
    """

    values: Deque[Optional[float]] = field(
        default_factory=lambda: deque(maxlen=HISTORY))

    def push(self, value: Optional[float]) -> None:
        self.values.append(value)

    def as_list(self) -> List[Optional[float]]:
        return list(self.values)

    def peak(self) -> Optional[float]:
        seen = [value for value in self.values if value is not None]
        return max(seen) if seen else None


class ProcessWatch:
    """Follows one process until it exits.

    Holds a `RateTracker`, because a rate needs the previous sample, and a
    short history for the graphs.
    """

    def __init__(self, pid: int, cores: Optional[int] = None,
                 gpu=None) -> None:
        self.pid = pid
        self._rates = RateTracker(cores=cores)
        self._gpu = gpu
        #: Pinned on the first successful sample. A different create time
        #: later means the pid was reused and this is a different program.
        self._create_time: Optional[int] = None
        self._alive = True
        self._exited_because: Optional[str] = None
        self.latest: Optional[ProcessSample] = None
        self.cpu = Series()
        self.io = Series()
        self.gpu = Series()
        self.private_bytes = Series()

    @property
    def alive(self) -> bool:
        return self._alive

    @property
    def exited_because(self) -> Optional[str]:
        """Why watching stopped -- exited, or the pid was reused."""
        return self._exited_because

    def sample(self, rows=None, now: Optional[float] = None
               ) -> Optional[ProcessSample]:
        """One reading, or `None` once the process is gone.

        `rows` lets a caller that already has a full `system_processes()`
        reading share it rather than paying for a second one -- which is
        what the pane does when several properties windows are open.
        """
        if not self._alive:
            return None
        import time as _time

        now = _time.monotonic() if now is None else now
        rows = system_processes() if rows is None else rows

        found = None
        for row in rows:
            if row.pid == self.pid:
                found = row
                break
        if found is None:
            return self._stop("the process has exited")
        if self._create_time is None:
            self._create_time = found.create_time
        elif found.create_time != self._create_time:
            # Not the process we were watching. Reporting its figures under
            # the old one's title is the failure this check exists to stop.
            return self._stop("the process has exited and its pid was reused")

        rates = self._rates.update([found], now=now).get(found.pid)
        gpu_percent = gpu_dedicated = gpu_shared = None
        if self._gpu is not None:
            gpu_percent = self._gpu.process_usage().get(self.pid)
            memory = self._gpu.process_memory().get(self.pid)
            if memory is not None:
                gpu_dedicated, gpu_shared = memory

        sample = ProcessSample(
            pid=self.pid, at=now, raw=found,
            cpu_percent=getattr(rates, "cpu_percent", None),
            read_bps=getattr(rates, "read_bps", None),
            write_bps=getattr(rates, "write_bps", None),
            other_bps=getattr(rates, "other_bps", None),
            gpu_percent=gpu_percent,
            gpu_dedicated=gpu_dedicated,
            gpu_shared=gpu_shared)

        self.latest = sample
        self.cpu.push(sample.cpu_percent)
        self.io.push(sample.io_total_bps)
        self.gpu.push(sample.gpu_percent)
        self.private_bytes.push(float(getattr(found, "private_bytes", 0) or 0))
        return sample

    def _stop(self, why: str) -> None:
        self._alive = False
        self._exited_because = why
        return None
