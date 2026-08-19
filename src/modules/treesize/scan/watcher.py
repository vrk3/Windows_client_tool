"""Live updates: "Watch for file system changes" (spec 3.5).

`ReadDirectoryChangesW` on the scanned root, on a dedicated thread. Change
records are coalesced over a window and applied to the store as size deltas
propagated up the parent chain, rather than by rescanning — a rescan of a
five-million-node volume to learn that one log file grew is not an update, it
is a restart.

Off by default and per scan, because it holds a handle on the volume root.

The change source is injectable, so the coalescing and the delta arithmetic —
which is where the bugs live — are testable without a filesystem, a thread, or
a volume handle.
"""
import ctypes
import logging
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from ..store.node_store import DIR, EXCLUDED

logger = logging.getLogger(__name__)

FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

FILE_NOTIFY_CHANGE_FILE_NAME = 0x00000001
FILE_NOTIFY_CHANGE_DIR_NAME = 0x00000002
FILE_NOTIFY_CHANGE_SIZE = 0x00000008
FILE_NOTIFY_CHANGE_LAST_WRITE = 0x00000010
WATCH_FLAGS = (FILE_NOTIFY_CHANGE_FILE_NAME | FILE_NOTIFY_CHANGE_DIR_NAME
               | FILE_NOTIFY_CHANGE_SIZE | FILE_NOTIFY_CHANGE_LAST_WRITE)

FILE_ACTION_ADDED = 1
FILE_ACTION_REMOVED = 2
FILE_ACTION_MODIFIED = 3
FILE_ACTION_RENAMED_OLD_NAME = 4
FILE_ACTION_RENAMED_NEW_NAME = 5

#: Spec 3.5. Long enough that a build or an unzip lands as one update rather
#: than ten thousand, short enough to feel live.
COALESCE_SECONDS = 0.5
BUFFER_BYTES = 64 * 1024

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


@dataclass(frozen=True)
class Change:
    """One coalesced change: a path, and what it now weighs."""
    path: str
    action: int


def find_node(store, root: int, path: str) -> int:
    """The node for an absolute path, or -1.

    Walks down from the root by name. The store has no path index -- building
    one for half a million nodes to serve a handful of changes a second would
    cost far more than the walk does.
    """
    if store is None or root < 0:
        return -1
    root_path = store.name(root).rstrip("\\/")
    if not path.lower().startswith(root_path.lower()):
        return -1
    remainder = path[len(root_path):].strip("\\/")
    node = root
    if not remainder:
        return node
    for part in remainder.split("\\"):
        wanted = part.lower()
        for child in store.children(node):
            if store.name(child).lower() == wanted:
                node = child
                break
        else:
            return -1
    return node


def apply_change(store, root: int, path: str) -> int:
    """Re-stat one path and push the difference up its parent chain.

    Returns the byte delta applied. Only the chain from the node to the root
    is touched, which is what makes an update O(depth) rather than O(volume).
    """
    node = find_node(store, root, path)
    if node < 0:
        return 0
    try:
        new_size = 0 if store.attrs[node] & DIR else os.path.getsize(path)
    except OSError:
        # Gone between the notification and the stat. Treat as zero: the
        # delta then removes exactly what the store thought was there.
        new_size = 0
    delta = new_size - store.size[node]
    if delta == 0:
        return 0
    walker = node
    seen = set()
    while 0 <= walker < len(store) and walker not in seen:
        seen.add(walker)
        store.size[walker] += delta
        if walker == root:
            break
        walker = store.parent[walker]
    return delta


class Watcher:
    """Watches a directory tree and reports coalesced changes.

    `source` yields raw (path, action) tuples; the default reads them from
    ReadDirectoryChangesW. Injecting it is what makes this testable.
    """

    def __init__(self, path: str, on_changes, source=None,
                 coalesce: float = COALESCE_SECONDS, clock=time.monotonic) -> None:
        self.path = path
        self._on_changes = on_changes
        self._source = source or self._read_from_directory
        self._coalesce = coalesce
        self._clock = clock
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.error: str | None = None

    # ---- lifecycle -----------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="treesize-watcher")
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- the loop ------------------------------------------------------

    def _run(self) -> None:
        pending: dict[str, int] = {}
        last_flush = self._clock()
        try:
            for path, action in self._source():
                if self._stop.is_set():
                    break
                # Last action per path wins: a file written in ten chunks is
                # one change, and reporting ten would defeat the whole point.
                pending[path] = action
                if self._clock() - last_flush >= self._coalesce:
                    self._flush(pending)
                    pending = {}
                    last_flush = self._clock()
        except Exception as exc:                    # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning("TreeSize watcher stopped: %s", exc, exc_info=True)
        finally:
            self._flush(pending)

    def _flush(self, pending: dict) -> None:
        if not pending:
            return
        try:
            self._on_changes([Change(path, action)
                              for path, action in pending.items()])
        except Exception:                           # noqa: BLE001
            logger.warning("TreeSize watcher callback failed", exc_info=True)

    # ---- the Windows source --------------------------------------------

    def _read_from_directory(self):
        handle = _kernel32.CreateFileW(
            self.path, FILE_LIST_DIRECTORY,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise OSError(f"Cannot watch {self.path}: "
                          f"{ctypes.FormatError(ctypes.get_last_error()).strip()}")
        buffer = ctypes.create_string_buffer(BUFFER_BYTES)
        returned = wintypes.DWORD(0)
        try:
            while not self._stop.is_set():
                ok = _kernel32.ReadDirectoryChangesW(
                    handle, buffer, BUFFER_BYTES, True, WATCH_FLAGS,
                    ctypes.byref(returned), None, None)
                if not ok or returned.value == 0:
                    break
                yield from self._parse(buffer.raw[:returned.value])
        finally:
            _kernel32.CloseHandle(handle)

    def _parse(self, raw: bytes):
        """Walk the FILE_NOTIFY_INFORMATION chain."""
        offset = 0
        while offset < len(raw):
            next_entry, action, name_bytes = ctypes.cast(
                ctypes.byref(ctypes.create_string_buffer(raw[offset:offset + 12])),
                ctypes.POINTER(ctypes.c_uint32 * 3)).contents[:]
            name_start = offset + 12
            name = raw[name_start:name_start + name_bytes].decode(
                "utf-16-le", errors="replace")
            yield os.path.join(self.path, name), action
            if next_entry == 0:
                break
            offset += next_entry
