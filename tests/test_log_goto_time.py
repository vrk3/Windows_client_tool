"""Jumping to a moment in time.

Different from the time-range filter: that HIDES everything outside the
range, this only moves you. When you are correlating a log against an event
log or a user's account of what happened, hiding is the wrong tool.
"""
from datetime import datetime

import pytest

from core.types import LogEntry
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.log_model import LogModel, MESSAGE


def _at(minute, message=None, when=None):
    return LogEntry(timestamp=when or datetime(2026, 8, 27, 10, minute, 0),
                    source="CBS", level="Info",
                    message=message or f"minute {minute}", raw={"thread": "1"})


def _model(entries):
    model = LogModel()
    model.append(list(entries))
    return model


def _message_at(model, row):
    return model.data(model.index(row, MESSAGE))


def test_going_to_a_time_lands_on_the_first_row_at_or_after_it(qapp):
    model = _model([_at(0), _at(10), _at(20)])
    row = model.row_at_or_after(datetime(2026, 8, 27, 10, 5, 0))
    assert _message_at(model, row) == "minute 10"


def test_an_exact_match_lands_on_that_row(qapp):
    model = _model([_at(0), _at(10), _at(20)])
    row = model.row_at_or_after(datetime(2026, 8, 27, 10, 10, 0))
    assert _message_at(model, row) == "minute 10"


def test_a_time_before_the_start_lands_on_the_first_row(qapp):
    model = _model([_at(10), _at(20)])
    row = model.row_at_or_after(datetime(2026, 8, 27, 9, 0, 0))
    assert row == 0


def test_a_time_after_the_end_lands_on_the_last_row(qapp):
    model = _model([_at(10), _at(20)])
    row = model.row_at_or_after(datetime(2026, 8, 27, 23, 0, 0))
    assert _message_at(model, row) == "minute 20"


def test_an_empty_model_answers_with_no_row(qapp):
    assert _model([]).row_at_or_after(datetime(2026, 8, 27, 10, 0, 0)) == -1


def test_rows_with_no_timestamp_are_skipped_not_matched(qapp):
    """A continuation carries no clock of its own. Landing on one would put
    you in the middle of a block with no idea where you are."""
    model = _model([_at(0),
                    _at(0, "continuation", when=UNKNOWN_TIME),
                    _at(10)])
    row = model.row_at_or_after(datetime(2026, 8, 27, 10, 5, 0))
    assert _message_at(model, row) == "minute 10"


def test_a_log_whose_clock_runs_backwards_still_answers(qapp):
    """setupact.log and setuperr.log both jump ten hours BACKWARDS at a setup
    phase boundary, so the timestamps down a column are not sorted and a
    bisect would answer confidently and wrongly. The first row at or after,
    in file order, is the honest answer.
    """
    model = _model([_at(0, "before the jump", when=datetime(2026, 8, 27, 10, 44, 46)),
                    _at(0, "after the jump", when=datetime(2026, 8, 27, 0, 44, 49)),
                    _at(0, "later still", when=datetime(2026, 8, 27, 0, 45, 0))])

    row = model.row_at_or_after(datetime(2026, 8, 27, 0, 44, 0))

    assert _message_at(model, row) == "before the jump", (
        "10:44:46 is at or after 00:44:00 and comes first in the file")


def test_the_search_respects_the_current_filter(qapp):
    """It returns a ROW, and rows are what the filter left."""
    model = _model([_at(0), _at(10, "keep me"), _at(20)])
    model.set_filter(needle="keep")
    row = model.row_at_or_after(datetime(2026, 8, 27, 10, 0, 0))
    assert _message_at(model, row) == "keep me"


# ---- the pane control ----------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = "".join(
    '<![LOG[minute {n}]LOG]!><time="13:{n:02d}:00.000+000" '
    'date="08-20-2026" component="CBS" context="" type="1" thread="1" '
    'file="a.cpp:1">\n'.format(n=n) for n in range(0, 40, 10))


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_go_to_jumps_without_filtering_anything_away(viewer):
    """The whole point: the range filter HIDES, this only moves. When you are
    correlating against an event log you need the surrounding rows to stay.

    The jump takes its own time rather than reading the From box, because
    editing that box fires `dateTimeChanged` -- which is exactly what turns
    the range filter on. Reusing it would have filtered before the jump
    happened.
    """
    before = viewer.model.rowCount()

    viewer.go_to_time(datetime(2026, 8, 20, 13, 20, 0))

    assert viewer.model.rowCount() == before, "rows were hidden, not scrolled"
    assert not viewer._range_active, "a jump must not switch the range on"


def test_go_to_selects_the_row_it_landed_on(viewer):
    viewer.go_to_time(datetime(2026, 8, 20, 13, 20, 0))

    entry = viewer.model.entry(viewer.table.currentIndex().row())
    assert entry is not None and entry.message == "minute 20"


def test_go_to_on_an_empty_pane_does_nothing(qapp):
    widget = LogViewerWidget()
    try:
        widget.go_to_time(datetime(2026, 8, 20, 13, 0, 0))
    finally:
        widget.stop()
