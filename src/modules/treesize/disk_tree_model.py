import datetime
from typing import List, Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from modules.treesize.disk_scanner import DiskNode

COLUMNS = ["Name", "Size", "% of Parent", "Files", "Last Modified"]
COL_NAME, COL_SIZE, COL_PCT, COL_FILES, COL_MODIFIED = range(5)


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class SizeBarDelegate(QStyledItemDelegate):
    """Renders size column as an inline coloured bar + text."""

    def paint(self, painter: QPainter, option: "QStyleOptionViewItem", index: QModelIndex):
        if index.column() != COL_SIZE:
            super().paint(painter, option, index)
            return

        node: Optional[DiskNode] = index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.fillRect(option.rect, option.palette.base())

        parent_size = node.parent.size if node.parent else node.size
        pct = node.size / parent_size if parent_size > 0 else 0
        bar_width = max(1, int(option.rect.width() * pct))

        if node.size > 10 * 1024 ** 3:
            color = QColor("#FF4444")
        elif node.size > 1 * 1024 ** 3:
            color = QColor("#FF8800")
        elif node.is_dir:
            color = QColor("#4488FF")
        else:
            color = QColor("#888888")

        bar_rect = option.rect.adjusted(0, 2, 0, -2)
        bar_rect.setWidth(bar_width)
        painter.fillRect(bar_rect, color)
        painter.drawText(
            option.rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            f"  {format_size(node.size)}",
        )
        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        sh.setWidth(max(sh.width(), 120))
        return sh


class DiskTreeModel(QAbstractItemModel):
    """Tree model for DiskNode. All mutations must happen on the main thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots: List[DiskNode] = []
        self._min_size: int = 0  # bytes filter; 0 = no filter

    # ── public API ──────────────────────────────────────────────────────────

    def set_min_size_filter(self, size_bytes: int):
        self.layoutAboutToBeChanged.emit()
        self._min_size = size_bytes
        self.layoutChanged.emit()

    def add_batch(self, nodes: List[DiskNode]):
        """Slot — receives batch from DiskScanner. Main thread only."""
        existing = {r.path for r in self._roots}
        new = [n for n in nodes if n.path not in existing]
        if not new:
            return
        first = len(self._roots)
        self.beginInsertRows(QModelIndex(), first, first + len(new) - 1)
        self._roots.extend(new)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._roots.clear()
        self.endResetModel()

    # ── helpers ─────────────────────────────────────────────────────────────

    def _visible_children(self, node: DiskNode) -> List[DiskNode]:
        if self._min_size == 0:
            return node.children
        return [c for c in node.children if c.size >= self._min_size]

    # ── QAbstractItemModel interface ─────────────────────────────────────────

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not parent.isValid():
            src = self._roots
        else:
            src = self._visible_children(parent.internalPointer())
        if 0 <= row < len(src):
            return self.createIndex(row, column, src[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node: DiskNode = index.internalPointer()
        if node.parent is None:
            return QModelIndex()
        p = node.parent
        siblings = self._roots if p.parent is None else self._visible_children(p.parent)
        try:
            row = siblings.index(p)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, p)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if not parent.isValid():
            return len(self._roots)
        return len(self._visible_children(parent.internalPointer()))

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: DiskNode = index.internalPointer()
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return node.name
            if col == COL_SIZE:
                return format_size(node.size)  # delegate will also draw the bar
            if col == COL_PCT:
                ps = node.parent.size if node.parent else node.size
                pct = (node.size / ps * 100) if ps > 0 else 0.0
                return f"{pct:.1f}%"
            if col == COL_FILES:
                return str(node.file_count)
            if col == COL_MODIFIED:
                if node.last_modified:
                    return datetime.datetime.fromtimestamp(
                        node.last_modified).strftime("%Y-%m-%d %H:%M")
                return ""

        if role == Qt.ItemDataRole.UserRole:
            return node

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SIZE, COL_PCT, COL_FILES):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None
