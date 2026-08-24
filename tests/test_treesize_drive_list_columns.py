"""The drive list must not clip its own columns.

At the width the TreeSize splitter actually gives this panel, the four columns
added up to more than the viewport and the last one was cut: `% Free` rendered
as `93.6'`, the per-cent sign sliced off. Three fixed 100px columns plus a
minimum for Name overflow anything narrower than about 500px, and the default
layout puts the panel at 375-460px.

Measured across the range the splitter can produce, not at one convenient size.
"""
import sys

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

QApplication.instance() or QApplication(sys.argv)

from modules.treesize.ui.panels import DriveList

DRIVES = [("C", 1_800_000_000_000, 1_700_000_000_000),
          ("E", 5_500_000_000_000, 5_000_000_000_000)]


def _panel(width):
    panel = DriveList()
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.resize(width, 140)
    panel.show()
    panel.refresh(DRIVES)
    QApplication.instance().processEvents()
    return panel


@pytest.mark.parametrize("width", [300, 375, 460, 500, 700, 1000])
def test_columns_fit_the_viewport(width):
    panel = _panel(width)
    widths = [panel.columnWidth(i) for i in range(4)]
    viewport = panel.viewport().width()
    assert sum(widths) <= viewport, (
        f"at {width}px the columns total {sum(widths)} in a {viewport}px "
        f"viewport {widths} -- the last column is cut off")


def test_the_percent_column_can_hold_its_own_text():
    """A bar delegate paints over the cell; the number still has to fit."""
    panel = _panel(375)
    text = panel.topLevelItem(0).text(3)
    needed = panel.fontMetrics().horizontalAdvance(text)
    assert panel.columnWidth(3) >= needed, (
        f"% Free column is {panel.columnWidth(3)}px but {text!r} needs {needed}px")
