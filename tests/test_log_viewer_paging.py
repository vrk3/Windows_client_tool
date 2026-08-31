"""Walking backwards through a log the viewer opened at its tail.

A log too big to load whole opens at its end, and until now everything before
that was unreachable. These drive the pane: the button, the auto-load on
scrolling to the top, what happens to Follow, and what the status line admits
to.

The pane is given a small `max_bytes` here so the fixtures stay kilobytes
rather than the real 32 MB. That seam is exactly the kind that hides bugs on
the other side of it, so `tools/log_viewer_real_check.py` pages the real
380 MB CBS archive at the real size -- these tests are not the evidence that
this works, they are the evidence that it keeps working.
"""
import pytest

from modules.log_viewer.log_model import MESSAGE
from modules.log_viewer.log_viewer_module import LogViewerWidget

#: Small enough for a fixture, large enough that the window lands mid-record.
STEP = 2048


def _record(number):
    """One CMTrace record, timestamped so that 300 of them run strictly
    forwards over five minutes -- paging is about time going backwards, so
    the fixture's clock has to actually move."""
    return ('<![LOG[Record {n:04d}]LOG]!><time="13:{m:02d}:{s:02d}.000+000" '
            'date="08-20-2026" component="Alpha" context="" type="1" '
            'thread="1" file="a.cpp:1">\n').format(
                n=number, m=number // 60, s=number % 60)


@pytest.fixture
def big_log(tmp_path):
    """Enough records that the tail cap leaves plenty behind it."""
    path = tmp_path / "ccmexec.log"
    path.write_text("".join(_record(n) for n in range(300)), encoding="utf-8")
    return path


@pytest.fixture
def small_log(tmp_path):
    path = tmp_path / "small.log"
    path.write_text("".join(_record(n) for n in range(3)), encoding="utf-8")
    return path


@pytest.fixture
def viewer(qapp, big_log):
    widget = LogViewerWidget(max_bytes=STEP)
    widget.open(str(big_log))
    yield widget
    widget.stop()


def _messages(widget):
    model = widget.model
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


# ---- the button ---------------------------------------------------------

def test_a_log_that_fitted_whole_offers_nothing_earlier(qapp, small_log):
    widget = LogViewerWidget(max_bytes=STEP)
    widget.open(str(small_log))
    try:
        assert not widget.load_earlier_button.isEnabled()
    finally:
        widget.stop()


def test_a_log_opened_at_its_tail_offers_to_load_earlier(viewer):
    assert viewer.load_earlier_button.isEnabled()


def test_loading_earlier_brings_older_records_in(viewer):
    before = viewer.model.total
    first = _messages(viewer)[0]

    viewer.load_earlier()

    assert viewer.model.total > before
    assert _messages(viewer)[0] < first, "the new first row must be OLDER"


def test_the_oldest_record_arrives_once_the_head_is_reached(viewer):
    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    assert _messages(viewer)[0] == "Record 0000"


def test_reaching_the_head_disables_the_button(viewer):
    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    assert not viewer.load_earlier_button.isEnabled()


def test_no_record_is_lost_or_duplicated_on_the_way_back(viewer):
    """The pane's version of the reader's reassembly test: a seam that eats
    one record per step is invisible in a table and fatal to an
    investigation."""
    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    viewer.fold.setChecked(False)
    rows = _messages(viewer)
    assert rows == sorted(rows)
    assert len(rows) == len(set(rows)), "a record was duplicated at a seam"
    assert rows == [f"Record {n:04d}" for n in range(300)]


# ---- following ----------------------------------------------------------

def test_loading_earlier_stops_following(viewer):
    """The tail is where new lines land, and the window has just moved away
    from it. Appending live lines onto a slice they are not contiguous with
    would fabricate a timeline, which is worse than not following."""
    viewer.follow.setChecked(True)

    viewer.load_earlier()

    assert not viewer.follow.isChecked()


def test_the_newest_button_returns_to_the_tail(viewer):
    viewer.load_earlier()

    viewer.go_to_newest()

    assert _messages(viewer)[-1] == "Record 0299"
    assert not viewer.model.unloaded_newer


# ---- auto-load ----------------------------------------------------------

def test_scrolling_to_the_top_loads_earlier_by_itself(viewer):
    before = viewer.model.total

    viewer.table.verticalScrollBar().setValue(
        viewer.table.verticalScrollBar().minimum())

    assert viewer.model.total > before


def test_a_load_already_running_does_not_start_another(viewer):
    """A step takes ~1.2s at the real size, and scroll events keep arriving
    throughout. Without the lock the auto path chains loads."""
    viewer._loading_earlier = True
    before = viewer.model.total

    viewer.load_earlier()

    assert viewer.model.total == before


def test_scrolling_to_the_top_at_the_head_does_nothing(viewer):
    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()
    before = viewer.model.total

    viewer.table.verticalScrollBar().setValue(
        viewer.table.verticalScrollBar().minimum())

    assert viewer.model.total == before


# ---- what the status line admits to -------------------------------------

def test_the_status_says_where_the_window_starts(viewer):
    assert "not loaded" in viewer.status.text()


def test_the_status_says_when_newer_records_were_unloaded(viewer):
    """Cap eviction needs 200,000 records to happen for real, so the counter
    is set directly here: what is under test is that the pane SAYS it."""
    viewer.model.unloaded_newer = 5

    viewer._update_status()

    assert "5 newer records unloaded" in viewer.status.text()


def test_the_status_stops_mentioning_the_window_at_the_head(viewer):
    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    assert "not loaded" not in viewer.status.text()


# ---- crossing two interactions ------------------------------------------

def test_a_filter_still_applies_after_loading_earlier(viewer):
    """Filter, then load earlier. Every defect the real-log pass found lived
    where two interactions crossed."""
    viewer.filter_box.setText("Record 000")
    viewer._apply_filters()
    assert _messages(viewer) == [], "those records are not loaded yet"

    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    assert _messages(viewer) == [f"Record {n:04d}" for n in range(10)]


def test_the_range_boxes_open_on_the_span_that_is_now_loaded(viewer):
    """Found by rendering the pane and reading it, not by a test.

    The From/To boxes are filled once, at open, with the span of the tail
    slice. Page back through 300 MB of older records and they still claim the
    log begins three minutes before it ends -- and nudging either box is how
    a range is turned ON, so the first nudge filters out everything that was
    just loaded.
    """
    before = viewer.time_from.dateTime().toPyDateTime()

    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    after = viewer.time_from.dateTime().toPyDateTime()
    assert after < before, "the boxes still describe the tail slice"
    assert after == viewer.model.time_span()[0]


def test_a_range_the_user_set_is_not_wiped_by_loading_earlier(viewer):
    """The counterpart. `_reset_range` also CLEARS the range, so refreshing
    the boxes must not go through it while the user has one set."""
    viewer.anchor_range(0, 1)
    chosen = viewer.time_from.dateTime()
    assert viewer._range_active

    viewer.load_earlier()

    assert viewer._range_active, "the user's range was cleared under them"
    assert viewer.time_from.dateTime() == chosen


def test_find_searches_the_records_that_were_just_loaded(viewer):
    """The search provider holds the model's entries. If a prepend does not
    tell it, Find silently searches the slice from before the load."""
    while viewer.load_earlier_button.isEnabled():
        viewer.load_earlier()

    viewer.find_box.setText("Record 0000")
    viewer.find_next()

    assert "No match" not in viewer.status.text()
