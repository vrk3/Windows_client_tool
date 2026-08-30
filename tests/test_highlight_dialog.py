"""The highlight-rules editor dialog.

Colour is chosen through the colour dialog (QColorDialog.getColor, which we
never invoke in a test -- it blocks). Nothing here opens that dialog; these
tests only exercise the table it builds and edits.
"""
from PyQt6.QtCore import Qt

from modules.log_viewer.highlight import HighlightRule
from modules.log_viewer.highlight_dialog import HighlightDialog


def test_the_colour_cell_cannot_be_typed_into(qapp):
    """A user could double-click the Colour cell and type "red" -- which
    later raises out of a reimplemented Qt virtual and is fatal. The colour
    is chosen through QColorDialog instead, so the cell must not be
    editable."""
    dialog = HighlightDialog([HighlightRule("boom", "#00ff00")])
    item = dialog.table.item(0, 1)
    assert not (item.flags() & Qt.ItemFlag.ItemIsEditable)


def test_other_columns_stay_editable(qapp):
    """Only the colour cell is special-cased -- Pattern is still meant to be
    typed into directly."""
    dialog = HighlightDialog([HighlightRule("boom", "#00ff00")])
    pattern_item = dialog.table.item(0, 0)
    assert pattern_item.flags() & Qt.ItemFlag.ItemIsEditable
