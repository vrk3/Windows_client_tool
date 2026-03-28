import os
import threading
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
    batch_ready = pyqtSignal(list)   # list of DiskNode (direct children of scanned root)
    progress = pyqtSignal(int)       # node count scanned so far
    finished = pyqtSignal()
    error = pyqtSignal(str)


class DiskScanner:
    """Scans a directory tree, emitting batches of top-level children every BATCH_SIZE nodes."""

    BATCH_SIZE = 500

    def __init__(self):
        self.signals = DiskScannerSignals()
        self._cancelled = False
        self._node_count = 0

    def cancel(self):
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    def scan(self, root_path: str) -> None:
        """Run this from a background thread. Emits batch_ready / finished / error."""
        self._cancelled = False
        self._node_count = 0
        pending: List[DiskNode] = []

        def flush():
            if pending:
                self.signals.batch_ready.emit(list(pending))
                self.signals.progress.emit(self._node_count)
                pending.clear()

        try:
            root_node = self._build_node(root_path, parent=None, pending=pending, flush=flush)
            flush()
            if not self._cancelled:
                # Emit the root itself so model can display it
                self.signals.batch_ready.emit([root_node])
                self.signals.finished.emit()
        except Exception as e:
            self.signals.error.emit(str(e))

    def _build_node(self, path: str, parent: Optional[DiskNode],
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
            return node

        for entry in entries:
            if self._cancelled:
                return node
            try:
                if entry.is_dir(follow_symlinks=False):
                    child = self._build_node(entry.path, parent=node,
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

                self._node_count += 1
                if self._node_count % self.BATCH_SIZE == 0:
                    flush()
            except OSError:
                continue

        return node
