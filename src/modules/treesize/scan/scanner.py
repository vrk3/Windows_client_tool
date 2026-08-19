"""Engine selection and scan orchestration.

Picks the MFT fast path when the target is a whole NTFS volume and the process
is elevated, and falls back to the directory walk otherwise. ``get_volume_info``
returning None is the normal fallback signal, not an error.

Filters are applied by the walk engine, which drops entries before they reach
the store. The MFT engine does not filter: records stream in MFT order with no
parent/child ordering, so an entry cannot be dropped at feed time without
orphaning its subtree. Filtering there needs a prune pass after tree assembly
and is deferred; ``ScanResult.excluded`` is 0 on the MFT path.
"""
import ctypes
import os
import threading
import time
from dataclasses import dataclass

from ..store.node_store import NodeStore
from ..store.rollup import rollup
from .filters import FilterSet
from .mft_reader import MftScanner
from .volume_info import VolumeInfo, get_volume_info
from .walk_scanner import WalkScanner

DEFAULT_CLUSTER_BYTES = 4096


@dataclass
class ScanResult:
    store: NodeStore
    root: int
    engine: str
    node_count: int
    excluded: int
    volume_info: VolumeInfo | None
    elapsed: float


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _drive_letter(target: str) -> str | None:
    """Return the drive letter if target names a whole drive, else None."""
    stripped = target.rstrip("\\/")
    if len(stripped) == 2 and stripped[1] == ":" and stripped[0].isalpha():
        return stripped[0]
    return None


class Scanner:
    def __init__(self, target: str, filters: FilterSet | None = None,
                 charge_all_hardlinks: bool = False) -> None:
        self.target = target
        self.filters = filters or FilterSet()
        self.charge_all_hardlinks = charge_all_hardlinks
        self._resume = threading.Event()
        self._resume.set()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def _wait_if_paused(self) -> None:
        self._resume.wait()

    def select_engine(self) -> str:
        letter = _drive_letter(self.target)
        if letter and _is_admin() and get_volume_info(letter) is not None:
            return "mft"
        return "walk"

    def scan(self, on_batch=None, should_cancel=None) -> ScanResult:
        started = time.monotonic()
        # A Scanner is reusable, so every run starts from a clean store and a
        # zeroed tally rather than accumulating across scans.
        self.filters.reset()
        store = NodeStore()
        engine = self.select_engine()
        info = None
        if engine == "mft":
            letter = _drive_letter(self.target)
            info = get_volume_info(letter)
            scanner = MftScanner(letter, info,
                                 charge_all_hardlinks=self.charge_all_hardlinks)
            scanner.scan(store, on_batch=on_batch, should_cancel=should_cancel,
                         wait_if_paused=self._wait_if_paused)
            root = scanner.builder.root
        else:
            cluster = DEFAULT_CLUSTER_BYTES
            letter = _drive_letter(self.target) or os.path.splitdrive(self.target)[0][:1]
            if letter:
                probe = get_volume_info(letter)
                if probe:
                    cluster = probe.bytes_per_cluster
                    info = probe
            scanner = WalkScanner(self.target, bytes_per_cluster=cluster,
                                  exclude=self.filters.excludes)
            scanner.scan(store, on_batch=on_batch, should_cancel=should_cancel,
                         wait_if_paused=self._wait_if_paused)
            root = scanner.root
        rollup(store)
        return ScanResult(store=store, root=root, engine=engine,
                          node_count=len(store), excluded=self.filters.excluded_count,
                          volume_info=info, elapsed=time.monotonic() - started)
