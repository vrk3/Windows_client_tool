"""Drive list, scan overview bar, and status bar (spec 5.6, 5.7, 5.9).

All three are individually toggleable from the View tab, as in Pro, so each is
a self-contained widget that the shell shows or hides.
"""
import ctypes
import string
from ctypes import wintypes

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTreeWidget,
    QTreeWidgetItem, QWidget,
)

from .formatting import Unit, format_bytes, format_count

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetLogicalDrives.restype = wintypes.DWORD
_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
DRIVE_FIXED = 3
DRIVE_REMOVABLE = 2
DRIVE_REMOTE = 4


def drive_space(letter: str) -> tuple[int, int]:
    """(total, free) bytes for a drive, or (0, 0) if it cannot be queried."""
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ok = _kernel32.GetDiskFreeSpaceExW(f"{letter}:\\", ctypes.byref(free),
                                       ctypes.byref(total), None)
    if not ok:
        return 0, 0
    return total.value, free.value


def list_drives() -> list[tuple[str, int, int]]:
    """(letter, total, free) for every ready fixed, removable or network drive.

    A drive with no media reports zero total; it is skipped rather than shown
    as a 0-byte volume, which is what Pro does.
    """
    mask = _kernel32.GetLogicalDrives()
    out = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not (mask >> i) & 1:
            continue
        if _kernel32.GetDriveTypeW(f"{letter}:\\") not in (
                DRIVE_FIXED, DRIVE_REMOVABLE, DRIVE_REMOTE):
            continue
        total, free = drive_space(letter)
        if total:
            out.append((letter, total, free))
    return out


class DriveList(QTreeWidget):
    """Bottom-left panel: Name, Total Size, Free, % Free with a bar."""

    drive_activated = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(4)
        self.setHeaderLabels(["Name", "Total Size", "Free", "% Free"])
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.itemDoubleClicked.connect(self._on_double_clicked)

    def refresh(self, drives=None) -> None:
        self.clear()
        for letter, total, free in (list_drives() if drives is None else drives):
            percent_free = (free * 100.0 / total) if total else 0.0
            item = QTreeWidgetItem([
                f"{letter}:",
                format_bytes(total),
                format_bytes(free),
                f"{percent_free:.1f}%",
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, letter)
            for column in (1, 2, 3):
                item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
            self.addTopLevelItem(item)

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        letter = item.data(0, Qt.ItemDataRole.UserRole)
        if letter:
            self.drive_activated.emit(f"{letter}:\\")


class ScanOverview(QWidget):
    """The bar above the panes: facts about the current selection (spec 5.7)."""

    FIELDS = ("Size", "Allocated", "Files", "Folders",
              "Last Modified", "Last Accessed", "Owner")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(16)
        self._labels: dict[str, QLabel] = {}
        for field in self.FIELDS:
            label = QLabel(f"{field}: —")
            label.setObjectName("scanOverviewField")
            self._labels[field] = label
            layout.addWidget(label)
        layout.addStretch(1)

    def clear(self) -> None:
        for field, label in self._labels.items():
            label.setText(f"{field}: —")

    def show_node(self, store, node: int, unit: Unit = Unit.AUTO,
                  decimals: int = 1) -> None:
        if store is None or not (0 <= node < len(store)):
            self.clear()
            return
        values = {
            "Size": format_bytes(store.size[node], unit, decimals),
            "Allocated": format_bytes(store.alloc[node], unit, decimals),
            "Files": format_count(store.file_count[node]),
            "Folders": format_count(store.folder_count[node]),
            "Last Modified": format_filetime(store.mtime[node]),
            "Last Accessed": format_filetime(store.atime[node]),
            "Owner": store.owner(store.owner_id[node]) or "—",
        }
        for field, text in values.items():
            self._labels[field].setText(f"{field}: {text}")


def format_filetime(value: int) -> str:
    """A Windows FILETIME as a local timestamp, or an em dash if unset."""
    if not value:
        return "—"
    import datetime
    seconds = value / 10_000_000 - 11_644_473_600
    try:
        return datetime.datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M")
    except (OSError, OverflowError, ValueError):
        return "—"


class TreeSizeStatusBar(QWidget):
    """Free space, counts, cluster size, filters and scan errors (spec 5.9)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(20)
        self._free = QLabel()
        self._files = QLabel()
        self._excluded = QLabel()
        self._cluster = QLabel()
        self._notice = QLabel()
        self._notice.setObjectName("statusNotice")
        for widget in (self._free, self._files, self._excluded, self._cluster):
            layout.addWidget(widget)
        layout.addStretch(1)
        layout.addWidget(self._notice)
        self.clear()

    def clear(self) -> None:
        self._free.setText("Free Space: —")
        self._files.setText("0 Files")
        self._excluded.setText("0 Excluded")
        self._cluster.setText("—")
        self._notice.setText("")

    def show_result(self, result, drive_total: int = 0, drive_free: int = 0) -> None:
        if drive_total:
            self._free.setText(
                f"Free Space: {format_bytes(drive_free)} of {format_bytes(drive_total)}")
        self._files.setText(f"{format_count(result.node_count)} Files")
        self._excluded.setText(f"{format_count(result.excluded)} Excluded")
        if result.volume_info:
            self._cluster.setText(
                f"{result.volume_info.bytes_per_cluster:,} Bytes per Cluster (NTFS)")
        else:
            self._cluster.setText("—")
        self._notice.setText(self._notice_for(result))

    def _notice_for(self, result) -> str:
        """What Pro's status bar is for: say when the scan was degraded.

        An incomplete scan is the loudest thing here, because every total above
        it is then a lower bound rather than a measurement.
        """
        if not result.complete:
            first = result.errors[0][0] if result.errors else ""
            return (f"INCOMPLETE — {format_count(result.error_count)} location(s) "
                    f"unreadable{f': {first}' if first else ''}")
        if result.engine == "walk":
            return "Fast MFT scan unavailable — run elevated on an NTFS drive for exact allocated sizes"
        return ""
