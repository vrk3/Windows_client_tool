"""Directory walk fallback using FindFirstFileExW.

FindExInfoBasic skips 8.3 name resolution and FIND_FIRST_EX_LARGE_FETCH
batches directory entries, together giving far fewer kernel transitions
than os.scandir on deep trees.
"""
import ctypes
import os
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from ..store.node_store import NodeStore, DIR, REPARSE, HIDDEN

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_HIDDEN = 0x2
FindExInfoBasic = 1
FindExSearchNameMatch = 0
FIND_FIRST_EX_LARGE_FETCH = 2
ERROR_NO_MORE_FILES = 18

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class FILETIME(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    @property
    def value(self) -> int:
        return (self.high << 32) | self.low


class WIN32_FIND_DATAW(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", FILETIME),
        ("ftLastAccessTime", FILETIME),
        ("ftLastWriteTime", FILETIME),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("dwReserved0", wintypes.DWORD),
        ("dwReserved1", wintypes.DWORD),
        ("cFileName", wintypes.WCHAR * 260),
        ("cAlternateFileName", wintypes.WCHAR * 14),
    ]


_kernel32.FindFirstFileExW.restype = wintypes.HANDLE
_kernel32.FindFirstFileExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.LPVOID,
                                       ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_kernel32.FindNextFileW.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
_kernel32.FindClose.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class DirEntry:
    name: str
    is_dir: bool
    is_reparse: bool
    is_hidden: bool
    size: int
    ctime: int
    mtime: int
    atime: int


def _long_path(path: str) -> str:
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def list_directory(path: str, on_error=None) -> list[DirEntry]:
    """Entries in `path`, or [] if it could not be opened.

    An empty list is ambiguous by itself -- an empty folder and a folder we were
    denied look identical -- so a caller that cares passes `on_error(path, why)`
    and learns which it was. Without that, a locked subtree silently contributes
    zero bytes to a total the user is expected to trust.
    """
    data = WIN32_FIND_DATAW()
    handle = _kernel32.FindFirstFileExW(
        _long_path(os.path.join(path, "*")), FindExInfoBasic, ctypes.byref(data),
        FindExSearchNameMatch, None, FIND_FIRST_EX_LARGE_FETCH)
    if not handle or handle == INVALID_HANDLE_VALUE:
        if on_error is not None:
            on_error(path, ctypes.FormatError(ctypes.get_last_error()).strip())
        return []
    out: list[DirEntry] = []
    try:
        while True:
            name = data.cFileName
            if name not in (".", ".."):
                attrs = data.dwFileAttributes
                out.append(DirEntry(
                    name=name,
                    is_dir=bool(attrs & FILE_ATTRIBUTE_DIRECTORY),
                    is_reparse=bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT),
                    is_hidden=bool(attrs & FILE_ATTRIBUTE_HIDDEN),
                    size=(data.nFileSizeHigh << 32) | data.nFileSizeLow,
                    ctime=data.ftCreationTime.value,
                    mtime=data.ftLastWriteTime.value,
                    atime=data.ftLastAccessTime.value,
                ))
            if not _kernel32.FindNextFileW(handle, ctypes.byref(data)):
                break
    finally:
        _kernel32.FindClose(handle)
    return out


class WalkScanner:
    MAX_RECORDED_ERRORS = 100

    def __init__(self, root_path: str, bytes_per_cluster: int = 4096,
                 max_workers: int | None = None,
                 exclude: Callable[[str, int, int], bool] | None = None) -> None:
        self.root_path = os.path.abspath(root_path)
        self.bytes_per_cluster = bytes_per_cluster
        self.max_workers = max_workers or min(32, (os.cpu_count() or 4) * 4)
        self.exclude = exclude
        self.root = -1
        # Directories that could not be listed. The list is capped so a scan of
        # a heavily locked-down tree cannot balloon; error_count is not, so the
        # true scale of the gap is never lost.
        self.errors: list[tuple[str, str]] = []
        self.error_count = 0

    def _record_error(self, path: str, why: str) -> None:
        self.error_count += 1
        if len(self.errors) < self.MAX_RECORDED_ERRORS:
            self.errors.append((path, why))

    def _alloc_for(self, size: int) -> int:
        if size == 0:
            return 0
        c = self.bytes_per_cluster
        return ((size + c - 1) // c) * c

    def scan(self, store: NodeStore, on_batch=None, should_cancel=None,
             wait_if_paused=None, batch_size: int = 500) -> int:
        self.root = store.add(-1, self.root_path, attrs=DIR)
        queue: deque[tuple[int, str]] = deque([(self.root, self.root_path)])
        batch_start = len(store)
        while queue:
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            node, path = queue.popleft()
            for entry in list_directory(path, on_error=self._record_error):
                flags = 0
                if entry.is_dir:
                    flags |= DIR
                if entry.is_reparse:
                    flags |= REPARSE
                if entry.is_hidden:
                    flags |= HIDDEN
                size = 0 if entry.is_dir else entry.size
                if self.exclude is not None and self.exclude(entry.name, size, flags):
                    continue
                idx = store.add(node, entry.name, size=size,
                                alloc=self._alloc_for(size),
                                mtime=entry.mtime, ctime=entry.ctime,
                                atime=entry.atime, attrs=flags)
                if entry.is_dir and not entry.is_reparse:
                    queue.append((idx, os.path.join(path, entry.name)))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
        store.build_child_lists()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)
