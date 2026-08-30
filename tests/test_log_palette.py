"""Colours the log viewer paints, in whichever theme is in force.

`ROW_COLOURS` used to be four hex values chosen against the dark sheet by
their own comment. The Log Viewer is NOT in test_theme_light_coverage's
THEME_EXEMPT set, so a colour frozen for one theme is a defect in the other.

The contrast tests iterate `slot_colour(slot, theme)` directly over
`range(COMPONENT_SLOTS)` rather than calling `component_colour(f"c{slot}", ...)`
-- `slot_for` is a byte-sum hash, so names like "c0".."c15" do NOT map to
slots 0..15. Iterating by name would leave most of the 16 palette entries
untested even though the loop looks like it covers all of them.
"""
import pytest

from modules.log_viewer import palette


def _luminance(hex_colour):
    value = hex_colour.lstrip("#")
    parts = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def channel(v):
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(p) for p in parts)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(a, b):
    first, second = _luminance(a), _luminance(b)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_component_colour_is_readable_on_itself(theme):
    for slot in range(palette.COMPONENT_SLOTS):
        background, foreground = palette.slot_colour(slot, theme)
        ratio = _contrast(foreground, background)
        assert ratio >= 4.5, (
            f"{theme}/slot {slot}: {foreground} on {background} "
            f"is {ratio:.2f}:1")


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_every_severity_colour_is_readable_on_itself(theme):
    for level in ("Error", "Warning"):
        background, foreground = palette.severity_row_colour(level, theme)
        ratio = _contrast(foreground, background)
        assert ratio >= 4.5, (
            f"{theme}/{level}: {foreground} on {background} is {ratio:.2f}:1")


def test_a_component_keeps_its_colour_across_calls_and_logs():
    """CBS must look the same in every log and after a restart, so the slot
    comes from the name, never from the order components were discovered."""
    first = palette.component_colour("CBS", "dark")
    assert palette.component_colour("CBS", "dark") == first
    assert palette.component_colour("CSI", "dark") != first


def test_an_unknown_component_still_gets_a_colour():
    background, foreground = palette.component_colour("NeverSeenBefore",
                                                      "dark")
    assert background.startswith("#") and foreground.startswith("#")


def test_a_level_with_no_colour_says_so_rather_than_guessing():
    assert palette.severity_row_colour("Info", "dark") is None


def test_the_theme_defaults_to_whatever_is_in_force():
    from core import semantic_colors

    semantic_colors.set_theme("light")
    try:
        assert palette.component_colour("CBS") == \
            palette.component_colour("CBS", "light")
    finally:
        semantic_colors.set_theme("dark")


def test_readable_text_on_clears_4_5_to_1_on_black():
    text = palette.readable_text_on("#000000")
    ratio = _contrast(text, "#000000")
    assert ratio >= 4.5, (
        f"readable_text_on('#000000') = {text} "
        f"has contrast {ratio:.2f}:1 (need 4.5:1)")


def test_readable_text_on_clears_4_5_to_1_on_white():
    text = palette.readable_text_on("#ffffff")
    ratio = _contrast(text, "#ffffff")
    assert ratio >= 4.5, (
        f"readable_text_on('#ffffff') = {text} "
        f"has contrast {ratio:.2f}:1 (need 4.5:1)")


@pytest.mark.parametrize("background", [
    "#00ff00",  # green
    "#808080",  # mid-tone gray
    "#5c1a1a",  # dark red (Error background in dark theme)
])
def test_readable_text_on_clears_4_5_to_1_on_varied_backgrounds(background):
    text = palette.readable_text_on(background)
    ratio = _contrast(text, background)
    assert ratio >= 4.5, (
        f"readable_text_on('{background}') = {text} "
        f"has contrast {ratio:.2f}:1 (need 4.5:1)")
