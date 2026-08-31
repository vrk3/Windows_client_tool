"""Showing the rows AROUND something, not just the something.

A filtered CBS view shows you the failure and hides the thing that caused it,
three lines above. This is `grep -C`, and it is the single most common thing
anyone does to a log by hand.

One primitive serves two features: "errors with context" anchors on every
error, "peek" anchors on one row you picked.
"""
from datetime import datetime, timedelta

import pytest

from core.types import LogEntry
from modules.log_viewer.log_model import LogModel, MESSAGE

BASE = datetime(2026, 8, 27, 10, 0, 0)


def _entry(message, level="Info", seconds=0):
    return LogEntry(timestamp=BASE + timedelta(seconds=seconds), source="CBS",
                    level=level, message=message, raw={"thread": "1"})


def _model(entries):
    model = LogModel()
    model.append(list(entries))
    return model


def _messages(model):
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


TEN = [_entry(f"line {n}", level="Error" if n == 5 else "Info", seconds=n)
       for n in range(10)]


# ---- errors with context ------------------------------------------------

def test_errors_with_context_shows_the_rows_either_side():
    model = _model(TEN)
    model.set_error_context(2)
    assert _messages(model) == ["line 3", "line 4", "line 5", "line 6",
                                "line 7"]


def test_a_context_of_zero_shows_only_the_errors():
    model = _model(TEN)
    model.set_error_context(0)
    assert _messages(model) == ["line 5"]


def test_turning_context_off_brings_everything_back():
    model = _model(TEN)
    model.set_error_context(2)
    model.set_error_context(None)
    assert len(_messages(model)) == 10


def test_overlapping_windows_are_merged_not_duplicated():
    """Two errors three apart with a context of three would otherwise list
    the rows between them twice."""
    entries = [_entry(f"line {n}",
                      level="Error" if n in (4, 6) else "Info", seconds=n)
               for n in range(10)]
    model = _model(entries)
    model.set_error_context(3)
    shown = _messages(model)
    assert len(shown) == len(set(shown)), "a row appeared twice"
    assert shown == [f"line {n}" for n in range(1, 10)]


def test_context_does_not_run_off_the_ends():
    entries = [_entry("first", level="Error", seconds=0),
               _entry("second", seconds=1)]
    model = _model(entries)
    model.set_error_context(5)
    assert _messages(model) == ["first", "second"]


def test_a_log_with_no_errors_shows_nothing_under_context():
    """An empty table is the honest answer to "show me the errors" when
    there are none -- and the pane says so in the status line."""
    model = _model([_entry("fine"), _entry("also fine")])
    model.set_error_context(2)
    assert _messages(model) == []


def test_context_still_obeys_the_other_filters():
    """Context widens what an ANCHOR pulls in; it does not override a filter
    the user set. A row excluded by the component filter stays excluded."""
    entries = [_entry("cbs line", seconds=0),
               _entry("bad", level="Error", seconds=1)]
    entries[0].source = "OTHER"
    model = _model(entries)
    model.set_filter(component="CBS")
    model.set_error_context(5)
    assert _messages(model) == ["bad"]


# ---- peeking around one row ---------------------------------------------

def test_peeking_reveals_the_neighbours_of_one_row():
    model = _model(TEN)
    model.set_filter(needle="line 5")
    assert _messages(model) == ["line 5"]

    model.peek(model.entry(0), 2)

    assert _messages(model) == ["line 3", "line 4", "line 5", "line 6",
                                "line 7"]


def test_closing_the_peek_restores_the_filtered_view_exactly():
    model = _model(TEN)
    model.set_filter(needle="line 5")
    model.peek(model.entry(0), 2)

    model.peek(None, 0)

    assert _messages(model) == ["line 5"]


def test_peeking_at_nothing_is_harmless():
    model = _model(TEN)
    model.peek(None, 3)
    assert len(_messages(model)) == 10


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = "".join(
    '<![LOG[line {n}]LOG]!><time="13:45:{n:02d}.000+000" date="08-20-2026" '
    'component="CBS" context="" type="{t}" thread="1" file="a.cpp:1">\n'.format(
        n=n, t=3 if n == 5 else 1) for n in range(10))


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _shown(widget):
    model = widget.model
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


def test_the_context_box_narrows_to_errors_and_their_surroundings(viewer):
    """The pane uses CONTEXT_LINES either side; line 5 is the only error."""
    viewer.context_box.setChecked(True)
    reach = LogViewerWidget.CONTEXT_LINES
    assert _shown(viewer) == [f"line {n}" for n in range(5 - reach,
                                                        5 + reach + 1)]


def test_unticking_the_box_restores_the_view(viewer):
    viewer.context_box.setChecked(True)
    viewer.context_box.setChecked(False)
    assert len(_shown(viewer)) == 10


def test_the_status_says_when_context_found_no_errors(qapp, tmp_path):
    path = tmp_path / "clean.log"
    path.write_text(
        '<![LOG[all well]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
        'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n',
        encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.context_box.setChecked(True)
        assert _shown(widget) == []
        assert "no errors" in widget.status.text().lower()
    finally:
        widget.stop()


def test_peeking_from_the_row_menu_reveals_the_neighbours(viewer):
    viewer.filter_box.setText("line 5")
    assert _shown(viewer) == ["line 5"]

    viewer.table.setCurrentIndex(viewer.model.index(0, MESSAGE))
    viewer.peek_around_current()

    assert len(_shown(viewer)) > 1, "the filter still hid the neighbours"


def test_peeking_again_closes_it(viewer):
    viewer.filter_box.setText("line 5")
    viewer.table.setCurrentIndex(viewer.model.index(0, MESSAGE))
    viewer.peek_around_current()

    viewer.peek_around_current()

    assert _shown(viewer) == ["line 5"]
