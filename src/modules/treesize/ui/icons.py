"""Per-extension file icons, taken from the shell (spec 5.4).

`SHGetFileInfoW` with `SHGFI_USEFILEATTRIBUTES` returns the icon Explorer would
show for a name, WITHOUT touching the disk — no stat, no open, and it works for
paths that no longer exist. That matters here: the store holds half a million
names from a scan that is already a snapshot, and hitting the filesystem once
per row to decide an icon would cost more than the scan did.

Icons are cached per extension, not per file. There are a few hundred distinct
extensions on a volume and half a million files; an icon per file would cost
more memory than the entire node store.
"""
import ctypes
from ctypes import wintypes

from PyQt6.QtGui import QIcon, QImage, QPixmap
from PyQt6.QtWidgets import QApplication, QStyle

SHGFI_ICON = 0x000000100
SHGFI_SMALLICON = 0x000000001
SHGFI_USEFILEATTRIBUTES = 0x000000010
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_DIRECTORY = 0x10


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HANDLE),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


def _shell_icon(name: str, directory: bool) -> QIcon | None:
    """The icon Explorer would use for `name`, without touching the disk."""
    info = SHFILEINFOW()
    attributes = FILE_ATTRIBUTE_DIRECTORY if directory else FILE_ATTRIBUTE_NORMAL
    flags = SHGFI_ICON | SHGFI_SMALLICON | SHGFI_USEFILEATTRIBUTES
    result = ctypes.windll.shell32.SHGetFileInfoW(
        name, attributes, ctypes.byref(info), ctypes.sizeof(info), flags)
    if not result or not info.hIcon:
        return None
    try:
        image = QImage.fromHICON(int(info.hIcon))
        if image.isNull():
            return None
        return QIcon(QPixmap.fromImage(image))
    finally:
        # The handle is ours once SHGetFileInfoW returns it; leaking one per
        # extension is small, leaking one per row would exhaust the desktop
        # heap on a real scan.
        ctypes.windll.user32.DestroyIcon(info.hIcon)


class IconProvider:
    """Extension -> QIcon, cached. Falls back to Qt's generic icons."""

    def __init__(self) -> None:
        self._cache: dict[str, QIcon] = {}
        self._folder: QIcon | None = None
        self._file: QIcon | None = None

    def _generic(self, directory: bool) -> QIcon:
        if self._folder is None:
            style = QApplication.style()
            self._folder = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            self._file = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        return self._folder if directory else self._file

    def folder(self) -> QIcon:
        icon = self._cache.get("<dir>")
        if icon is None:
            icon = _shell_icon("folder", True) or self._generic(True)
            self._cache["<dir>"] = icon
        return icon

    def for_name(self, name: str, directory: bool = False) -> QIcon:
        if directory:
            return self.folder()
        dot = name.rfind(".")
        extension = name[dot:].lower() if 0 < dot < len(name) - 1 else ""
        icon = self._cache.get(extension)
        if icon is None:
            # A synthetic name carrying only the extension: the icon depends on
            # the extension alone, so caching on the real name would produce one
            # entry per file for no benefit.
            icon = _shell_icon("file" + extension, False) or self._generic(False)
            self._cache[extension] = icon
        return icon

    @property
    def cached_extensions(self) -> int:
        return len(self._cache)
