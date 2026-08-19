"""Chart view: treemap, with a breadcrumb (spec 5.8).

Layout is computed in `treemap.py`, which knows nothing about Qt. This file
paints it and handles interaction: hover highlights, click selects in the tree,
double-click drills in, and the breadcrumb tracks depth.

Cushion shading gives each tile a lit dome so nesting reads as depth rather
than as a flat mosaic. It is a per-tile linear gradient rather than a real
per-pixel cushion: at tens of thousands of tiles the difference is invisible
and the cost is not.
"""
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ...store.node_store import DIR
from ..formatting import format_bytes
from ..treemap import HitGrid, build_treemap

# One hue per top-level branch, cycled. Chosen for even spacing round the wheel
# and equal-ish perceived lightness, so no branch looks more important than
# another purely because of its colour.
PALETTE = (
    QColor(0x4E, 0x79, 0xA7), QColor(0xF2, 0x8E, 0x2B), QColor(0xE1, 0x57, 0x59),
    QColor(0x76, 0xB7, 0xB2), QColor(0x59, 0xA1, 0x4F), QColor(0xED, 0xC9, 0x48),
    QColor(0xB0, 0x7A, 0xA1), QColor(0xFF, 0x9D, 0xA7), QColor(0x9C, 0x75, 0x5F),
)
LABEL_MIN_W = 46
LABEL_MIN_H = 15


class TreemapWidget(QWidget):
    node_clicked = pyqtSignal(int)
    node_drilled = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._store = None
        self._root = -1
        self._rects: list = []
        self._grid: HitGrid | None = None
        self._hover = -1
        self._colors: dict[int, QColor] = {}
        self.max_depth = 6

    def set_scan(self, store, root: int) -> None:
        self._store = store
        self._root = root
        self._colors.clear()
        self._rebuild()

    def _rebuild(self) -> None:
        if self._store is None or self._root < 0 or self.width() < 4:
            self._rects, self._grid = [], None
            self.update()
            return
        self._rects = build_treemap(self._store, self._root,
                                    float(self.width()), float(self.height()),
                                    max_depth=self.max_depth)
        self._grid = HitGrid(self._rects, float(self.width()), float(self.height()))
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild()

    def _color_for(self, rect) -> QColor:
        """Colour by top-level ancestor, darkened with depth.

        Sharing a hue down a branch is what lets the eye follow a folder's
        subtree without reading a single label.
        """
        store = self._store
        node = rect.node
        ancestor = node
        while (store.parent[ancestor] not in (-1, self._root)
               and 0 <= store.parent[ancestor] < len(store)):
            ancestor = store.parent[ancestor]
        base = self._colors.get(ancestor)
        if base is None:
            base = PALETTE[len(self._colors) % len(PALETTE)]
            self._colors[ancestor] = base
        return base.darker(100 + 12 * max(0, rect.depth - 1))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor(0x1F, 0x1F, 0x1F))
        if not self._rects:
            painter.setPen(QColor(0x9D, 0x9D, 0x9D))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "No scan")
            return
        metrics = QFontMetrics(painter.font())
        for rect in self._rects:
            if rect.depth == 0 or rect.w < 1 or rect.h < 1:
                continue
            box = QRectF(rect.x, rect.y, rect.w, rect.h)
            color = self._color_for(rect)
            # Cushion shading: a light-to-dark gradient across the tile reads
            # as a lit dome, which is what makes nesting legible.
            gradient = QLinearGradient(box.topLeft(), box.bottomRight())
            gradient.setColorAt(0.0, color.lighter(125))
            gradient.setColorAt(1.0, color.darker(120))
            painter.fillRect(box, gradient)
            if rect.node == self._hover:
                painter.setPen(QPen(QColor(0xFF, 0xFF, 0xFF), 2))
                painter.drawRect(box.adjusted(1, 1, -1, -1))
            elif rect.w > 3 and rect.h > 3:
                painter.setPen(QPen(color.darker(160), 1))
                painter.drawRect(box)
            if rect.w >= LABEL_MIN_W and rect.h >= LABEL_MIN_H:
                painter.setPen(QColor(0xFF, 0xFF, 0xFF))
                name = self._store.name(rect.node)
                painter.drawText(box.adjusted(3, 1, -2, -1),
                                 int(Qt.AlignmentFlag.AlignLeft
                                     | Qt.AlignmentFlag.AlignTop),
                                 metrics.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                                    int(rect.w) - 6))

    def mouseMoveEvent(self, event):
        hit = self._grid.hit(event.position().x(), event.position().y()) if self._grid else None
        node = hit.node if hit else -1
        if node != self._hover:
            self._hover = node
            if node >= 0 and self._store is not None:
                self.setToolTip(f"{self._store.path(node)}\n"
                                f"{format_bytes(self._store.size[node])}")
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.setToolTip("")
        self.update()

    def mousePressEvent(self, event):
        hit = self._grid.hit(event.position().x(), event.position().y()) if self._grid else None
        if hit:
            self.node_clicked.emit(hit.node)

    def mouseDoubleClickEvent(self, event):
        hit = self._grid.hit(event.position().x(), event.position().y()) if self._grid else None
        if hit and self._store is not None and self._store.attrs[hit.node] & DIR:
            self.node_drilled.emit(hit.node)


class ChartView(QWidget):
    """Treemap plus the breadcrumb that tracks drill depth."""

    node_clicked = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._store = None
        self._trail: list[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        crumb_bar = QWidget(self)
        self._crumbs = QHBoxLayout(crumb_bar)
        self._crumbs.setContentsMargins(6, 2, 6, 2)
        self._crumbs.setSpacing(2)
        layout.addWidget(crumb_bar)

        self.treemap = TreemapWidget(self)
        layout.addWidget(self.treemap, 1)
        self.treemap.node_clicked.connect(self.node_clicked)
        self.treemap.node_drilled.connect(self.drill_to)

    def set_scan(self, store, root: int) -> None:
        self._store = store
        self._trail = [root] if root >= 0 else []
        self.treemap.set_scan(store, root)
        self._rebuild_crumbs()

    def drill_to(self, node: int) -> None:
        if self._store is None:
            return
        if node in self._trail:
            self._trail = self._trail[:self._trail.index(node) + 1]
        else:
            self._trail.append(node)
        self.treemap.set_scan(self._store, node)
        self._rebuild_crumbs()
        self.node_clicked.emit(node)

    def _rebuild_crumbs(self) -> None:
        while self._crumbs.count():
            item = self._crumbs.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for depth, node in enumerate(self._trail):
            if depth:
                self._crumbs.addWidget(QLabel("›"))
            button = QPushButton(self._store.name(node) if self._store else "")
            button.setFlat(True)
            button.setObjectName("breadcrumb")
            button.clicked.connect(lambda _checked=False, n=node: self.drill_to(n))
            self._crumbs.addWidget(button)
        self._crumbs.addStretch(1)
