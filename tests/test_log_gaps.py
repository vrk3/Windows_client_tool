"""Where the log went quiet.

A hang leaves no error line. It leaves a HOLE in the timestamps -- servicing
stops for ninety seconds and then carries on as if nothing happened -- and
nothing in the viewer surfaced that until now.
"""
from datetime import datetime, timedelta

import pytest

from core.types import LogEntry
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.log_stats import gaps

BASE = datetime(2026, 8, 27, 10, 0, 0)


def _at(seconds, message="line", merge_time=None):
    raw = {"thread": "1"}
    if merge_time is not None:
        raw["merge_time"] = merge_time
    when = UNKNOWN_TIME if seconds is None else BASE + timedelta(seconds=seconds)
    return LogEntry(timestamp=when, source="CBS", level="Info",
                    message=message, raw=raw)


def test_a_gap_longer_than_the_threshold_is_reported():
    found = gaps([_at(0), _at(120)], threshold_seconds=60)
    assert found == [(1, 120.0)]


def test_a_gap_shorter_than_the_threshold_is_not():
    assert gaps([_at(0), _at(5)], threshold_seconds=60) == []


def test_the_index_points_at_the_record_AFTER_the_silence():
    """That is the row you want to be taken to: the first thing that happened
    when it started again."""
    found = gaps([_at(0), _at(1), _at(600)], threshold_seconds=60)
    assert found[0][0] == 2


def test_several_gaps_are_all_reported_longest_first():
    found = gaps([_at(0), _at(100), _at(400)], threshold_seconds=60)
    assert [seconds for _index, seconds in found] == [300.0, 100.0]


def test_records_with_no_clock_do_not_create_a_false_gap():
    """A continuation carries no timestamp of its own. Treating its absent
    clock as a moment in time would invent a gap back to the epoch."""
    assert gaps([_at(0), _at(None), _at(5)], threshold_seconds=60) == []


def test_a_backwards_clock_step_is_not_a_stall():
    """setupact.log and setuperr.log both jump ten hours BACKWARDS at a setup
    phase boundary. A negative delta is a clock changing, not silence."""
    assert gaps([_at(36000), _at(0)], threshold_seconds=60) == []


def test_the_merge_time_is_preferred_when_present():
    """In a merged set the effective timestamp is what the timeline is built
    on, and it is what a gap has to be measured against."""
    entries = [_at(0, merge_time=BASE),
               _at(None, merge_time=BASE + timedelta(seconds=300))]
    assert gaps(entries, threshold_seconds=60) == [(1, 300.0)]


def test_an_empty_log_has_no_gaps():
    assert gaps([], threshold_seconds=60) == []
    assert gaps([_at(0)], threshold_seconds=60) == []


def test_a_threshold_of_zero_does_not_report_every_row():
    """Guard against a control set to 0 flooding the panel with 138,683
    findings, every one of them meaningless."""
    assert gaps([_at(0), _at(1)], threshold_seconds=0) == []


# ---- the panel column ---------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = "".join(
    '<![LOG[line {n}]LOG]!><time="13:{m:02d}:00.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'.format(
        n=n, m=m)
    for n, m in enumerate((0, 1, 30, 31)))          # a 29-minute silence


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _rows(listing):
    return [listing.item(row).text() for row in range(listing.count())]


def test_the_summary_lists_the_silences(viewer):
    viewer.summary_button.setChecked(True)
    assert _rows(viewer.summary_gaps), "no gap found in a log with a 29m hole"
    assert "line 2" in _rows(viewer.summary_gaps)[0]


def test_clicking_a_silence_goes_to_the_row_after_it(viewer):
    viewer.summary_button.setChecked(True)

    viewer.summary_gaps.itemClicked.emit(viewer.summary_gaps.item(0))

    entry = viewer.model.entry(viewer.table.currentIndex().row())
    assert entry is not None and entry.message == "line 2"


def test_a_gap_row_survives_folding_being_on(viewer):
    """Gaps are counted over the unfolded records, so their indices are NOT
    row numbers. Clicking one has to find the record's actual row or it
    lands somewhere arbitrary."""
    assert viewer.fold.isChecked(), "folding is on by default"
    viewer.summary_button.setChecked(True)

    viewer.summary_gaps.itemClicked.emit(viewer.summary_gaps.item(0))

    entry = viewer.model.entry(viewer.table.currentIndex().row())
    assert entry.message == "line 2"


def test_a_log_with_no_silences_shows_an_empty_column(qapp, tmp_path):
    path = tmp_path / "busy.log"
    path.write_text(
        '<![LOG[a]LOG]!><time="13:00:00.000+000" date="08-20-2026" '
        'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
        '<![LOG[b]LOG]!><time="13:00:01.000+000" date="08-20-2026" '
        'component="CBS" context="" type="1" thread="1" file="a.cpp:2">\n',
        encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.summary_button.setChecked(True)
        assert _rows(widget.summary_gaps) == []
    finally:
        widget.stop()
