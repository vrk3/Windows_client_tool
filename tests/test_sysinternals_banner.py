"""The Sysinternals warning banner must be readable in both themes.

It paints its own fixed background (`#fff3cd`, pale yellow) but never set a
foreground, so the text came from the theme — and `dark.qss` says
`QLabel { color: #d4d4d4 }`. Light grey on pale yellow is about 1.3:1, which
is why the banner could not be read in dark mode.

A widget that fixes one half of a colour pair must fix the other half too;
inheriting the rest from a theme it is not participating in is the bug.
"""
import re

import pytest
from PyQt6.QtGui import QShowEvent

from modules.process_explorer.sysinternals_tab import (
    BANNER_LINK_COLOR, BANNER_STYLE, SysinternalsTab,
)


def _declared(style, prop):
    match = re.search(rf"(?:^|;)\s*{prop}\s*:\s*([^;]+)", style)
    return match.group(1).strip() if match else None


def _relative_luminance(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = channel(r), channel(g), channel(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(one, two):
    a, b = sorted((_relative_luminance(one), _relative_luminance(two)))
    return (b + 0.05) / (a + 0.05)


def test_the_contrast_helper_agrees_with_a_known_pair():
    """Guards the maths below: black on white is 21:1 by definition."""
    assert _contrast("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)


def test_banner_declares_both_halves_of_its_colour_pair():
    assert _declared(BANNER_STYLE, "background") is not None
    assert _declared(BANNER_STYLE, "color") is not None


def test_banner_text_meets_wcag_aa_against_its_own_background():
    ratio = _contrast(
        _declared(BANNER_STYLE, "color"),
        _declared(BANNER_STYLE, "background"),
    )
    assert ratio >= 4.5, f"banner text contrast is {ratio:.2f}:1, needs 4.5:1"


def test_banner_link_meets_wcag_aa_against_its_own_background():
    """The banner's call to action is a link, and it inherits too."""
    ratio = _contrast(BANNER_LINK_COLOR, _declared(BANNER_STYLE, "background"))
    assert ratio >= 4.5, f"banner link contrast is {ratio:.2f}:1, needs 4.5:1"


def test_the_tab_actually_applies_that_style(qapp):
    tab = SysinternalsTab()
    try:
        assert tab._banner.styleSheet() == BANNER_STYLE
    finally:
        tab.deleteLater()


def test_the_banner_link_carries_its_colour_inline(qapp, monkeypatch):
    """A stylesheet cannot reach it, so the markup showEvent writes must."""
    import modules.process_explorer.sysinternals_tab as tab_module

    monkeypatch.setattr(tab_module, "_is_webclient_running", lambda: False)

    tab = tab_module.SysinternalsTab()
    try:
        tab.showEvent(QShowEvent())

        assert tab._banner.isVisibleTo(tab)
        assert "start_webclient" in tab._banner.text()
        assert BANNER_LINK_COLOR in tab._banner.text()
    finally:
        tab.deleteLater()
