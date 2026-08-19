"""Engine selection and scan orchestration.

Picks the MFT fast path when the target is a whole NTFS volume and the process
is elevated, and falls back to the directory walk otherwise. ``get_volume_info``
returning None is the normal fallback signal, not an error.

Both engines honour filters, by different routes. The walk engine drops entries
before they reach the store. The MFT engine cannot -- records stream in MFT
order with no parent/child ordering, so dropping a directory at feed time would
orphan its children rather than remove them -- so it filters with a prune pass
over the assembled tree instead. See prune.py.
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
from .prune import prune_excluded
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
    # False when the scan could not read everything it was asked to: a failed
    # volume read, or a directory it was denied. The totals are then a LOWER
    # BOUND, not a measurement, and no caller should present them as final.
    complete: bool = True
    errors: tuple[tuple[str, str], ...] = ()
    error_count: int = 0
    # Number of $MFT extents followed. >1 means the table was fragmented and
    # the run list was needed; 1 means contiguous, or a fallback to one span.
    mft_extents: int = 0


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
            if info is None:
                # select_engine() probed the volume a moment ago and it
                # answered; it no longer does. Removable media, a dismount, a
                # transient failure. Walking is a worse plan than the MFT but a
                # far better one than crashing on info.bytes_per_record.
                engine = "walk"
        if engine == "mft":
            scanner = MftScanner(letter, info,
                                 charge_all_hardlinks=self.charge_all_hardlinks)
            scanner.scan(store, on_batch=on_batch, should_cancel=should_cancel,
                         wait_if_paused=self._wait_if_paused)
            root = scanner.builder.root
            # The MFT engine cannot drop entries as it meets them, so filtering
            # is a prune pass over the assembled tree. See prune.py.
            prune_excluded(store, root, self.filters)
            mft_extents = len(scanner.extents)
            complete = not scanner.truncated
            errors: tuple[tuple[str, str], ...] = ()
            error_count = 0
            if scanner.truncated:
                errors = ((f"{letter}:", "MFT read failed before the end of the table"),)
                error_count = 1
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
            mft_extents = 0
            complete = scanner.error_count == 0
            errors = tuple(scanner.errors)
            error_count = scanner.error_count
        rollup(store)
        return ScanResult(store=store, root=root, engine=engine,
                          node_count=len(store), excluded=self.filters.excluded_count,
                          volume_info=info, elapsed=time.monotonic() - started,
                          complete=complete, errors=errors, error_count=error_count,
                          mft_extents=mft_extents)
