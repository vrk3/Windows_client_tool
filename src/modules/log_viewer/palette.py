"""Colours the log viewer paints, resolved for the theme in force.

Three colour systems share a row and must not hide one another: severity owns
the row background, a highlight rule overrides it, and the component tint owns
the Component column and nothing else.

Component colours are GENERATED from evenly spaced hues rather than written
out as 64 hand-picked hex values. Hand-picking would be guesswork checked by
eye; this is deterministic, and `tests/test_log_palette.py` computes the
contrast ratio of all 32 pairs instead of trusting a comment.

The slot comes from a hash of the component name, not from the order names
were discovered, so CBS is the same colour in every log and after a restart,
and a new component appearing does not reshuffle the others. The measured
maximum on this machine is 15 distinct components, so a collision is a
cosmetic repeat rather than a practical concern.

`slot_colour` is the primitive the tests use to cover all 16 slots directly --
`slot_for` is a byte-sum hash, so component names do NOT map onto slots
0..COMPONENT_SLOTS-1 in order, and testing only by name would silently leave
most slots unchecked. `component_colour` is `slot_colour(slot_for(name), ...)`
and is what callers outside this module use.

No Qt here: the model wraps these in QColor. That is what lets the contrast
be asserted with no display.
"""
import colorsys
from typing import Optional, Tuple

from core.semantic_colors import current_theme

#: Enough for the 15 distinct components measured across this machine's logs.
COMPONENT_SLOTS = 16

#: (saturation, lightness) for the tint and for the text on it, per theme.
#: Tuned until every one of the 32 pairs clears 4.5:1; the test is what says
#: whether a change to these still does.
_COMPONENT_TONES = {
    "dark": ((0.45, 0.20), (0.70, 0.80)),
    "light": ((0.50, 0.88), (0.85, 0.22)),
}

#: Severity owns the whole row, so these are row backgrounds with the text
#: that sits on them -- a different job from `semantic_colors`, which colours
#: a word rather than a band.
SEVERITY_ROW_COLOURS = {
    "dark": {
        "Error": ("#5c1a1a", "#ff9999"),
        "Warning": ("#4a3c14", "#f5d576"),
    },
    "light": {
        "Error": ("#ffe3e0", "#8c1d18"),
        "Warning": ("#fff3d6", "#6b4400"),
    },
}


def _hex(hue_index: int, saturation: float, lightness: float) -> str:
    hue = (hue_index % COMPONENT_SLOTS) / COMPONENT_SLOTS
    red, green, blue = colorsys.hls_to_rgb(hue, lightness, saturation)
    return "#{:02x}{:02x}{:02x}".format(
        int(red * 255), int(green * 255), int(blue * 255))


def _theme(theme: Optional[str]) -> str:
    name = theme or current_theme()
    return name if name in _COMPONENT_TONES else "dark"


def slot_for(name: str) -> int:
    """A stable slot for `name`.

    `hash()` is salted per process since Python 3.3, so it would give a
    component a different colour on every launch. A sum of the bytes is
    stable, and for a dozen short names it spreads them well enough.
    """
    return sum(name.encode("utf-8")) % COMPONENT_SLOTS


def slot_colour(slot: int, theme: str = None) -> Tuple[str, str]:
    """`(background, foreground)` for `slot` directly.

    This is the primitive `component_colour` is built on, and the one the
    contrast tests call over `range(COMPONENT_SLOTS)` so every slot -- not
    just whichever ones a handful of test names happen to hash to -- is
    actually measured.
    """
    tint, text = _COMPONENT_TONES[_theme(theme)]
    return _hex(slot, *tint), _hex(slot, *text)


def component_colour(name: str, theme: str = None) -> Tuple[str, str]:
    """`(background, foreground)` for a component's cell."""
    return slot_colour(slot_for(name), theme)


def severity_row_colour(level: str, theme: str = None):
    """`(background, foreground)` for a row, or None when the level has no
    colour of its own -- Info and Debug are deliberately plain, because a log
    where every row is coloured is a log with no colour."""
    return SEVERITY_ROW_COLOURS[_theme(theme)].get(level)


def readable_text_on(background_hex: str) -> str:
    """Return a text colour (#hex) that contrasts well with an arbitrary
    background colour, using WCAG relative-luminance math to pick light or
    dark ink. Guarantees 4.5:1 contrast or better.

    The user picks highlight rule colours from a colour dialog, so this must
    work on ANY hex colour, not a fixed set of known backgrounds.
    """
    def _luminance(hex_colour):
        value = hex_colour.lstrip("#")
        parts = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        def channel(v):
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        red, green, blue = (channel(p) for p in parts)
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    # Light and dark ink candidates that must clear 4.5:1 on any background
    light_ink = "#ffffff"
    dark_ink = "#000000"

    # Threshold computed from the WCAG contrast formula. Both white (#ffffff)
    # and black (#000000) achieve 4.5:1 contrast on backgrounds near 0.179;
    # below that threshold white text works, above it black text works.
    bg_luminance = _luminance(background_hex)
    return light_ink if bg_luminance < 0.179 else dark_ink
