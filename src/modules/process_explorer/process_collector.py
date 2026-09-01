"""The Process Explorer tab's snapshot, on the Dashboard's process engine.

It used to call `psutil.process_iter` with ten attributes, which the wave-1
benchmark measured at **667.9 ms** for this machine's ~270 processes against
**2.6 ms** for `NtQuerySystemInformation` -- a 257x gap that showed up in the
UI as a tab which sat empty for about five seconds after you clicked it, and
then burned two thirds of a core to stay current at 1 Hz.

The engine in `modules/dashboard/procengine/` already had everything this
pane needs, so this is now a translation layer rather than a second
collector: `SnapshotSource` reads, and each `ProcessInfo` becomes the
`ProcessNode` that `ProcessTreeModel` and the lower panes already expect.
That also fills in the GPU column, which had shown 0.0 for every process
since it was added because nothing ever wrote to it.

Two things are deliberately kept from the old behaviour: the shape of
`ProcessNode` (the tree model, the colour scheme, the properties dialog and
seven lower panes all read it) and the `{pid: node}` snapshot contract.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional, Set, Tuple

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.worker import Worker
from modules.process_explorer.process_node import ProcessNode

logger = logging.getLogger(__name__)

#: Session 0 is the non-interactive session Windows reserves for services.
#: Used to classify system processes because it arrives free with the bulk
#: syscall and CANNOT be refused -- the wave-1 finding that unelevated, the
#: token classifies zero system processes by user name, so the "Windows
#: processes" group came out empty.
SERVICES_SESSION = 0


def node_from_info(info, service_names: Set[str],
                   gpu: Optional[Dict[int, float]] = None) -> ProcessNode:
    """One engine `ProcessInfo` as the `ProcessNode` the pane speaks.

    The engine reports `None` for anything it could not read, which is the
    distinction the whole thing is built on. `ProcessNode` predates that and
    has non-optional fields, so the conversion has to choose -- and it
    chooses the empty string for text and 0.0 for rates, NOT to claim a
    measurement but because the widgets downstream cannot render a `None`.
    The unfilled cell is the honest rendering of "we were refused"; what
    must never happen is a refusal arriving as a plausible NUMBER, and no
    refusal here produces one.
    """
    raw, rates, details = info.raw, info.rates, info.details
    return ProcessNode(
        pid=raw.pid,
        name=raw.name or "",
        exe=details.path or "",
        cmdline=details.cmdline or "",
        user=details.user or "",
        status="suspended" if _suspended(raw) else "running",
        parent_pid=raw.ppid or 0,
        cpu_percent=rates.cpu_percent or 0.0,
        memory_rss=raw.working_set or 0,
        memory_vms=raw.virtual_size or 0,
        disk_read_bps=rates.read_bps or 0.0,
        disk_write_bps=rates.write_bps or 0.0,
        gpu_percent=(gpu or {}).get(raw.pid, 0.0),
        is_system=raw.session == SERVICES_SESSION,
        is_service=info.is_service or (raw.name or "").lower() in service_names,
        is_suspended=_suspended(raw),
        integrity_level=details.integrity or "Medium",
    )


def _suspended(raw) -> bool:
    """A process with threads but no cycles is not merely idle.

    The engine's own snapshot marks this the same way; kept here rather than
    imported so the translation has one source of truth for the field.
    """
    return bool(getattr(raw, "threads", 0)) and getattr(raw, "cycles", 1) == 0


#: How many processes may have their cold details resolved per tick.
#: Elevated, a full cold sweep of this machine's ~270 processes measures
#: 2,252 ms, so an unbounded first tick leaves the pane blank for over two
#: seconds. At 60 a tick the list appears immediately with names, rates and
#: memory, and the paths and users fill in over the next four seconds --
#: which is what the two-tier design was for. Warm ticks cost 8.5 ms and
#: never come near the cap.
COLD_BUDGET_PER_TICK = 60


def build_snapshot(service_names: Set[str],
                   source=None,
                   gpu: Optional[Dict[int, float]] = None,
                   cold_budget: Optional[int] = COLD_BUDGET_PER_TICK
                   ) -> Dict[int, ProcessNode]:
    """Every process as a `{pid: ProcessNode}` map, children linked.

    `source` is the caller's `SnapshotSource`, which must persist between
    ticks: it holds the previous sample (without which there is no rate at
    all) and the cold cache (without which every tick re-resolves 270
    paths). Passing `None` builds a throwaway one, which is correct only
    for a single reading -- every rate will be 0.0.
    """
    from modules.dashboard.procengine.snapshot import SnapshotSource

    if source is None:
        source = SnapshotSource()
    snapshot = source.read(cold_budget=cold_budget)

    result: Dict[int, ProcessNode] = {}
    for pid, info in snapshot.by_pid.items():
        if pid == 0:
            continue
        result[pid] = node_from_info(info, service_names, gpu)

    # Parent -> children, over the pids that are actually present. The
    # engine's own tree has already broken any ppid cycle (pid reuse makes
    # them, and a cycle wearing the shape of a tree never stops being
    # walked), so this only has to re-hang the same links on these nodes.
    for node in result.values():
        parent = result.get(node.parent_pid)
        if parent is not None and parent.pid != node.pid:
            parent.children.append(node)

    return result


def diff_snapshots(
    old: Dict[int, ProcessNode],
    new: Dict[int, ProcessNode],
) -> Tuple[List[int], List[int], List[int]]:
    """Return (added_pids, removed_pids, changed_pids) — all List[int].

    GPU and the disk rates are part of "changed" as well as CPU and memory.
    They were not, which was harmless while nothing wrote to them and is
    not now: a row whose ONLY movement is on the GPU would never be
    repainted, so the column would sit at whatever it read the tick some
    other number happened to change.
    """
    old_pids = set(old)
    new_pids = set(new)
    added   = list(new_pids - old_pids)
    removed = list(old_pids - new_pids)
    changed = [
        p for p in old_pids & new_pids
        if (old[p].cpu_percent != new[p].cpu_percent or
            old[p].memory_rss != new[p].memory_rss or
            old[p].gpu_percent != new[p].gpu_percent or
            old[p].disk_read_bps != new[p].disk_read_bps or
            old[p].disk_write_bps != new[p].disk_write_bps or
            old[p].status != new[p].status)
    ]
    return added, removed, changed


class ProcessCollector(QObject):
    """Polls process list on a background Worker, diffs, and emits signals."""
    process_added     = pyqtSignal(object)   # emits ProcessNode
    process_removed   = pyqtSignal(int)      # emits pid
    processes_updated = pyqtSignal(list)     # emits List[int] changed pids
    snapshot_ready    = pyqtSignal(dict)     # emits full {pid: ProcessNode} on first load

    def __init__(self, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._snapshot: Dict[int, ProcessNode] = {}
        self._service_names: Set[str] = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._thread_pool = None
        self._first = True
        self._busy = False
        #: Both of these MUST live across ticks, and for the same reason:
        #: they hold the previous reading. A fresh SnapshotSource has no
        #: rates and an empty cold cache (141 ms of re-resolution); a fresh
        #: GpuSampler has no interval, so PDH refuses its first read. Built
        #: lazily on the worker thread, because constructing them opens
        #: handles and a PDH query that a never-started collector should
        #: not be holding.
        self._source = None
        self._gpu = None

    def set_thread_pool(self, pool):
        self._thread_pool = pool

    def set_service_names(self, names: Set[str]):
        self._service_names = {n.lower() for n in names}

    def set_interval(self, ms: int):
        self._interval_ms = ms
        if self._timer.isActive():
            self._timer.setInterval(ms)

    def start(self):
        self._timer.start(self._interval_ms)
        # And read once NOW. A QTimer does not fire until its first interval
        # has elapsed, so starting it alone bought a guaranteed second of
        # empty table on the tick someone clicked the tab -- a full second
        # of the ~3.5 that made this pane feel broken.
        self._tick()

    def stop(self):
        self._timer.stop()
        self._close_gpu()

    def _close_gpu(self) -> None:
        """Release the PDH query. It lives in the performance-counter
        service rather than in this process, so an abandoned one outlives
        the pane that opened it."""
        if self._gpu is not None:
            self._gpu.close()
            self._gpu = None

    def _tick(self):
        if self._thread_pool is None or self._busy:
            return
        self._busy = True
        service_names = self._service_names

        def do_work(worker):
            if self._source is None:
                from modules.dashboard.procengine.snapshot import \
                    SnapshotSource
                self._source = SnapshotSource()
            if self._gpu is None:
                from modules.dashboard.procengine.gpuinfo import GpuSampler
                self._gpu = GpuSampler()
            # Collect once, then read the per-pid slice of that same
            # collection: sampling twice would halve each interval and
            # report GPU figures for a window that does not line up with
            # the CPU and disk rates on the same row.
            self._gpu.sample()
            gpu = self._gpu.process_usage()
            return build_snapshot(service_names, source=self._source, gpu=gpu)

        def _on_error(e: str) -> None:
            logger.error("ProcessCollector error: %s", e)
            self._busy = False

        w = Worker(do_work)
        w.signals.result.connect(self._on_snapshot)
        w.signals.error.connect(_on_error)
        self._thread_pool.start(w)

    def _on_snapshot(self, new_snapshot: Dict[int, ProcessNode]):
        self._busy = False
        if self._first:
            self._snapshot = new_snapshot
            self._first = False
            self.snapshot_ready.emit(new_snapshot)
            return
        added, removed, changed = diff_snapshots(self._snapshot, new_snapshot)
        self._snapshot = new_snapshot
        for pid in added:
            node = new_snapshot.get(pid)
            if node:
                self.process_added.emit(node)
        for pid in removed:
            self.process_removed.emit(pid)
        if changed:
            self.processes_updated.emit(changed)

    def get_snapshot(self) -> Dict[int, ProcessNode]:
        return self._snapshot
