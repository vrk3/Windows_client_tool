"""The category legend must be readable in whichever theme is in force.

`_SliceCard` wrote its label colour into the markup -- `<span
style='color:#e0e0e0'>` -- which no stylesheet can reach, so it stayed a
dark-theme grey forever. That was invisible the moment the card stopped
painting itself dark: #e0e0e0 on #f5f5f5 is 1.1:1.

Measured on the rendered widget, because the point is what reaches the screen.
"""
import sys

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication

QApplication.instance() or QApplication(sys.argv)

from modules.cleanup.components.quick_cleanup_tab import _SliceCard


def _luminance(colour: QColor) -> float:
    def channel(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(x) for x in (colour.red(), colour.green(), colour.blue()))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: QColor, b: QColor) -> float:
    low, high = sorted((_luminance(a), _luminance(b)))
    return (high + 0.05) / (low + 0.05)


def _render_label_region(theme_qss: str):
    """Just the category-name label's rectangle.

    Measuring the whole card passes on the strength of its OTHER text -- the
    size, which is already themed -- and says nothing about the label. The
    coloured dot would fool it too. Crop to the one widget under test.
    """
    qapp = QApplication.instance()
    previous = qapp.styleSheet()
    qapp.setStyleSheet(theme_qss)
    card = _SliceCard("Temp Files", 0, "#4fc3f7")
    card.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    card.resize(320, 40)
    card.show()
    qapp.processEvents()
    # Grab the label WIDGET, not a crop of the card: a crop still contains
    # the category's colour swatch, which is the most contrasting thing in the
    # card and would answer for text it says nothing about.
    image = card._lbl.grab().toImage()
    qapp.setStyleSheet(previous)
    return image


def _background_and_darkest_ink(image):
    """The card's own background, and the most extreme text pixel on it."""
    from collections import Counter
    counts = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            counts[image.pixel(x, y)] += 1
    background = QColor(counts.most_common(1)[0][0])
    # The glyph cores sit furthest from the background in luminance.
    ink = max((QColor(p) for p in counts),
              key=lambda c: abs(_luminance(c) - _luminance(background)))
    return background, ink


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_legend_label_is_readable_on_its_own_card(theme):
    import os
    qss = open(os.path.join(os.path.dirname(__file__), "..", "src", "ui",
                            "styles", f"{theme}.qss"), encoding="utf-8").read()
    background, ink = _background_and_darkest_ink(_render_label_region(qss))
    ratio = _contrast(background, ink)
    assert ratio >= 4.5, (
        f"{theme}: the legend card's text reaches only {ratio:.2f}:1 against "
        f"its own background ({ink.name()} on {background.name()})"
    )
