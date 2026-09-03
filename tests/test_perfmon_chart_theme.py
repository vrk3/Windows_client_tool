"""PerfMon's charts paint themselves, so a stylesheet cannot reach them.

`_QtLineChart.paintEvent` fills its own background and draws its own title,
axis labels and grid with literal colours. Under the light theme that left a
dark slab with dark-theme text in the middle of an otherwise light pane --
the charts were the largest part of the only pane the theme could not touch.

The colours therefore have to come from somewhere that changes with the theme,
and the widget has to be told when it does.
"""
import sys

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

QApplication.instance() or QApplication(sys.argv)

from modules.perfmon.perfmon_charts import CHART_PALETTES, _QtLineChart  # noqa: E402


def _luminance(colour: QColor) -> float:
    def channel(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(x) for x in (colour.red(), colour.green(), colour.blue()))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_both_themes_define_every_colour_the_chart_paints():
    assert set(CHART_PALETTES) == {"dark", "light"}
    assert set(CHART_PALETTES["dark"]) == set(CHART_PALETTES["light"])


@pytest.mark.parametrize("theme,background_is_light", [("dark", False), ("light", True)])
def test_chart_background_follows_the_theme(theme, background_is_light):
    chart = _QtLineChart("CPU", "%")
    chart.set_theme(theme)
    background = QColor(chart.colours["background"])
    assert (_luminance(background) > 0.5) is background_is_light


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_chart_text_stays_readable_against_its_own_background(theme):
    """The bug this replaces was dark-theme text left on a light pane."""
    palette = CHART_PALETTES[theme]
    background = QColor(palette["background"])
    for key in ("title", "axis"):
        foreground = QColor(palette[key])
        pair = sorted((_luminance(background), _luminance(foreground)))
        ratio = (pair[1] + 0.05) / (pair[0] + 0.05)
        assert ratio >= 4.5, f"{theme}/{key} is {ratio:.2f}:1 on its own background"


def test_a_chart_defaults_to_dark_so_nothing_paints_uncoloured():
    assert _QtLineChart("CPU", "%").colours == CHART_PALETTES["dark"]
