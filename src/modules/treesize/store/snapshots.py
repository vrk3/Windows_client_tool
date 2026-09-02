"""Snapshots: saved scans tagged as system snapshots (spec 4.4, 8.3).

Same format as a saved scan, written to a per-machine location and enumerated
by the History view. The only difference is the header's `kind` and where they
live, which is deliberate: one format means one loader, one set of bugs, and a
snapshot can be opened as an ordinary scan whenever that is useful.
"""
import logging
import os
import re
import time
from dataclasses import dataclass

from .scan_file import ScanFileError, ScanHeader, load, save

logger = logging.getLogger(__name__)

SNAPSHOT_SUFFIX = ".tssnap"


def snapshot_dir() -> str:
    """Per-machine snapshot location, created on demand."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "WindowsTweaker", "treesize", "snapshots")
    os.makedirs(path, exist_ok=True)
    return path


def _slug(target: str) -> str:
    """A filesystem-safe stand-in for a scan target.

    Colons and separators cannot appear in a filename, and two different
    targets must not collapse to the same slug, so every run of unsafe
    characters becomes a single underscore rather than being dropped.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", target).strip("_")
    return cleaned[:60] or "scan"


@dataclass(frozen=True)
class SnapshotInfo:
    path: str
    target: str
    timestamp: float
    total_size: int
    node_count: int

    @property
    def when(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.timestamp))


def create(store, root: int, target: str, engine: str = "",
           bytes_per_cluster: int = 0, directory: str | None = None) -> str:
    """Write a snapshot and return its path."""
    directory = directory or snapshot_dir()
    os.makedirs(directory, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(directory, f"{_slug(target)}-{stamp}{SNAPSHOT_SUFFIX}")
    header = ScanHeader(target=target, engine=engine, kind="snapshot",
                        bytes_per_cluster=bytes_per_cluster,
                        options={"total_size": int(store.size[root])})
    save(path, store, root, header)
    return path


def enumerate_snapshots(directory: str | None = None,
                        target: str | None = None) -> list[SnapshotInfo]:
    """Snapshots on disk, newest first.

    A file that cannot be read is SKIPPED, not raised: one corrupt snapshot
    must not stop the History view showing the other nine.
    """
    directory = directory or snapshot_dir()
    if not os.path.isdir(directory):
        return []
    out = []
    for name in os.listdir(directory):
        if not name.endswith(SNAPSHOT_SUFFIX):
            continue
        path = os.path.join(directory, name)
        try:
            store, root, header = load(path)
        except (ScanFileError, OSError):
            logger.debug("enumerate_snapshots: skipping an item that could not be read", exc_info=True)
            continue
        if target and header.target.lower() != target.lower():
            continue
        out.append(SnapshotInfo(
            path=path,
            target=header.target,
            timestamp=header.timestamp,
            total_size=int(store.size[root]) if len(store) else 0,
            node_count=header.node_count,
        ))
    out.sort(key=lambda s: s.timestamp, reverse=True)
    return out


def delete(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False
