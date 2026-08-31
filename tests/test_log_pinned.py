"""Rows kept in view while you read the two hundred lines that led to them.

Different from a bookmark, which is a place to jump back to: a pinned row
stays on screen. Keeping the error visible while scrolling through what
preceded it is the whole point.

A pinned row therefore survives a filter that would hide it -- which is why
the pinned strip has its own model rather than a proxy over the filtered one:
a proxy cannot show a row the model has already excluded.
"""
import pytest

from modules.log_viewer.log_model import MESSAGE
from modules.log_viewer.log_viewer_module import LogViewerWidget

CMTRACE = "".join(
    '<![LOG[line {n}]LOG]!><time="13:45:1{n}.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'.format(
        n=n) for n in range(5))


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _pinned(widget):
    model = widget.pinned_model
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


def test_the_strip_is_hidden_until_something_is_pinned(viewer):
    assert not viewer.pinned_table.isVisible()
    assert _pinned(viewer) == []


def test_pinning_a_row_puts_it_in_the_strip(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(2, MESSAGE))
    viewer.toggle_pin()
    assert _pinned(viewer) == ["line 2"]


def test_unpinning_removes_it(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(2, MESSAGE))
    viewer.toggle_pin()
    viewer.toggle_pin()
    assert _pinned(viewer) == []


def test_several_rows_can_be_pinned_in_view_order(viewer):
    for row in (3, 1):
        viewer.table.setCurrentIndex(viewer.model.index(row, MESSAGE))
        viewer.toggle_pin()
    assert _pinned(viewer) == ["line 1", "line 3"]


def test_a_pinned_row_survives_a_filter_that_hides_it(viewer):
    """The reason the strip has its own model: a proxy over the filtered
    model could not show a row that model had already excluded."""
    viewer.table.setCurrentIndex(viewer.model.index(2, MESSAGE))
    viewer.toggle_pin()

    viewer.filter_box.setText("line 4")

    assert viewer.model.rowCount() == 1, "the filter applied"
    assert _pinned(viewer) == ["line 2"], "the pinned row vanished"


def test_pinning_with_no_row_selected_does_nothing(viewer):
    viewer.table.clearSelection()
    viewer.table.setCurrentIndex(viewer.model.index(-1, -1))
    viewer.toggle_pin()
    assert _pinned(viewer) == []


def test_opening_another_log_clears_the_pins(viewer, tmp_path):
    """Pinned rows belong to the log they came from. Carrying them into a
    different file would show records that are not in it."""
    viewer.table.setCurrentIndex(viewer.model.index(2, MESSAGE))
    viewer.toggle_pin()

    other = tmp_path / "second.log"
    other.write_text(CMTRACE, encoding="utf-8")
    viewer.open(str(other))

    assert _pinned(viewer) == []
    assert not viewer.pinned_table.isVisible()


def test_a_pin_shortcut_exists(viewer):
    assert "Ctrl+P" in {s.key().toString() for s in viewer._shortcuts}
