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
import stat
import struct
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

from ..store.node_store import DIR, EXCLUDED
from .walk_scanner import to_filetime

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

#: FILE_NOTIFY_INFORMATION: NextEntryOffset, Action, FileNameLength.
_HEADER_BYTES = 12

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


def _alloc_for(size: int, bytes_per_cluster: int) -> int:
    """Allocated bytes for a logical size, or 0 when the geometry is unknown.

    A remote target has no cluster size. Guessing one would put a number in
    the Allocated column that the volume never had, so `alloc` is left alone
    instead -- see the `bytes_per_cluster == 0` branches below.
    """
    if size <= 0 or bytes_per_cluster <= 0:
        return 0
    return ((size + bytes_per_cluster - 1) // bytes_per_cluster) * bytes_per_cluster


def _charge(store, root: int, start: int, size: int, alloc: int,
            files: int, folders: int) -> None:
    """Add deltas to `start` and every ancestor up to `root` inclusive.

    O(depth), not O(volume) -- that is the whole point of updating rather
    than rescanning. The `seen` set is there because a corrupt parent chain
    must cost a wrong number, never a frozen UI thread.

    `file_count` and `folder_count` are UNSIGNED arrays, so a decrement past
    zero raises OverflowError rather than wrapping. They are clamped.
    """
    walker = start
    seen = set()
    while 0 <= walker < len(store) and walker not in seen:
        seen.add(walker)
        if size:
            store.size[walker] += size
        if alloc:
            store.alloc[walker] += alloc
        if files:
            store.file_count[walker] = max(0, store.file_count[walker] + files)
        if folders:
            store.folder_count[walker] = max(0, store.folder_count[walker] + folders)
        if walker == root:
            break
        walker = store.parent[walker]


@dataclass(frozen=True)
class Applied:
    """What one change did to the store.

    `structural` is the part the shell cannot infer: the tree model caches a
    child tuple per node, so a row appearing or vanishing needs that cache
    dropped and a layout signal, where a number moving needs only a repaint.
    """
    delta: int = 0
    structural: bool = False

    def __bool__(self) -> bool:
        return bool(self.delta) or self.structural


def _insert(store, root: int, parent: int, path: str,
            bytes_per_cluster: int) -> Applied:
    """Hang a newly created file or folder off a parent already in the store.

    Charging an unknown path straight to its parent without inserting it is
    the obvious shortcut and it is wrong: the path is still absent afterwards,
    so the next notification for the same file charges it all over again.
    """
    try:
        info = os.stat(path)
    except OSError:
        return Applied()            # created and gone again, or unreadable
    is_dir = stat.S_ISDIR(info.st_mode)
    size = 0 if is_dir else info.st_size
    alloc = _alloc_for(size, bytes_per_cluster)
    node = store.add(parent, os.path.basename(path),
                     size=size, alloc=alloc, attrs=DIR if is_dir else 0,
                     mtime=to_filetime(info.st_mtime),
                     ctime=to_filetime(info.st_ctime),
                     atime=to_filetime(info.st_atime))
    # build_child_lists ran at the end of the scan and will not run again, so
    # the sibling chain is spliced by hand. Head insertion, which is the order
    # that pass produces anyway; the model sorts what it displays.
    store.next_sibling[node] = store.first_child[parent]
    store.first_child[parent] = node
    _charge(store, root, parent, size, alloc,
            0 if is_dir else 1, 1 if is_dir else 0)
    return Applied(delta=size, structural=True)


def _remove(store, root: int, node: int) -> Applied:
    """Take a vanished node out of the totals and out of the view.

    Zeroing the size was not enough: the row stayed in the tree at 0 bytes and
    stayed in the file count, so "Number of files" only ever went up. EXCLUDED
    is what every consumer already checks, and it also makes this idempotent
    -- a second notification for the same deletion finds the flag and stops.
    """
    if store.attrs[node] & EXCLUDED:
        return Applied()
    is_dir = bool(store.attrs[node] & DIR)
    size, alloc = store.size[node], store.alloc[node]
    files = store.file_count[node] if is_dir else 1
    folders = (1 + store.folder_count[node]) if is_dir else 0
    store.attrs[node] |= EXCLUDED
    parent = store.parent[node]
    if 0 <= parent < len(store) and node != root:
        _charge(store, root, parent, -size, -alloc, -files, -folders)
    store.size[node] = 0
    store.alloc[node] = 0
    return Applied(delta=-size, structural=True)


def apply_change(store, root: int, path: str,
                 bytes_per_cluster: int = 0) -> Applied:
    """Re-stat one path and push the difference up its parent chain.

    Handles the three things a notification can mean -- this file changed
    size, this file is new, this file is gone -- as deltas against the stored
    totals. Only the chain from the node to the root is touched, which is what
    makes an update O(depth) rather than O(volume).
    """
    if store is None or root < 0:
        return Applied()
    node = find_node(store, root, path)
    if node < 0:
        # Not in the store. If its folder is, and the path really exists, it
        # was created since the scan; otherwise it is outside the scan and
        # none of our business.
        parent = find_node(store, root, os.path.dirname(path))
        if parent < 0 or store.attrs[parent] & EXCLUDED:
            return Applied()
        return _insert(store, root, parent, path, bytes_per_cluster)

    if store.attrs[node] & EXCLUDED:
        return Applied()
    try:
        info = os.stat(path)
    except OSError:
        return _remove(store, root, node)
    if store.attrs[node] & DIR:
        return Applied()            # a folder's own size is its subtree's
    size_delta = info.st_size - store.size[node]
    alloc_delta = 0
    if bytes_per_cluster > 0:
        alloc_delta = (_alloc_for(info.st_size, bytes_per_cluster)
                       - store.alloc[node])
    if not size_delta and not alloc_delta:
        return Applied()
    _charge(store, root, node, size_delta, alloc_delta, 0, 0)
    return Applied(delta=size_delta)


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
        self._ticker: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending: dict[str, int] = {}
        self._last_flush = 0.0
        self._lock = threading.Lock()
        self.error: str | None = None

    # ---- lifecycle -----------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="treesize-watcher")
        self._thread.start()
        # The reader thread cannot flush on its own, because ReadDirectoryChangesW
        # BLOCKS: between two changes it is parked in the kernel and runs no
        # code at all. A window that is only ever checked on arrival of the
        # NEXT change means one edit followed by quiet is buffered forever --
        # which is exactly how anyone watches a single folder.
        self._ticker = threading.Thread(target=self._tick, daemon=True,
                                        name="treesize-watcher-flush")
        self._ticker.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        ticker, self._ticker = self._ticker, None
        for worker in (ticker, thread):
            if worker is not None:
                worker.join(timeout)

    def _tick(self) -> None:
        """Flush whatever is pending, once a window, until stopped."""
        # Half a window, so a batch is never held for much more than one.
        interval = max(0.01, self._coalesce / 2)
        while not self._stop.wait(interval):
            self._maybe_flush()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- the loop ------------------------------------------------------

    def _run(self) -> None:
        with self._lock:
            self._pending = {}
            self._last_flush = self._clock()
        try:
            for path, action in self._source():
                if self._stop.is_set():
                    break
                # Last action per path wins: a file written in ten chunks is
                # one change, and reporting ten would defeat the whole point.
                with self._lock:
                    self._pending[path] = action
                self._maybe_flush()
        except Exception as exc:                    # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            logger.warning("TreeSize watcher stopped: %s", exc, exc_info=True)
        finally:
            self._maybe_flush(force=True)

    def _maybe_flush(self, force: bool = False) -> None:
        """Emit the buffer if the window has elapsed, or if forced.

        Both the reader thread and the ticker call this, so the buffer is
        swapped out under the lock and the callback runs outside it -- holding
        a lock across a Qt signal emit is how a watcher deadlocks the UI.
        """
        with self._lock:
            if not self._pending:
                return
            now = self._clock()
            if not force and now - self._last_flush < self._coalesce:
                return
            batch, self._pending = self._pending, {}
            self._last_flush = now
        try:
            self._on_changes([Change(path, action)
                              for path, action in batch.items()])
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
        """Walk the FILE_NOTIFY_INFORMATION chain.

        struct, not ctypes. The previous reading of the three header DWORDs
        went through `cast(byref(create_string_buffer(...)))`, whose buffer is
        a temporary Python is free to collect the moment `byref` returns --
        so every record decoded as action 0 with an empty name, which resolved
        to the watched root and compared equal to itself. The kernel was
        delivering perfectly good notifications and every one was discarded.
        """
        offset = 0
        limit = len(raw)
        while offset + _HEADER_BYTES <= limit:
            next_entry, action, name_bytes = struct.unpack_from(
                "<III", raw, offset)
            name_start = offset + _HEADER_BYTES
            name_end = name_start + name_bytes
            if name_end > limit:
                break               # the kernel filled less than it promised
            name = raw[name_start:name_end].decode("utf-16-le", errors="replace")
            if name:
                yield os.path.join(self.path, name), action
            if next_entry == 0:
                break
            offset += next_entry
