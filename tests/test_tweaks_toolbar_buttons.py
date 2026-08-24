"""The tweak-selection buttons must be able to show their own labels.

Each was pinned with setFixedWidth to a value smaller than its text: "Select
Applied" needs about 111px and was given 100, so it rendered as "elect Applie".
Present in BOTH themes, so it was never a theming bug -- just a fixed width
chosen by eye and never measured.
"""
import sys

import pytest
from PyQt6.QtWidgets import QApplication

QApplication.instance() or QApplication(sys.argv)

from modules.tweaks.tweaks_module import TweakTab


@pytest.fixture
def toolbar_buttons():
    widget = TweakTab([])
    return [widget._select_all_btn, widget._deselect_all_btn,
            widget._select_applied_btn, widget._select_not_btn]


def test_each_button_is_wide_enough_for_its_label(toolbar_buttons):
    for button in toolbar_buttons:
        needed = button.sizeHint().width()
        assert button.minimumWidth() >= needed, (
            f"{button.text()!r} is {button.minimumWidth()}px but needs {needed}px")


def test_no_button_is_pinned_narrower_than_its_label(toolbar_buttons):
    """setFixedWidth pins BOTH bounds -- the maximum is what cropped the text."""
    for button in toolbar_buttons:
        needed = button.sizeHint().width()
        assert button.maximumWidth() >= needed, (
            f"{button.text()!r} is capped at {button.maximumWidth()}px, "
            f"under the {needed}px its label needs")
