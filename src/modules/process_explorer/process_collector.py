from __future__ import annotations
import logging
from typing import Dict, List, Set, Tuple

import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.worker import Worker
from modules.process_explorer.process_node import ProcessNode

logger = logging.getLogger(__name__)

_SYSTEM_USERS = {"SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "NT AUTHORITY\\SYSTEM",
                 "NT AUTHORITY\\LOCAL SERVICE", "NT AUTHORITY\\NETWORK SERVICE"}


def build_snapshot(service_names: Set[str]) -> Dict[int, ProcessNode]:
    """Collect all processes from psutil and return a {pid: ProcessNode} dict."""
    attrs = ["pid", "name", "exe", "cmdline", "username", "status", "ppid",
             "cpu_percent", "memory_info", "io_counters"]
    result: Dict[int, ProcessNode] = {}

    for proc in psutil.process_iter(attrs):
        info = proc.info
        pid = info.get("pid") or 0
        if pid == 0:
            continue
        try:
            user = info.get("username") or ""
            mem = info.get("memory_info")
            io = info.get("io_counters")
            node = ProcessNode(
                pid=pid,
                name=info.get("name") or "",
                exe=info.get("exe") or "",
                cmdline=" ".join(info.get("cmdline") or []),
                user=user,
                status=info.get("status") or "unknown",
                parent_pid=info.get("ppid") or 0,
                cpu_percent=float(info.get("cpu_percent") or 0.0),
                memory_rss=mem.rss if mem else 0,
                memory_vms=mem.vms if mem else 0,
                disk_read_bps=float(io.read_bytes) if io else 0.0,
                disk_write_bps=float(io.write_bytes) if io else 0.0,
                is_system=user.upper().split("\\")[-1] in _SYSTEM_USERS or pid <= 8,
                is_service=(info.get("name") or "").lower() in service_names,
            )
            result[pid] = node
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Build parent→children links
    for node in result.values():
        parent = result.get(node.parent_pid)
        if parent and parent.pid != node.pid:
            parent.children.append(node)

    return result


def diff_snapshots(
    old: Dict[int, ProcessNode],
    new: Dict[int, ProcessNode],
) -> Tuple[List[int], List[int], List[int]]:
    """Return (added_pids, removed_pids, changed_pids) — all List[int]."""
    old_pids = set(old)
    new_pids = set(new)
    added   = list(new_pids - old_pids)
    removed = list(old_pids - new_pids)
    changed = [
        p for p in old_pids & new_pids
        if (old[p].cpu_percent != new[p].cpu_percent or
            old[p].memory_rss != new[p].memory_rss or
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

    def stop(self):
        self._timer.stop()

    def _tick(self):
        if self._thread_pool is None:
            return
        service_names = self._service_names

        def do_work(worker):
            return build_snapshot(service_names)

        w = Worker(do_work)
        w.signals.result.connect(self._on_snapshot)
        w.signals.error.connect(lambda e: logger.error("ProcessCollector error: %s", e))
        self._thread_pool.start(w)

    def _on_snapshot(self, new_snapshot: Dict[int, ProcessNode]):
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
