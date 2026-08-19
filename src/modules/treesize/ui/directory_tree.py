"""Directory tree view and its proportional-bar delegate (spec 5.4).

Each row shows the value, a proportional bar, an icon, and the name -- Pro's
arrangement. The bar is painted by a QStyledItemDelegate rather than being a
widget per row, because a widget per row does not survive a large scan.
"""
from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTreeView,
)

from .tree_model import BarFractionRole, COLUMN_VALUE, DirectoryTreeModel, NodeIndexRole

# Sampled from Pro's dark scheme; the light sheet overrides via set_bar_colors.
BAR_FILL = QColor(0x3D, 0x8B, 0xD4)
BAR_TRACK = QColor(0x2A, 0x2D, 0x2E)
BAR_HEIGHT = 6
BAR_MARGIN = 4


class ProportionBarDelegate(QStyledItemDelegate):
    """Paints the value text with a proportional bar beneath it."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fill = BAR_FILL
        self._track = BAR_TRACK

    def set_bar_colors(self, fill: QColor, track: QColor) -> None:
        self._fill = fill
        self._track = track

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex):
        """Reserve room beneath the text so the bar is not drawn through it."""
        size = super().sizeHint(option, index)
        size.setHeight(size.height() + BAR_HEIGHT + 2)
        return size

    def paint(self, painter: QPainter, option: QStyleOptionViewItem,
              index: QModelIndex) -> None:
        # Text occupies everything above the bar strip; the bar gets the rest.
        # Painting both into the same rect leaves the number sitting on top of
        # its own bar, which is unreadable at small sizes.
        text_option = QStyleOptionViewItem(option)
        text_option.rect = option.rect.adjusted(0, 0, 0, -(BAR_HEIGHT + 1))
        super().paint(painter, text_option, index)
        fraction = index.data(BarFractionRole)
        if fraction is None:
            return
        bar = option.rect.adjusted(BAR_MARGIN, 0, -BAR_MARGIN, -2)
        bar.setTop(bar.bottom() - BAR_HEIGHT)
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track)
        painter.drawRect(bar)
        filled = int(bar.width() * max(0.0, min(1.0, float(fraction))))
        if filled > 0:
            painter.setBrush(self._fill)
            painter.drawRect(bar.x(), bar.y(), filled, bar.height())
        painter.restore()


class DirectoryTree(QTreeView):
    """The left-hand tree. Emits the store node index on selection."""

    node_selected = pyqtSignal(int)
    node_activated = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._model = DirectoryTreeModel(self)
        self.setModel(self._model)
        self._delegate = ProportionBarDelegate(self)
        self.setItemDelegateForColumn(COLUMN_VALUE, self._delegate)

        self.setUniformRowHeights(True)          # required for large models
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSortingEnabled(True)
        self.setAlternatingRowColors(False)
        self.setExpandsOnDoubleClick(False)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.header().setStretchLastSection(False)
        self.setColumnWidth(0, 320)

        self.selectionModel().currentChanged.connect(self._on_current_changed)
        self.doubleClicked.connect(self._on_double_clicked)

    @property
    def tree_model(self) -> DirectoryTreeModel:
        return self._model

    def set_scan(self, store, root: int) -> None:
        self._model.set_scan(store, root)
        top = self._model.index(0, 0, QModelIndex())
        if top.isValid():
            self.expand(top)
            self.setCurrentIndex(top)

    def selected_node(self) -> int:
        index = self.currentIndex()
        if not index.isValid():
            return -1
        value = index.data(NodeIndexRole)
        return -1 if value is None else int(value)

    def _on_current_changed(self, current: QModelIndex, _previous) -> None:
        if current.isValid():
            value = current.data(NodeIndexRole)
            if value is not None:
                self.node_selected.emit(int(value))

    def _on_double_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        value = index.data(NodeIndexRole)
        if value is not None:
            self.node_activated.emit(int(value))
        self.setExpanded(index, not self.isExpanded(index))
