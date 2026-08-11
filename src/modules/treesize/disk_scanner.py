import fnmatch
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional
from PyQt6.QtCore import QObject, pyqtSignal

# Windows reparse tag mask — anything with this bit set is a reparse point
# (junction, symlink, mount point, etc.)
_REPARSE_TAG_MASK = 0x80000000

# Sentinel value for directories whose size is still unknown (not yet loaded)
SIZE_UNKNOWN = -1


@dataclass
class DiskNode:
    path: str
    name: str
    size: int           # bytes; SIZE_UNKNOWN (-1) means "not yet scanned"
    is_dir: bool
    file_count: int = 0
    last_modified: float = 0.0
    children: List["DiskNode"] = field(default_factory=list)
    parent: Optional["DiskNode"] = field(default=None, repr=False, compare=False)
    _fully_loaded: bool = False  # True once children have been populated


class DiskScannerSignals(QObject):
    batch_ready = pyqtSignal(list)       # list of DiskNode — top-level stubs
    children_ready = pyqtSignal(str, list)  # (parent_path, list of child DiskNode)
    progress = pyqtSignal(int)           # node count scanned so far
    access_denied = pyqtSignal(int)      # count of folders that couldn't be entered
    finished = pyqtSignal()
    error = pyqtSignal(str)


class DiskScanner:
    """Two-phase directory scanner with lazy deep-loading support.

    Phase 1 — fast top-level scan: emit the root + all immediate children
    as stubs (directories have SIZE_UNKNOWN and empty children) for
    immediate UI display.

    Phase 2 — on-demand shallow scan: when the user expands a directory
    stub, call scan_shallow() to populate its children on a background
    thread.

    The eager deep-scan (old Phase 2) is removed — it froze the UI when
    scanning large drives like C:\\ because ThreadPoolExecutor workers
    would recursively descend into every subdirectory (Windows, Users,
    Program Files, etc.) synchronously.
    """

    BATCH_SIZE = 500

    def __init__(self):
        self.signals = DiskScannerSignals()
        self._cancelled = False
        self._node_count = 0
        self._lock = threading.Lock()

        self._excluded_patterns: List[str] = []
        self._min_age_days: int = 0

        self._access_denied_count: int = 0
        self._skipped_count: int = 0
        self._scan_errors: int = 0

        self._paused = False
        self._pause_cond = threading.Condition()

        self._start_time: float = 0.0

    # ── public API ─────────────────────────────────────────────────────────

    def cancel(self):
        with self._lock:
            self._cancelled = True
        self._resume()

    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def set_excluded_patterns(self, patterns: List[str]) -> None:
        self._excluded_patterns = list(patterns)

    def set_min_age_days(self, days: int) -> None:
        self._min_age_days = max(0, days)

    def get_stats(self) -> dict:
        return {
            "nodes": self._node_count,
            "errors": self._scan_errors,
            "skipped": self._skipped_count,
            "access_denied": self._access_denied_count,
        }

    # ── pause / resume ──────────────────────────────────────────────────────

    def pause(self) -> None:
        with self._pause_cond:
            self._paused = True

    def resume(self) -> None:
        with self._pause_cond:
            self._paused = False
            self._pause_cond.notify_all()

    def _resume(self) -> None:
        """Wake paused threads without clearing the paused flag (used by cancel)."""
        with self._pause_cond:
            self._pause_cond.notify_all()

    def _check_pause(self) -> None:
        with self._pause_cond:
            while self._paused and not self._cancelled:
                self._pause_cond.wait()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _increment_count(self) -> int:
        with self._lock:
            self._node_count += 1
            return self._node_count

    def _increment_skipped(self) -> None:
        with self._lock:
            self._skipped_count += 1

    def _increment_access_denied(self) -> int:
        with self._lock:
            self._access_denied_count += 1
            return self._access_denied_count

    def _is_reparse_point(self, fstat) -> bool:
        """Check st_reparse_tag from a stat_result (avoid extra os.stat call)."""
        try:
            tag = fstat.st_reparse_tag
            return bool(tag & _REPARSE_TAG_MASK)
        except AttributeError:
            return False

    def _is_excluded(self, name: str) -> bool:
        for pat in self._excluded_patterns:
            if fnmatch.fnmatch(name, pat):
                return True
        return False

    def _check_min_age(self, fstat) -> bool:
        if self._min_age_days <= 0:
            return False
        age_sec = time.time() - fstat.st_mtime
        return age_sec > self._min_age_days * 86400

    # ── Phase 1: fast top-level scan ────────────────────────────────────────

    def scan(self, root_path: str) -> None:
        """Run this from a background thread.

        Scans only the immediate children of root_path (Phase 1).
        No recursive deep scan — child directories are left as stubs
        (SIZE_UNKNOWN, no children) to be expanded on demand.
        """
        self._cancelled = False
        self._node_count = 0
        self._access_denied_count = 0
        self._skipped_count = 0
        self._scan_errors = 0
        self._start_time = time.time()

        try:
            root_node = self._fast_scan_root(root_path)
            if self._cancelled:
                return

            # Emit root only — children are already in root.children.
            # Do NOT emit children as separate batch_ready items;
            # that would add them as duplicate top-level _roots entries,
            # breaking the tree hierarchy and freezing QTreeView.
            self.signals.batch_ready.emit([root_node])

            if not self._cancelled:
                self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(str(e))

    # ── Phase 2: on-demand shallow scan of a single directory ───────────────

    def scan_shallow(self, parent_path: str) -> None:
        """Run from a background thread.

        Scans ONE directory level deep (immediate children only).
        Returns children via signals.children_ready(parent_path, children).
        If children themselves are directories, they stay as stubs
        (SIZE_UNKNOWN, no children) for further on-demand expansion.
        """
        if self._cancelled:
            return

        children: List[DiskNode] = []
        dir_size = 0
        dir_files = 0

        try:
            entries = list(os.scandir(parent_path))
        except PermissionError:
            cnt = self._increment_access_denied()
            self.signals.access_denied.emit(cnt)
            self.signals.children_ready.emit(parent_path, children)
            return
        except OSError:
            self.signals.children_ready.emit(parent_path, children)
            return

        for entry in entries:
            if self._cancelled:
                return
            self._check_pause()

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            try:
                fstat = entry.stat()
            except OSError:
                continue

            # Skip reparse points (junctions, symlinks, mount points)
            if is_dir and self._is_reparse_point(fstat):
                self._increment_skipped()
                continue

            # Skip excluded patterns
            if self._is_excluded(entry.name):
                self._increment_skipped()
                continue

            if is_dir:
                # Directory stub — SIZE_UNKNOWN means "not yet loaded"
                child = DiskNode(
                    path=entry.path,
                    name=entry.name,
                    size=SIZE_UNKNOWN,
                    is_dir=True,
                    last_modified=fstat.st_mtime,
                    parent=None,  # parent set by model
                )
            else:
                # Skip old files
                if self._check_min_age(fstat):
                    self._increment_skipped()
                    continue
                child = DiskNode(
                    path=entry.path,
                    name=entry.name,
                    size=fstat.st_size,
                    is_dir=False,
                    file_count=1,
                    last_modified=fstat.st_mtime,
                    parent=None,
                )
                dir_size += child.size
                dir_files += 1

            children.append(child)
            cnt = self._increment_count()
            if cnt % self.BATCH_SIZE == 0:
                self.signals.progress.emit(cnt)

        self.signals.children_ready.emit(parent_path, children)

    def _fast_scan_root(self, root_path: str) -> DiskNode:
        """Phase 1: fast scan of immediate children of the target directory."""
        try:
            st = os.stat(root_path)
            last_mod = st.st_mtime
        except OSError:
            last_mod = 0.0

        root = DiskNode(
            path=root_path,
            name=os.path.basename(root_path) or root_path,
            size=0,
            is_dir=True,
            last_modified=last_mod,
            parent=None,
            _fully_loaded=True,
        )

        try:
            entries = list(os.scandir(root_path))
        except PermissionError:
            cnt = self._increment_access_denied()
            self.signals.access_denied.emit(cnt)
            return root
        except OSError:
            return root

        dir_size = 0
        dir_files = 0

        for entry in entries:
            if self._cancelled:
                break
            self._check_pause()

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue

            try:
                fstat = entry.stat()
            except OSError:
                continue

            # Skip reparse points
            if is_dir and self._is_reparse_point(fstat):
                self._increment_skipped()
                continue

            # Skip excluded patterns
            if self._is_excluded(entry.name):
                self._increment_skipped()
                continue

            if is_dir:
                # Directory stub — SIZE_UNKNOWN means "not yet loaded"
                child = DiskNode(
                    path=entry.path,
                    name=entry.name,
                    size=SIZE_UNKNOWN,
                    is_dir=True,
                    last_modified=fstat.st_mtime,
                    parent=root,
                )
            else:
                # Skip old files
                if self._check_min_age(fstat):
                    self._increment_skipped()
                    continue
                child = DiskNode(
                    path=entry.path,
                    name=entry.name,
                    size=fstat.st_size,
                    is_dir=False,
                    file_count=1,
                    last_modified=fstat.st_mtime,
                    parent=root,
                )
                dir_size += child.size
                dir_files += 1

            root.children.append(child)
            self._increment_count()

        root.size = dir_size
        root.file_count = dir_files
        return root
