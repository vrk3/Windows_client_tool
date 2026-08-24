"""Colours that mean something, resolved for whichever theme is in force.

A pane that writes `#4ec9b0` has picked a colour for the dark theme and frozen
it. That reads 7.7:1 on the dark pane and 1.98:1 on the light one, so the light
theme got a pale smear where the dark theme got a clear "OK". The fix is the
same one the stylesheets use: name the MEANING, let the theme choose.

Kept out of the .qss files on purpose. These are applied from Python at moments
a stylesheet cannot express -- a table cell's foreground that depends on a
reading, a status word that changes as a job runs -- so they need to be
callable, not declarative.

Every value here is held to 4.5:1 against its own theme's pane background by
`tests/test_semantic_colors.py`, which computes the ratios rather than
trusting this comment.
"""
from typing import Dict

#: What each theme paints a pane, and therefore what these colours sit on.
PANE_BACKGROUND: Dict[str, str] = {
    "dark": "#1e1e1e",
    "light": "#f5f5f5",
}

SEMANTIC_PALETTES: Dict[str, Dict[str, str]] = {
    "dark": {
        "success": "#4ec9b0",
        "warning": "#e5c07b",
        "error": "#f44747",
        "info": "#4fc3f7",
    },
    # Darkened rather than recoloured: the same hues, taken down until they
    # clear 4.5:1 on a light pane. A light-theme "OK" should still read green.
    "light": {
        "success": "#00695c",
        "warning": "#8a5300",
        "error": "#b3261e",
        "info": "#00639c",
    },
}

_current_theme = "dark"


def set_theme(theme: str) -> None:
    """Follow `theme`. Unknown names are ignored -- the palette in force stays,
    which is better than blanking every status colour in the app."""
    global _current_theme
    if theme in SEMANTIC_PALETTES:
        _current_theme = theme


def current_theme() -> str:
    return _current_theme


def semantic(meaning: str) -> str:
    """The colour for `meaning` in the current theme.

    Raises KeyError on an unknown meaning: a typo that silently returned
    nothing would paint invisible text, which is the bug this module exists
    to stop.
    """
    return SEMANTIC_PALETTES[_current_theme][meaning]
