"""Details view (spec 5.8) — the table in the product screenshots.

Columns: Name, Size, Allocated, Files, Folders, % of Parent (with an inline
proportional bar), Last Modified, Last Accessed, Owner.

Shows the children of the selected node, not the whole tree: it is the
right-hand companion to the directory tree, and the tree is what does depth.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QHeaderView, QTreeWidget, QTreeWidgetItem,
)

from ...store.node_store import DIR, EXCLUDED
from ..directory_tree import ProportionBarDelegate
from ..formatting import Mode, Unit, format_bytes, format_count, percent_of_parent
from ..panels import format_filetime
from ..tree_model import BarFractionRole

COLUMNS = ("Name", "Size", "Allocated", "Files", "Folders", "% of Parent",
           "Last Modified", "Last Accessed", "Owner")
SIZE_COLUMN = 1
PERCENT_COLUMN = 5
SortValueRole = int(Qt.ItemDataRole.UserRole) + 10


class DetailsItem(QTreeWidgetItem):
    """Sorts on the underlying number, not the formatted string.

    Sorting the display text puts "9 B" above "10 GB" and "1.0 TB" below
    "999 MB" -- the classic size-column bug, and immediately obvious to anyone
    who uses the real product.
    """

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() else 0
        mine = self.data(column, SortValueRole)
        theirs = other.data(column, SortValueRole)
        if mine is not None and theirs is not None:
            return mine < theirs
        return self.text(column).lower() < other.text(column).lower()


class DetailsView(QTreeWidget):
    node_activated = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(list(COLUMNS))
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setItemDelegateForColumn(PERCENT_COLUMN, ProportionBarDelegate(self))
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._store = None
        self._unit = Unit.AUTO
        self._decimals = 1
        self.itemDoubleClicked.connect(self._on_double_clicked)
        # Largest first, matching the tree and the product.
        self.sortByColumn(SIZE_COLUMN, Qt.SortOrder.DescendingOrder)

    def set_unit(self, unit: Unit, decimals: int | None = None) -> None:
        self._unit = unit
        if decimals is not None:
            self._decimals = decimals

    def show_children_of(self, store, node: int) -> None:
        self.clear()
        self._store = store
        if store is None or not (0 <= node < len(store)):
            return
        # Sorting is suspended while filling: re-sorting per insertion is
        # quadratic, and a folder with 40,000 children is ordinary.
        self.setSortingEnabled(False)
        for child in store.children(node):
            if store.attrs[child] & EXCLUDED:
                continue
            self.addTopLevelItem(self._row(store, child))
        self.setSortingEnabled(True)

    def _row(self, store, node: int) -> QTreeWidgetItem:
        percent = percent_of_parent(store, node)
        item = DetailsItem([
            store.name(node),
            format_bytes(store.size[node], self._unit, self._decimals),
            format_bytes(store.alloc[node], self._unit, self._decimals),
            format_count(store.file_count[node]) if store.attrs[node] & DIR else "",
            format_count(store.folder_count[node]) if store.attrs[node] & DIR else "",
            f"{percent:.1f}%",
            format_filetime(store.mtime[node]),
            format_filetime(store.atime[node]),
            store.owner(store.owner_id[node]) or "",
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, node)
        item.setData(PERCENT_COLUMN, BarFractionRole, percent / 100.0)
        item.setData(SIZE_COLUMN, SortValueRole, store.size[node])
        item.setData(2, SortValueRole, store.alloc[node])
        item.setData(3, SortValueRole, store.file_count[node])
        item.setData(4, SortValueRole, store.folder_count[node])
        item.setData(PERCENT_COLUMN, SortValueRole, percent)
        item.setData(6, SortValueRole, store.mtime[node])
        item.setData(7, SortValueRole, store.atime[node])
        for column in range(1, len(COLUMNS)):
            item.setTextAlignment(column, Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
        return item

    def _on_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        node = item.data(0, Qt.ItemDataRole.UserRole)
        if node is not None:
            self.node_activated.emit(int(node))
