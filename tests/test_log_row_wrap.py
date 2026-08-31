"""Letting the row you are reading expand to show its whole message.

The detail pane exists because rows cannot wrap: 3,998 of 4,000 sampled rows
on a real CBS archive were elided, and some are 2,751px wide. Expanding the
SELECTED row keeps the message where the eye already is.

Only ever the selected row. Measuring every row would lay out 200,000
messages to show one.
"""
import pytest

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QStyleOptionViewItem

from modules.log_viewer.log_delegate import LogMessageDelegate
from modules.log_viewer.log_model import MESSAGE
from modules.log_viewer.log_viewer_module import LogViewerWidget

LONG = ("Appl: Evaluating package applicability for package "
        "HyperV-KMCL-Host-Package~31bf3856ad364e35~amd64~~10.0.26100.1, "
        "applicable state: Installed, and a great deal more text besides "
        "so that the line certainly does not fit inside one row of a table")

CMTRACE = (
    '<![LOG[{long}]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
    '<![LOG[short]LOG]!><time="13:45:11.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:2">\n'
).format(long=LONG)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.resize(700, 400)
    widget.open(str(path))
    yield widget
    widget.stop()


def _hint(widget, row):
    delegate = widget.message_delegate
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, widget.table.columnWidth(MESSAGE), 20)
    option.font = widget.table.font()
    return delegate.sizeHint(option, widget.model.index(row, MESSAGE))


def test_an_ordinary_row_is_one_line_tall(viewer):
    plain = _hint(viewer, 1).height()
    assert plain < 60, "a short row should not be expanded"


def test_the_expanded_row_is_taller(viewer):
    before = _hint(viewer, 0).height()

    viewer.message_delegate.expanded_row = 0

    assert _hint(viewer, 0).height() > before


def test_only_one_row_is_ever_expanded(viewer):
    viewer.message_delegate.expanded_row = 0
    assert _hint(viewer, 1).height() < _hint(viewer, 0).height()


def test_selecting_a_row_expands_it(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(0, MESSAGE))
    assert viewer.message_delegate.expanded_row == 0


def test_selecting_another_row_collapses_the_first(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(0, MESSAGE))
    viewer.table.setCurrentIndex(viewer.model.index(1, MESSAGE))
    assert viewer.message_delegate.expanded_row == 1


def test_expanding_does_not_break_the_rich_text_painting(viewer):
    """The expanded row takes the QTextDocument path; a failing code in it
    must still be coloured."""
    viewer.message_delegate.expanded_row = 0
    viewer.table.grab()          # forces paintEvent over both rows


def test_a_row_with_no_message_does_not_break_the_hint(viewer):
    viewer.message_delegate.expanded_row = 99
    assert _hint(viewer, 0).height() > 0


def test_an_empty_option_rect_still_wraps(viewer):
    r"""The case the first version of these tests missed entirely.

    Qt hands `sizeHint` an EMPTY rect when it asks during
    `resizeRowToContents`, and a text width of zero disables wrapping -- so
    the row came back one line tall and the feature silently did nothing,
    while every test here passed because they all built a rect with a real
    width. Only running it on the real archive showed 24px -> 28px where it
    should have been 24px -> 60px.
    """
    delegate = viewer.message_delegate
    delegate.expanded_row = 0
    option = QStyleOptionViewItem()
    option.rect = QRect()                  # empty, as Qt supplies it
    option.widget = viewer.table
    option.font = viewer.table.font()

    height = delegate.sizeHint(option, viewer.model.index(0, MESSAGE)).height()

    assert height > 40, "an empty rect disabled wrapping again"
