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


@dataclass
class DiskNode:
    path: str
    name: str
    size: int           # bytes
    is_dir: bool
    file_count: int = 0
    last_modified: float = 0.0
    children: List["DiskNode"] = field(default_factory=list)
    parent: Optional["DiskNode"] = field(default=None, repr=False, compare=False)


class DiskScannerSignals(QObject):
    node_replaced = pyqtSignal(object)   # DiskNode — old stub replaced with deep-scanned version
    batch_ready = pyqtSignal(list)       # list of DiskNode — top-level stubs
    progress = pyqtSignal(int)           # node count scanned so far
    access_denied = pyqtSignal(int)      # count of folders that couldn't be entered
    finished = pyqtSignal()
    error = pyqtSignal(str)


class DiskScanner:
    """Parallel directory scanner using ThreadPoolExecutor.

    Phase 1 — fast top-level scan: emit all immediate children as stubs
    (size=0, empty children) for immediate UI display.
    Phase 2 — parallel deep scan: each top-level subdirectory is scanned
    in its own thread; completed subtrees are emitted via node_replaced.
    """

    BATCH_SIZE = 500

    def __init__(self):
        self.signals = DiskScannerSignals()
        self._cancelled = False
        self._node_count = 0
        self._lock = threading.Lock()

        # ── feature: exclude paths ──────────────────────────────────────────
        self._excluded_patterns: List[str] = []

        # ── feature: min age filter ─────────────────────────────────────────
        self._min_age_days: int = 0

        # ── feature: access denied / skipped counters ─────────────────────────
        self._access_denied_count: int = 0
        self._skipped_count: int = 0
        self._scan_errors: int = 0

        # ── feature: pause / resume ──────────────────────────────────────────
        self._paused = False
        self._pause_cond = threading.Condition()

        # ── feature: timing ──────────────────────────────────────────────────
        self._start_time: float = 0.0

    # ── public API ─────────────────────────────────────────────────────────

    def cancel(self):
        self._cancelled = True
        self._resume()

    def is_cancelled(self) -> bool:
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

    def _check_pause(self) -> None:
        with self._pause_cond:
            while self._paused and not self._cancelled:
                self._pause_cond.wait()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _increment_count(self) -> int:
        with self._lock:
            self._node_count += 1
            return self._node_count

    def _is_reparse_point(self, path: str) -> bool:
        """Return True if path is a junction, symlink, or mount point."""
        try:
            tag = os.stat(path).st_reparse_tag
            return bool(tag & _REPARSE_TAG_MASK)
        except OSError:
            return False

    def _is_excluded(self, name: str) -> bool:
        for pat in self._excluded_patterns:
            if fnmatch.fnmatch(name, pat):
                return True
        return False

    def _check_min_age(self, fstat) -> bool:
        """Return True if file is too old (should be skipped)."""
        if self._min_age_days <= 0:
            return False
        age_sec = time.time() - fstat.st_mtime
        return age_sec > self._min_age_days * 86400

    # ── scan ────────────────────────────────────────────────────────────────

    def scan(self, root_path: str) -> None:
        """Run this from a background thread."""
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

            self.signals.batch_ready.emit([root_node])
            self.signals.batch_ready.emit(list(root_node.children))

            subdirs = [c for c in root_node.children if c.is_dir]
            if subdirs and not self._cancelled:
                max_workers = min(os.cpu_count() or 4, 8)
                with ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = {
                        pool.submit(self._deep_scan_subtree, sd): sd
                        for sd in subdirs
                    }
                    for future in as_completed(futures):
                        if self._cancelled:
                            pool.shutdown(wait=False)
                            return
                        try:
                            scanned_node = future.result()
                            if scanned_node is not None:
                                self.signals.node_replaced.emit(scanned_node)
                        except Exception:
                            self._scan_errors += 1

            if not self._cancelled:
                self._emit_finished()
        except Exception as e:
            self.signals.error.emit(str(e))

    def _emit_finished(self) -> None:
        self.signals.finished.emit()

    # ── Fast top-level scan ────────────────────────────────────────────────

    def _fast_scan_root(self, root_path: str) -> DiskNode:
        try:
            stat = os.stat(root_path)
            last_mod = stat.st_mtime
        except OSError:
            last_mod = 0.0

        root = DiskNode(
            path=root_path,
            name=os.path.basename(root_path) or root_path,
            size=0,
            is_dir=True,
            last_modified=last_mod,
            parent=None,
        )

        try:
            entries = list(os.scandir(root_path))
        except PermissionError:
            self._access_denied_count += 1
            self.signals.access_denied.emit(self._access_denied_count)
            return root

        for entry in entries:
            if self._cancelled:
                break
            self._check_pause()
            try:
                is_dir = entry.is_dir(follow_symlinks=False)

                # ── feature: skip junctions / symlinks ─────────────────────
                if is_dir and self._is_reparse_point(entry.path):
                    self._skipped_count += 1
                    continue

                # ── feature: skip excluded patterns ─────────────────────────
                if self._is_excluded(entry.name):
                    self._skipped_count += 1
                    continue

                try:
                    fstat = entry.stat()
                    size = 0 if is_dir else fstat.st_size
                    mod = fstat.st_mtime
                except OSError:
                    size = 0
                    mod = 0.0

                child = DiskNode(
                    path=entry.path,
                    name=entry.name,
                    size=size,
                    is_dir=is_dir,
                    last_modified=mod,
                    parent=root,
                )
                root.children.append(child)
                self._increment_count()
            except OSError:
                continue

        return root

    # ── Deep parallel subtree scan ───────────────────────────────────────────

    def _deep_scan_subtree(self, node: DiskNode) -> Optional[DiskNode]:
        if self._cancelled:
            return None
        pending: List[DiskNode] = []

        def flush():
            if pending and not self._cancelled:
                self.signals.progress.emit(self._node_count)
                pending.clear()

        try:
            self._build_subtree(node, pending=pending, flush=flush)
            flush()
            return node
        except Exception:
            return None

    def _build_subtree(self, node: DiskNode, pending: list, flush) -> None:
        try:
            entries = list(os.scandir(node.path))
        except PermissionError:
            self._access_denied_count += 1
            self.signals.access_denied.emit(self._access_denied_count)
            return

        for entry in entries:
            if self._cancelled:
                return
            self._check_pause()
            try:
                is_dir = entry.is_dir(follow_symlinks=False)

                # ── feature: skip junctions / symlinks ─────────────────────
                if is_dir and self._is_reparse_point(entry.path):
                    self._skipped_count += 1
                    continue

                # ── feature: skip excluded patterns ─────────────────────────
                if self._is_excluded(entry.name):
                    self._skipped_count += 1
                    continue

                if is_dir:
                    child = self._build_node_recursive(
                        entry.path, parent=node, pending=pending, flush=flush,
                    )
                    node.children.append(child)
                    node.size += child.size
                    node.file_count += child.file_count
                else:
                    try:
                        fstat = entry.stat()

                        # ── feature: skip old files ─────────────────────────
                        if self._check_min_age(fstat):
                            self._skipped_count += 1
                            continue

                        size = fstat.st_size
                        mod = fstat.st_mtime
                    except OSError:
                        size = 0
                        mod = 0.0
                    child = DiskNode(
                        path=entry.path, name=entry.name,
                        size=size, is_dir=False, file_count=1,
                        last_modified=mod, parent=node,
                    )
                    node.children.append(child)
                    node.size += size
                    node.file_count += 1

                cnt = self._increment_count()
                if cnt % self.BATCH_SIZE == 0:
                    flush()
            except OSError:
                continue

    def _build_node_recursive(self, path: str, parent: Optional[DiskNode],
                               pending: list, flush) -> DiskNode:
        try:
            stat = os.stat(path)
            last_mod = stat.st_mtime
        except OSError:
            last_mod = 0.0

        node = DiskNode(
            path=path,
            name=os.path.basename(path) or path,
            size=0,
            is_dir=True,
            last_modified=last_mod,
            parent=parent,
        )

        try:
            entries = list(os.scandir(path))
        except PermissionError:
            self._access_denied_count += 1
            self.signals.access_denied.emit(self._access_denied_count)
            return node

        for entry in entries:
            if self._cancelled:
                return node
            self._check_pause()
            try:
                is_dir = entry.is_dir(follow_symlinks=False)

                # ── feature: skip junctions / symlinks ─────────────────────
                if is_dir and self._is_reparse_point(entry.path):
                    self._skipped_count += 1
                    continue

                # ── feature: skip excluded patterns ─────────────────────────
                if self._is_excluded(entry.name):
                    self._skipped_count += 1
                    continue

                if is_dir:
                    child = self._build_node_recursive(
                        entry.path, parent=node, pending=pending, flush=flush,
                    )
                    node.children.append(child)
                    node.size += child.size
                    node.file_count += child.file_count
                else:
                    try:
                        fstat = entry.stat()

                        # ── feature: skip old files ─────────────────────────
                        if self._check_min_age(fstat):
                            self._skipped_count += 1
                            continue

                        size = fstat.st_size
                        mod = fstat.st_mtime
                    except OSError:
                        size = 0
                        mod = 0.0
                    child = DiskNode(
                        path=entry.path, name=entry.name,
                        size=size, is_dir=False, file_count=1,
                        last_modified=mod, parent=node,
                    )
                    node.children.append(child)
                    node.size += size
                    node.file_count += 1

                self._increment_count()
            except OSError:
                continue

        return node
