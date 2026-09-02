"""One way to render a byte count.

There were five: `format_size` (cleanup), `human_size` (store apps),
`format_bytes` (TreeSize) and `_fmt_size` twice in Updates. They agreed
above 1 KB and disagreed below it — `0.0 B` from three of them, `0 B` from
the other two — so the same folder could read differently in two panes.

This is TreeSize's, which was the most complete: it selects a unit per
value (Pro's mixed-unit columns, one row in MB and the next in GB), takes a
decimal count, and keeps the sign so it can render a size delta. No Qt, so
it is testable without a display.
"""
from enum import Enum


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


#: The name the cleanup scanners and Updates used.
def format_size(size: int) -> str:
    """A byte count at one decimal place, auto-scaled."""
    return format_bytes(size)


def human_size(size: int) -> str:
    """A byte count, or "n/a" for a negative one.

    Store Apps uses a NEGATIVE size to mean "too large to scan" — an
    AppX package whose size could not be measured. That is a different
    thing from a size of zero and must not be shown as one, so this is a
    distinct function rather than an alias for format_size. (TreeSize does
    use real negatives, for size deltas, which is why format_bytes keeps
    the sign.)
    """
    if size < 0:
        return "n/a"
    return format_bytes(size)
