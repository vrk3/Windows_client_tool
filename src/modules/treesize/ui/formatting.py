"""Modes and units (spec 5.5).

Two orthogonal settings that together decide every number the UI shows.

**Mode** selects WHAT is measured -- size, allocated space, file count, or
percent of parent. It is pane state, not per-view state: switching mode changes
the tree bars, the chart and the size columns together.

**Unit** selects HOW a byte count is rendered, with a configurable decimal
count. Auto picks the most appropriate unit per value, which is what produces
Pro's mixed-unit columns -- one row in MB and the next in GB.

Kept free of Qt so it can be tested without a display.
"""
from enum import Enum


class Mode(str, Enum):
    SIZE = "Size"
    ALLOCATED = "Allocated space"
    FILES = "Number of files"
    PERCENT = "Percent"


class Unit(str, Enum):
    AUTO = "Auto"
    TB = "TB"
    GB = "GB"
    MB = "MB"
    KB = "KB"
    B = "B"


# Ordered largest-first; Auto walks this and takes the first that fits.
_SCALE = (
    (Unit.TB, 1024 ** 4),
    (Unit.GB, 1024 ** 3),
    (Unit.MB, 1024 ** 2),
    (Unit.KB, 1024),
    (Unit.B, 1),
)
_DIVISOR = dict(_SCALE)


def format_bytes(value: int, unit: Unit = Unit.AUTO, decimals: int = 1) -> str:
    """Render a byte count. Negative values keep their sign, for size deltas."""
    sign = "-" if value < 0 else ""
    magnitude = abs(value)

    if unit is Unit.AUTO:
        for candidate, divisor in _SCALE:
            if magnitude >= divisor:
                unit = candidate
                break
        else:
            unit = Unit.B

    divisor = _DIVISOR[unit]
    if unit is Unit.B:
        # Bytes are whole things; a fractional byte is noise, not precision.
        return f"{sign}{magnitude:,} B"
    return f"{sign}{magnitude / divisor:,.{decimals}f} {unit.value}"


def format_count(value: int) -> str:
    return f"{value:,}"


def format_percent(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def node_value(store, node: int, mode: Mode) -> float:
    """The raw number this node contributes under the current mode."""
    if mode is Mode.SIZE:
        return store.size[node]
    if mode is Mode.ALLOCATED:
        return store.alloc[node]
    if mode is Mode.FILES:
        return store.file_count[node]
    if mode is Mode.PERCENT:
        return percent_of_parent(store, node)
    raise ValueError(f"unknown mode: {mode!r}")


def percent_of_parent(store, node: int) -> float:
    """Share of the parent's size. A root, or a zero-sized parent, is 100%."""
    parent = store.parent[node]
    if not (0 <= parent < len(store)) or parent == node:
        return 100.0
    total = store.size[parent]
    if total <= 0:
        return 0.0
    return store.size[node] * 100.0 / total


def format_value(store, node: int, mode: Mode, unit: Unit = Unit.AUTO,
                 decimals: int = 1) -> str:
    """The display string for a node under the current mode and unit."""
    if mode is Mode.FILES:
        return format_count(store.file_count[node])
    if mode is Mode.PERCENT:
        return format_percent(percent_of_parent(store, node), decimals)
    return format_bytes(int(node_value(store, node, mode)), unit, decimals)


def bar_fraction(store, node: int, mode: Mode) -> float:
    """0.0-1.0 for the proportional bar drawn beside a row.

    Always relative to the parent, whatever the mode, because the bar answers
    "how much of the folder I am inside does this account for" -- the question
    Pro's bars answer.
    """
    parent = store.parent[node]
    if not (0 <= parent < len(store)) or parent == node:
        return 1.0
    if mode is Mode.FILES:
        total = store.file_count[parent]
        mine = store.file_count[node]
    elif mode is Mode.ALLOCATED:
        total = store.alloc[parent]
        mine = store.alloc[node]
    else:
        total = store.size[parent]
        mine = store.size[node]
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, mine / total))
