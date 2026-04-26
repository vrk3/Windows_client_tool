import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from modules.treesize.disk_scanner import DiskNode

COLUMNS = ["Name", "Size", "% of Parent", "Files", "Last Modified"]
COL_NAME, COL_SIZE, COL_PCT, COL_FILES, COL_MODIFIED = range(5)

# Color sequence for pie chart
_CHART_COLORS = [
    QColor("#4488FF"), QColor("#FF8800"), QColor("#44DD88"),
    QColor("#FF44AA"), QColor("#AAAA44"), QColor("#AA44FF"),
    QColor("#44FFFF"), QColor("#FF8844"), QColor("#88FF44"),
    QColor("#FF44FF"),
]


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


class SizeBarDelegate(QStyledItemDelegate):
    """Renders size column as an inline coloured bar + text.
    Also renders % of Parent column as an inline progress bar."""

    def paint(self, painter: QPainter, option: "QStyleOptionViewItem", index: QModelIndex):
        node: Optional[DiskNode] = index.data(Qt.ItemDataRole.UserRole)
        if node is None:
            super().paint(painter, option, index)
            return

        col = index.column()

        # ── % of Parent bar ────────────────────────────────────────────────
        if col == COL_PCT:
            painter.save()
            painter.fillRect(option.rect, option.palette.base())
            parent_size = node.parent.size if node.parent else node.size
            pct = node.size / parent_size if parent_size > 0 else 0.0
            bar_width = max(1, int(option.rect.width() * min(pct, 1.0)))
            bar_rect = option.rect.adjusted(0, 2, 0, -2)
            bar_rect.setWidth(bar_width)
            # Color based on percentage
            if pct >= 0.8:
                bar_color = QColor("#FF4444")
            elif pct >= 0.5:
                bar_color = QColor("#FF8800")
            elif pct >= 0.2:
                bar_color = QColor("#4488FF")
            else:
                bar_color = QColor("#888888")
            painter.fillRect(bar_rect, bar_color)
            painter.drawText(
                option.rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"  {pct * 100:.1f}%",
            )
            painter.restore()
            return

        # ── Size bar ───────────────────────────────────────────────────────
        if col == COL_SIZE:
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

            # Size delta arrow (feature 23)
            delta = self._delta_map.get(node.path) if hasattr(self, "_delta_map") else None
            extra = ""
            if delta is not None and delta != node.size:
                extra = " ↑" if node.size > delta else " ↓"

            painter.drawText(
                option.rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"  {format_size(node.size)}{extra}",
            )
            painter.restore()
            return

        # ── Name column — name text + mini size bar ────────────────────────
        if col == COL_NAME:
            painter.save()
            painter.fillRect(option.rect, option.palette.base())

            # Draw name text
            painter.drawText(
                option.rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "  " + node.name,
            )

            # Draw mini size bar at the right end of the column
            parent_size = node.parent.size if node.parent else node.size
            pct = node.size / parent_size if parent_size > 0 else 0
            bar_height = max(2, int(option.rect.height() * 0.3))
            bar_y = option.rect.top() + (option.rect.height() - bar_height) // 2
            bar_width = max(2, int(option.rect.width() * 0.3 * pct))  # occupy up to 30% of col width
            bar_x = option.rect.right() - bar_width - 4
            if node.size > 1 * 1024 ** 3:
                bar_color = QColor("#FF8800")
            elif node.is_dir:
                bar_color = QColor("#4488FF")
            else:
                bar_color = QColor("#888888")
            painter.fillRect(bar_x, bar_y, bar_width, bar_height, bar_color)

            painter.restore()
            return

        super().paint(painter, option, index)

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        sh.setWidth(max(sh.width(), 120))
        return sh

    def setDeltaMap(self, delta_map: Dict[str, int]) -> None:
        self._delta_map = delta_map


class DiskTreeModel(QAbstractItemModel):
    """Tree model for DiskNode. All mutations must happen on the main thread."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots: List[DiskNode] = []
        self._min_size: int = 0  # bytes filter; 0 = no filter
        # ── feature: live search ─────────────────────────────────────────
        self._search_query: str = ""
        # ── feature: size delta ───────────────────────────────────────────
        self._last_scan: Dict[str, int] = {}  # path -> size snapshot

    # ── public API ──────────────────────────────────────────────────────────

    def set_min_size_filter(self, size_bytes: int):
        self.layoutAboutToBeChanged.emit()
        self._min_size = size_bytes
        self.layoutChanged.emit()

    def set_search_query(self, query: str) -> None:
        self.layoutAboutToBeChanged.emit()
        self._search_query = query.strip()
        self.layoutChanged.emit()

    def add_batch(self, nodes: List[DiskNode]):
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
        self._last_scan.clear()
        self.endResetModel()

    def replace_node(self, new_node: "DiskNode") -> None:
        for i, root in enumerate(self._roots):
            if root.path == new_node.path:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, self.index(i, self.columnCount() - 1))
                self._roots[i] = new_node
                return

    # ── feature: size delta ─────────────────────────────────────────────────

    def store_last_scan(self) -> None:
        self._last_scan.clear()

        def walk(node: DiskNode):
            self._last_scan[node.path] = node.size
            for c in node.children:
                walk(c)

        for root in self._roots:
            walk(root)

    def get_size_delta(self, path: str) -> Optional[int]:
        return self._last_scan.get(path)

    def delta_map(self) -> Dict[str, int]:
        return self._last_scan

    # ── feature: top N largest files ───────────────────────────────────────

    def get_top_files(self, n: int = 10) -> List[DiskNode]:
        all_files: List[DiskNode] = []

        def collect(node: DiskNode):
            if not node.is_dir:
                all_files.append(node)
            for c in node.children:
                collect(c)

        for root in self._roots:
            collect(root)

        all_files.sort(key=lambda x: x.size, reverse=True)
        return all_files[:n]

    # ── helpers ─────────────────────────────────────────────────────────────

    def _node_matches(self, node: DiskNode) -> bool:
        if not self._search_query:
            return True
        q = self._search_query.lower()
        if q in node.name.lower():
            return True
        return any(self._node_matches(c) for c in node.children)

    def _visible_children(self, node: DiskNode) -> List[DiskNode]:
        base = node.children if node.parent else self._roots
        if self._min_size == 0 and not self._search_query:
            return base
        result = []
        for c in base:
            size_ok = self._min_size == 0 or c.size >= self._min_size
            if size_ok and self._search_query:
                if self._node_matches(c):
                    result.append(c)
            elif size_ok:
                result.append(c)
            elif self._search_query and self._node_matches(c):
                result.append(c)
        return result

    # ── QAbstractItemModel interface ─────────────────────────────────────────

    def index(self, row: int, column: int, parent: QModelIndex = None) -> QModelIndex:
        if parent is None:
            parent = QModelIndex()
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

    def rowCount(self, parent: QModelIndex = None) -> int:
        if parent is None:
            parent = QModelIndex()
        if not parent.isValid():
            return len(self._roots)
        return len(self._visible_children(parent.internalPointer()))

    def columnCount(self, parent: QModelIndex = None) -> int:
        if parent is None:
            parent = QModelIndex()
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
                return format_size(node.size)
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

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder

        def get_key(node: DiskNode):
            if column == COL_NAME:
                return node.name.lower()
            elif column == COL_SIZE:
                return node.size
            elif column == COL_PCT:
                ps = node.parent.size if node.parent else node.size
                return (node.size / ps * 100) if ps > 0 else 0.0
            elif column == COL_FILES:
                return node.file_count
            elif column == COL_MODIFIED:
                return node.last_modified or 0
            return ""

        def do_sort(nodes: List[DiskNode]) -> List[DiskNode]:
            return sorted(nodes, key=get_key, reverse=reverse)

        self.layoutAboutToBeChanged.emit()
        self._roots = do_sort(self._roots)
        for root in self._roots:
            if root.children:
                root.children = do_sort(root.children)
        self.layoutChanged.emit()


# ── PieChartWidget (feature 21) ─────────────────────────────────────────────

class PieChartWidget:
    """Simple donut/pie chart drawn with QPainter. Used as a standalone widget."""

    def __init__(self):
        self._roots: List[DiskNode] = []
        self.setMinimumHeight(80)

    def set_roots(self, roots: List[DiskNode]) -> None:
        self._roots = [r for r in roots if r.is_dir and r.size > 0]
        self.update()

    def paint(self, painter: QPainter):
        """Call from a widget's paintEvent."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = painter.viewport()
        w, h = rect.width(), rect.height()
        size = min(w, h) - 8
        r = size // 2
        cx, cy = rect.x() + w // 2, rect.y() + h // 2

        if not self._roots:
            painter.drawText(cx - 40, cy, "No data")
            return

        total = sum(r.size for r in self._roots)
        if total == 0:
            return

        # Draw pie slices
        angle = 0
        for i, root in enumerate(self._roots):
            sweep = int(360 * 16 * root.size / total)
            color = _CHART_COLORS[i % len(_CHART_COLORS)]
            painter.setPen(color)
            painter.setBrush(color)
            painter.drawPie(
                cx - r, cy - r, size, size,
                int(angle * 16), sweep,
            )
            angle += sweep / 16

        # Donut hole (white center)
        inner = int(r * 0.45)
        painter.setBrush(painter.viewport().parent())
        painter.drawEllipse(cx - inner, cy - inner, inner * 2, inner * 2)

        # Legend labels
        legend_x = cx + r // 2 + 10
        legend_y = cy - (len(self._roots) * 14) // 2
        for i, root in enumerate(self._roots[:6]):
            color = _CHART_COLORS[i % len(_CHART_COLORS)]
            pct = root.size / total * 100
            painter.setPen(color)
            painter.drawText(legend_x, legend_y + i * 14,
                             f"{root.name[:12]}: {pct:.0f}%")
