import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem

from modules.treesize.disk_scanner import DiskNode, SIZE_UNKNOWN

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
    if size < 0:
        return "…"
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
            if parent_size <= 0 or node.size < 0:
                painter.drawText(
                    option.rect,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    "  …",
                )
                painter.restore()
                return
            pct = node.size / parent_size
            bar_width = max(1, int(option.rect.width() * min(pct, 1.0)))
            bar_rect = option.rect.adjusted(0, 2, 0, -2)
            bar_rect.setWidth(bar_width)
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

            if node.size < 0:
                # SIZE_UNKNOWN — show ellipsis
                painter.drawText(
                    option.rect,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    "  …",
                )
                painter.restore()
                return

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

            delta = self._delta_map.get(node.path) if hasattr(self, "_delta_map") else None
            extra = ""
            if delta is not None and delta >= 0 and delta != node.size:
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

            name_text = node.name
            loading = index.data(Qt.ItemDataRole.UserRole + 1)
            if loading:
                name_text += " ⏳"

            painter.drawText(
                option.rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                "  " + name_text,
            )

            if node.size >= 0:
                parent_size = node.parent.size if node.parent else node.size
                pct = node.size / parent_size if parent_size > 0 else 0
                bar_height = max(2, int(option.rect.height() * 0.3))
                bar_y = option.rect.top() + (option.rect.height() - bar_height) // 2
                bar_width = max(2, int(option.rect.width() * 0.3 * pct))
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
    """Tree model for DiskNode. All mutations must happen on the main thread.

    Supports lazy loading: directories with SIZE_UNKNOWN (-1) are stubs
    that show an expand arrow (via hasChildren) but have zero children
    until the user expands them, triggering an on-demand scan.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._roots: List[DiskNode] = []
        self._min_size: int = 0
        self._search_query: str = ""
        self._last_scan: Dict[str, int] = {}
        self._node_map: Dict[str, DiskNode] = {}  # path -> node for direct lookup
        self._loading_paths: set = set()

    # ── public API ──────────────────────────────────────────────────────────

    def get_roots(self) -> List[DiskNode]:
        """Return a copy of the root node list (safe public accessor)."""
        return list(self._roots)

    def set_min_size_filter(self, size_bytes: int):
        self.layoutAboutToBeChanged.emit()
        self._min_size = size_bytes
        self.layoutChanged.emit()

    def set_search_query(self, query: str) -> None:
        self.layoutAboutToBeChanged.emit()
        self._search_query = query.strip()
        self.layoutChanged.emit()

    def mark_loading(self, path: str) -> None:
        self._loading_paths.add(path)
        idx = self._node_index_for_path(path)
        if idx and idx.isValid():
            self.dataChanged.emit(idx, idx)

    def unmark_loading(self, path: str) -> None:
        self._loading_paths.discard(path)
        idx = self._node_index_for_path(path)
        if idx and idx.isValid():
            self.dataChanged.emit(idx, idx)

    def is_loading(self, path: str) -> bool:
        return path in self._loading_paths

    def add_batch(self, nodes: List[DiskNode]):
        existing = {r.path for r in self._roots}
        new = [n for n in nodes if n.path not in existing]
        if not new:
            return
        first = len(self._roots)
        self.beginInsertRows(QModelIndex(), first, first + len(new) - 1)
        self._roots.extend(new)
        for n in new:
            self._node_map[n.path] = n
            # Register all descendants so add_children_to_node can find them
            def _register_descendants(node: DiskNode):
                for child in node.children:
                    self._node_map[child.path] = child
                    _register_descendants(child)
            _register_descendants(n)
        self.endInsertRows()

    def clear(self):
        self.beginResetModel()
        self._roots.clear()
        self._last_scan.clear()
        self._node_map.clear()
        self._loading_paths.clear()
        self.endResetModel()

    def add_children_to_node(self, parent_path: str, children: List[DiskNode]) -> DiskNode:
        """Add children to an existing node. Returns parent node or None if not found."""
        parent = self._node_map.get(parent_path)
        if parent is None:
            return None

        parent._fully_loaded = True

        # Calculate cumulative size for the parent from its children
        total_size = 0
        total_files = 0
        for child in children:
            child.parent = parent
            self._node_map[child.path] = child
            if child.size >= 0:
                total_size += child.size
            if child.is_dir:
                total_files += child.file_count
            else:
                total_files += 1

        parent.size = total_size
        parent.file_count = total_files
        parent.children = children

        # Notify views that the parent node's data changed (size is now known)
        pidx = self._node_index_for_path(parent_path)
        if pidx and pidx.isValid():
            self.dataChanged.emit(pidx, self.index(pidx.row(), self.columnCount() - 1, pidx.parent()))

        # Notify child insertion
        if children:
            self.beginInsertRows(pidx, 0, len(children) - 1)
            self.endInsertRows()

        return parent

    def update_parent_sizes(self, node: DiskNode) -> None:
        """Walk up the tree recalculating sizes after a loaded node changes."""
        p = node.parent
        while p is not None:
            new_size = sum(c.size for c in p.children if c.size >= 0)
            new_files = sum(c.file_count for c in p.children)
            p.size = new_size
            p.file_count = new_files
            pidx = self._node_index_for_path(p.path)
            if pidx and pidx.isValid():
                self.dataChanged.emit(pidx, self.index(pidx.row(), self.columnCount() - 1, pidx.parent()))
            p = p.parent

    def _node_index_for_path(self, path: str) -> Optional[QModelIndex]:
        """Find the QModelIndex for a node by its path."""
        node = self._node_map.get(path)
        if node is None:
            return None

        # Find the node's row among its parent's children
        if node.parent is None:
            # Root-level node
            try:
                row = self._roots.index(node)
            except ValueError:
                return None
            return self.index(row, 0, QModelIndex())

        # Non-root node
        siblings = self._visible_children(node.parent)
        try:
            row = siblings.index(node)
        except ValueError:
            return None
        parent_idx = self._node_index_for_path(node.parent.path)
        if parent_idx is None:
            return None
        return self.index(row, 0, parent_idx)

    # ── feature: size delta ─────────────────────────────────────────────────

    def store_last_scan(self) -> None:
        self._last_scan.clear()

        def walk(node: DiskNode):
            if node.size >= 0:
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
            if not node.is_dir and node.size >= 0:
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
        base = node.children
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

    def hasChildren(self, parent: QModelIndex = QModelIndex()) -> bool:
        """Override to show expand arrow for unloaded directory stubs."""
        if not parent.isValid():
            return len(self._roots) > 0
        node: DiskNode = parent.internalPointer()
        if node.is_dir:
            # If not fully loaded, show expand arrow so user can trigger lazy load
            if not node._fully_loaded:
                return True
            # If fully loaded with children, standard behavior
            return len(self._visible_children(node)) > 0
        return False

    def canFetchMore(self, parent: QModelIndex) -> bool:
        if not parent.isValid():
            return False
        node: DiskNode = parent.internalPointer()
        return node.is_dir and not node._fully_loaded

    def fetchMore(self, parent: QModelIndex) -> None:
        """Called by QTreeView when expanding a node with canFetchMore=True.
        We handle expansion via the expanded signal directly in the module,
        so this is a no-op here."""
        pass

    def index(self, row: int, column: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if not parent.isValid():
            if 0 <= row < len(self._roots):
                return self.createIndex(row, column, self._roots[row])
            return QModelIndex()
        node: DiskNode = parent.internalPointer()
        children = self._visible_children(node)
        if 0 <= row < len(children):
            return self.createIndex(row, column, children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
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
        node: DiskNode = parent.internalPointer()
        return len(self._visible_children(node))

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
                if node.size < 0:
                    return "…"
                return format_size(node.size)
            if col == COL_PCT:
                if node.size < 0:
                    return "…"
                ps = node.parent.size if node.parent else node.size
                pct = (node.size / ps * 100) if ps > 0 else 0.0
                return f"{pct:.1f}%"
            if col == COL_FILES:
                if node.size < 0:
                    return "…"
                return str(node.file_count)
            if col == COL_MODIFIED:
                if node.last_modified:
                    return datetime.datetime.fromtimestamp(
                        node.last_modified).strftime("%Y-%m-%d %H:%M")
                return ""

        if role == Qt.ItemDataRole.UserRole:
            return node

        if role == Qt.ItemDataRole.UserRole + 1:
            return node.path in self._loading_paths

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (COL_SIZE, COL_PCT, COL_FILES):
                return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        if role == Qt.ItemDataRole.ForegroundRole:
            if node.size < 0:
                return QColor("#666666")

        return None

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        reverse = order == Qt.SortOrder.DescendingOrder

        def get_key(node: DiskNode):
            if column == COL_NAME:
                return node.name.lower()
            elif column == COL_SIZE:
                return node.size if node.size >= 0 else -1
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
