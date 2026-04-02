import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Optional
from PyQt6.QtCore import QObject, pyqtSignal


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
    # Fully-scanned top-level nodes (for replacing stubs in the model)
    node_replaced = pyqtSignal(object)   # DiskNode — old stub is replaced with this
    # Legacy: initial batch of top-level items (no deep scan yet)
    batch_ready = pyqtSignal(list)       # list of DiskNode
    # Progress counter
    progress = pyqtSignal(int)           # node count scanned so far
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

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _increment_count(self) -> int:
        with self._lock:
            self._node_count += 1
            return self._node_count

    def scan(self, root_path: str) -> None:
        """Run this from a background thread."""
        self._cancelled = False
        self._node_count = 0

        try:
            # ── Phase 1: fast top-level scan (no deep recursion) ──────────────
            root_node = self._fast_scan_root(root_path)
            if self._cancelled:
                return

            # Emit root node itself so the tree has a top anchor
            self.signals.batch_ready.emit([root_node])

            # Emit immediate children as stubs immediately
            self.signals.batch_ready.emit(list(root_node.children))

            # ── Phase 2: parallel deep scan of each subdirectory ───────────────
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
                        except Exception as e:
                            # Non-fatal: keep going with other subtrees
                            pass

            if not self._cancelled:
                self.signals.finished.emit()

        except Exception as e:
            self.signals.error.emit(str(e))

    # ── Fast top-level scan ────────────────────────────────────────────────

    def _fast_scan_root(self, root_path: str) -> DiskNode:
        """Scan only the root's immediate children — no recursion."""
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
            return root

        for entry in entries:
            if self._cancelled:
                break
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
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
        """Recursively scan a subtree. Called in a thread pool worker."""
        if self._cancelled:
            return None

        pending: List[DiskNode] = []
        count = self._node_count  # snapshot before this subtree

        def flush():
            nonlocal count
            if pending and not self._cancelled:
                # Emit progress batch (used for progress counter only)
                self.signals.progress.emit(self._node_count)
                pending.clear()

        try:
            self._build_subtree(node, pending=pending, flush=flush)
            flush()
            return node
        except Exception:
            return None

    def _build_subtree(self, node: DiskNode, pending: list, flush) -> None:
        """Recursively build node.children with full sizes."""
        try:
            entries = list(os.scandir(node.path))
        except PermissionError:
            return

        for entry in entries:
            if self._cancelled:
                return
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                if is_dir:
                    child = self._build_node_recursive(entry.path, parent=node,
                                                       pending=pending, flush=flush)
                    node.children.append(child)
                    node.size += child.size
                    node.file_count += child.file_count
                else:
                    try:
                        fstat = entry.stat()
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
        """Build a single dir node and recurse into its children."""
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
            return node

        for entry in entries:
            if self._cancelled:
                return node
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                if is_dir:
                    child = self._build_node_recursive(entry.path, parent=node,
                                                       pending=pending, flush=flush)
                    node.children.append(child)
                    node.size += child.size
                    node.file_count += child.file_count
                else:
                    try:
                        fstat = entry.stat()
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
