"""Squarified treemap layout (spec 5.8).

Pure geometry, no Qt, so the layout can be computed off the UI thread and
tested without a display.

Squarified rather than slice-and-dice because slice-and-dice degenerates into
unreadable slivers as soon as one child dominates -- which on a real disk is
always. The algorithm (Bruls, Huizing, van Wijk) fills a strip along the
shorter side, adding rectangles while the worst aspect ratio in the strip keeps
improving, then starts a new strip in the remaining space.

Rectangles are flattened into one list and hit-tested through a uniform spatial
grid, so hover and click stay responsive at tens of thousands of rects rather
than degrading linearly.
"""
from dataclasses import dataclass

from .formatting import Mode, weight_value


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float
    node: int
    depth: int

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h


def _worst_ratio(areas, length: float, total: float) -> float:
    """Worst aspect ratio in a strip of `areas` laid along `length`."""
    if not areas or length <= 0 or total <= 0:
        return float("inf")
    side = total / length
    return max(max(side / (a / side), (a / side) / side) if a > 0 else float("inf")
               for a in areas)


def squarify(values, x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Lay `values` out in the given box, returning one (x, y, w, h) each.

    Values must be positive and are laid out in the order given -- the caller
    sorts, because sort order is a display decision.
    """
    result: list[tuple[float, float, float, float]] = [None] * len(values)  # type: ignore
    order = [i for i, v in enumerate(values) if v > 0]
    if not order or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0) for _ in values]

    total_value = sum(values[i] for i in order)
    if total_value <= 0:
        return [(x, y, 0.0, 0.0) for _ in values]
    scale = (w * h) / total_value

    remaining = list(order)
    cx, cy, cw, ch = x, y, w, h
    while remaining:
        length = min(cw, ch)
        strip: list[int] = []
        strip_areas: list[float] = []
        strip_total = 0.0
        while remaining:
            candidate = values[remaining[0]] * scale
            current = _worst_ratio(strip_areas, length, strip_total)
            widened = _worst_ratio(strip_areas + [candidate], length,
                                   strip_total + candidate)
            if strip and widened > current:
                break
            strip.append(remaining.pop(0))
            strip_areas.append(candidate)
            strip_total += candidate

        # Lay the strip along the shorter side, then shrink the free box.
        if cw >= ch:
            strip_width = strip_total / ch if ch > 0 else 0.0
            offset = cy
            for index, area in zip(strip, strip_areas):
                height = area / strip_width if strip_width > 0 else 0.0
                result[index] = (cx, offset, strip_width, height)
                offset += height
            cx += strip_width
            cw -= strip_width
        else:
            strip_height = strip_total / cw if cw > 0 else 0.0
            offset = cx
            for index, area in zip(strip, strip_areas):
                width = area / strip_height if strip_height > 0 else 0.0
                result[index] = (offset, cy, width, strip_height)
                offset += width
            cy += strip_height
            ch -= strip_height

    for i, value in enumerate(values):
        if result[i] is None:
            result[i] = (x, y, 0.0, 0.0)
    return result


MIN_TILE = 3.0          # below this a rect is not worth recursing into


def build_treemap(store, root: int, width: float, height: float,
                  max_depth: int = 6, min_tile: float = MIN_TILE,
                  mode: Mode = Mode.SIZE) -> list[Rect]:
    """Flatten a subtree into drawable rectangles, parents before children.

    Recursion stops at `max_depth` or when a tile is too small to show
    anything useful -- without that a full C:\\ builds millions of sub-pixel
    rectangles that nobody can see and every one of which must be hit-tested.

    `mode` is spec 5.5's pane mode: it decides what area MEANS here, exactly
    as it decides what the tree bars mean. Weighting by size regardless of it
    redrew an identical picture when the user asked for allocated space, on a
    volume where the two differ by 240 GB.
    """
    from ..store.node_store import DIR, EXCLUDED

    out: list[Rect] = []
    stack = [(root, x_y_w_h := (0.0, 0.0, width, height), 0)]
    out.append(Rect(0.0, 0.0, width, height, root, 0))
    while stack:
        node, (x, y, w, h), depth = stack.pop()
        if depth >= max_depth or w < min_tile or h < min_tile:
            continue
        if not (store.attrs[node] & DIR):
            continue
        kids = [c for c in store.children(node)
                if not (store.attrs[c] & EXCLUDED)
                and weight_value(store, c, mode) > 0]
        if not kids:
            continue
        kids.sort(key=lambda n: weight_value(store, n, mode), reverse=True)
        values = [weight_value(store, n, mode) for n in kids]
        # Inset by one pixel so a child never sits flush against its parent's
        # border; that gap is what makes nesting legible at a glance.
        boxes = squarify(values, x + 1, y + 1, max(0.0, w - 2), max(0.0, h - 2))
        for child, box in zip(kids, boxes):
            if box[2] <= 0 or box[3] <= 0:
                continue
            out.append(Rect(box[0], box[1], box[2], box[3], child, depth + 1))
            stack.append((child, box, depth + 1))
    return out


class HitGrid:
    """Uniform spatial grid over the rects, for O(1)-ish hit testing.

    A linear scan is fine at a hundred rects and unusable at fifty thousand,
    which is what a real treemap holds. Deepest match wins, so hovering a small
    child does not report its parent.
    """

    def __init__(self, rects: list[Rect], width: float, height: float,
                 cells: int = 64) -> None:
        self.rects = rects
        self.width = max(width, 1.0)
        self.height = max(height, 1.0)
        self.cells = max(1, cells)
        self._grid: dict[tuple[int, int], list[int]] = {}
        for i, rect in enumerate(rects):
            for cx in range(self._col(rect.x), self._col(rect.x + rect.w) + 1):
                for cy in range(self._row(rect.y), self._row(rect.y + rect.h) + 1):
                    self._grid.setdefault((cx, cy), []).append(i)

    def _col(self, x: float) -> int:
        return max(0, min(self.cells - 1, int(x / self.width * self.cells)))

    def _row(self, y: float) -> int:
        return max(0, min(self.cells - 1, int(y / self.height * self.cells)))

    def hit(self, x: float, y: float) -> Rect | None:
        best: Rect | None = None
        for i in self._grid.get((self._col(x), self._row(y)), ()):
            rect = self.rects[i]
            if rect.contains(x, y) and (best is None or rect.depth > best.depth):
                best = rect
        return best
