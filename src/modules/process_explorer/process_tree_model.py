from __future__ import annotations
from typing import Dict, List

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.color_scheme import get_row_color

# Column indices
COL_NAME  = 0
COL_PID   = 1
COL_CPU   = 2
COL_RAM   = 3
COL_DISK_R = 4
COL_DISK_W = 5
COL_NET_IN = 6
COL_NET_OUT = 7
COL_GPU   = 8
COL_USER  = 9
COL_PATH  = 10

COLUMNS = ["Name", "PID", "CPU%", "RAM", "Disk R", "Disk W",
           "Net In", "Net Out", "GPU%", "User", "Path"]


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024**2:
        return f"{n/1024:.1f}K"
    if n < 1024**3:
        return f"{n/1024**2:.1f}M"
    return f"{n/1024**3:.1f}G"


class ProcessTreeModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot: Dict[int, ProcessNode] = {}
        self._roots: List[ProcessNode] = []
        self._flat_mode = False

    # ── Public API ────────────────────────────────────────────────────

    def load_snapshot(self, snapshot: Dict[int, ProcessNode]):
        self.beginResetModel()
        self._snapshot = snapshot
        self._roots = [n for n in snapshot.values()
                       if n.parent_pid not in snapshot or n.parent_pid == n.pid]
        self.endResetModel()

    def set_flat_mode(self, flat: bool):
        self.beginResetModel()
        self._flat_mode = flat
        self.endResetModel()

    def update_nodes(self, changed: Dict[int, ProcessNode]):
        """Update metrics for changed pids and emit dataChanged."""
        for pid, new_node in changed.items():
            if pid not in self._snapshot:
                continue
            old = self._snapshot[pid]
            old.cpu_percent    = new_node.cpu_percent
            old.memory_rss     = new_node.memory_rss
            old.memory_vms     = new_node.memory_vms
            old.disk_read_bps  = new_node.disk_read_bps
            old.disk_write_bps = new_node.disk_write_bps
            old.net_send_bps   = new_node.net_send_bps
            old.net_recv_bps   = new_node.net_recv_bps
            old.gpu_percent    = new_node.gpu_percent
            old.status         = new_node.status

        if changed:
            if self._flat_mode:
                count = len(self._snapshot)
                if count > 0:
                    top_left = self.index(0, 0)
                    bot_right = self.index(count - 1, len(COLUMNS) - 1)
                    self.dataChanged.emit(top_left, bot_right)
            else:
                # Emit per-node so child rows are included, not just roots
                for pid in changed:
                    node = self._snapshot.get(pid)
                    if node is None:
                        continue
                    parent_node = self._snapshot.get(node.parent_pid)
                    siblings = (parent_node.children
                                if parent_node and parent_node.pid != node.pid
                                else self._roots)
                    try:
                        row = siblings.index(node)
                    except ValueError:
                        continue
                    tl = self.createIndex(row, 0, node)
                    br = self.createIndex(row, len(COLUMNS) - 1, node)
                    self.dataChanged.emit(tl, br)

    # ── QAbstractItemModel required overrides ─────────────────────────

    def rowCount(self, parent: QModelIndex = None) -> int:
        if parent is None:
            parent = QModelIndex()
        if self._flat_mode:
            if not parent.isValid():
                return len(self._snapshot)
            return 0
        if not parent.isValid():
            return len(self._roots)
        node: ProcessNode = parent.internalPointer()
        return len(node.children)

    def columnCount(self, parent: QModelIndex = None) -> int:
        if parent is None:
            parent = QModelIndex()
        return len(COLUMNS)

    def index(self, row: int, col: int, parent: QModelIndex = None) -> QModelIndex:
        if parent is None:
            parent = QModelIndex()
        if self._flat_mode:
            nodes = list(self._snapshot.values())
            if 0 <= row < len(nodes):
                return self.createIndex(row, col, nodes[row])
            return QModelIndex()

        if not parent.isValid():
            if 0 <= row < len(self._roots):
                return self.createIndex(row, col, self._roots[row])
        else:
            p_node: ProcessNode = parent.internalPointer()
            if 0 <= row < len(p_node.children):
                return self.createIndex(row, col, p_node.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid() or self._flat_mode:
            return QModelIndex()
        node: ProcessNode = index.internalPointer()
        parent_node = self._snapshot.get(node.parent_pid)
        if parent_node is None or parent_node is node:
            return QModelIndex()
        grandparent = self._snapshot.get(parent_node.parent_pid)
        siblings = grandparent.children if grandparent else self._roots
        try:
            row = siblings.index(parent_node)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, parent_node)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: ProcessNode = index.internalPointer()
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return [
                node.name, str(node.pid),
                f"{node.cpu_percent:.1f}", _fmt_bytes(node.memory_rss),
                _fmt_bytes(int(node.disk_read_bps)), _fmt_bytes(int(node.disk_write_bps)),
                _fmt_bytes(int(node.net_recv_bps)), _fmt_bytes(int(node.net_send_bps)),
                f"{node.gpu_percent:.1f}", node.user, node.exe,
            ][col]

        if role == Qt.ItemDataRole.BackgroundRole:
            color = get_row_color(node)
            if color.alpha() > 0:
                return color
            return None

        if role == Qt.ItemDataRole.ToolTipRole and col == COL_NAME:
            return node.exe

        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None
