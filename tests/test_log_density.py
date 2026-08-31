"""Bucketing a log's records over its own time span.

The data behind the density strip: on a 1.5-million-record archive, finding
where the errors cluster is the difference between reading and hunting.

Qt-free. The painter is the pane's business; deciding what the bars MEAN is
this module's, and that is the part worth testing.
"""
from datetime import datetime, timedelta

import pytest

from core.types import LogEntry
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.density import buckets

BASE = datetime(2026, 8, 27, 10, 0, 0)


def _at(seconds, level="Info"):
    when = UNKNOWN_TIME if seconds is None else BASE + timedelta(seconds=seconds)
    return LogEntry(timestamp=when, source="CBS", level=level,
                    message="line", raw={"thread": "1"})


def test_the_buckets_span_the_whole_range():
    made = buckets([_at(0), _at(100)], count=10)
    assert len(made) == 10
    assert made[0].start == BASE
    assert made[-1].end == BASE + timedelta(seconds=100)


def test_every_record_lands_in_exactly_one_bucket():
    entries = [_at(n) for n in range(0, 100, 7)]
    made = buckets(entries, count=10)
    assert sum(bucket.total for bucket in made) == len(entries)


def test_the_last_record_lands_in_the_last_bucket_not_past_it():
    """The final timestamp sits exactly on the upper edge. Off-by-one here
    drops the newest record, which is the one someone opened the log for."""
    made = buckets([_at(0), _at(100)], count=10)
    assert made[-1].total == 1


def test_errors_are_counted_separately_from_the_total():
    made = buckets([_at(0, "Error"), _at(1, "Info")], count=1)
    assert made[0].total == 2
    assert made[0].errors == 1


def test_records_with_no_clock_are_excluded_not_bucketed_at_the_epoch():
    """A continuation carries no timestamp. Bucketing it at the epoch would
    stretch the range back to year 1 and squash the whole log into one bar."""
    made = buckets([_at(0), _at(None), _at(100)], count=10)
    assert sum(bucket.total for bucket in made) == 2
    assert made[0].start == BASE


def test_a_log_that_happened_in_one_instant_does_not_divide_by_zero():
    made = buckets([_at(0), _at(0)], count=10)
    assert made and sum(bucket.total for bucket in made) == 2


def test_a_single_record_still_yields_buckets():
    made = buckets([_at(0)], count=10)
    assert sum(bucket.total for bucket in made) == 1


def test_no_records_with_a_clock_yields_nothing():
    assert buckets([], count=10) == []
    assert buckets([_at(None)], count=10) == []


def test_a_backwards_clock_does_not_invert_the_range():
    """setupact jumps ten hours backwards mid-file. The range is the MIN and
    MAX seen, not the first and last record."""
    made = buckets([_at(3600), _at(0)], count=4)
    assert made[0].start == BASE
    assert made[-1].end == BASE + timedelta(seconds=3600)


def test_the_bucket_count_is_respected():
    assert len(buckets([_at(0), _at(60)], count=3)) == 3


def test_a_zero_bucket_count_is_refused_rather_than_dividing_by_zero():
    assert buckets([_at(0), _at(60)], count=0) == []


# ---- the strip ----------------------------------------------------------

from modules.log_viewer.density_strip import DensityStrip  # noqa: E402
from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402


def test_an_empty_strip_paints_nothing_and_does_not_crash(qapp):
    strip = DensityStrip()
    strip.resize(200, 44)
    strip.set_buckets([])
    strip.grab()                        # forces paintEvent
    assert not strip.has_data()


def test_a_strip_with_data_paints(qapp):
    strip = DensityStrip()
    strip.resize(200, 44)
    strip.set_buckets(buckets([_at(0), _at(50, "Error"), _at(100)], count=20))
    strip.grab()
    assert strip.has_data()


def test_clicking_the_left_edge_gives_the_start_of_the_span(qapp):
    strip = DensityStrip()
    strip.resize(200, 44)
    strip.set_buckets(buckets([_at(0), _at(100)], count=10))
    assert strip.moment_at(0) == BASE


def test_clicking_the_right_edge_gives_the_last_bucket(qapp):
    strip = DensityStrip()
    strip.resize(200, 44)
    made = buckets([_at(0), _at(100)], count=10)
    strip.set_buckets(made)
    assert strip.moment_at(199) == made[-1].start


def test_a_click_past_the_edge_is_clamped_rather_than_raising(qapp):
    strip = DensityStrip()
    strip.resize(200, 44)
    strip.set_buckets(buckets([_at(0), _at(100)], count=10))
    assert strip.moment_at(10_000) is not None
    assert strip.moment_at(-50) is not None


def test_an_empty_strip_answers_no_moment(qapp):
    strip = DensityStrip()
    strip.resize(200, 44)
    assert strip.moment_at(10) is None


# ---- wired into the pane ------------------------------------------------

SPAN = "".join(
    '<![LOG[line {n}]LOG]!><time="13:{m:02d}:00.000+000" date="08-20-2026" '
    'component="CBS" context="" type="{t}" thread="1" file="a.cpp:1">\n'.format(
        n=n, m=n * 5, t=3 if n == 6 else 1)
    for n in range(10))


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(SPAN, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_opening_a_log_fills_the_strip(viewer):
    assert viewer.density.has_data()


def test_clicking_the_strip_scrolls_the_table(viewer):
    """It moves you; it does not filter. Same rule as "Go to"."""
    before = viewer.model.rowCount()

    viewer.density.moment_picked.emit(datetime(2026, 8, 20, 13, 30, 0))

    assert viewer.model.rowCount() == before, "rows were hidden, not scrolled"
    entry = viewer.model.entry(viewer.table.currentIndex().row())
    assert entry is not None and entry.message == "line 6"


def test_the_strip_follows_the_filter(viewer):
    """It describes what is on screen, like the Summary panel does."""
    viewer.filter_box.setText("line 6")
    viewer._refresh_density()
    filled = [b for b in viewer.density._buckets if b.total]
    assert len(filled) == 1


def test_a_log_with_no_timestamps_leaves_the_strip_empty(qapp, tmp_path):
    path = tmp_path / "flat.log"
    path.write_text("no timestamps here\nnor here\n", encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        assert not widget.density.has_data()
        assert not widget.density.isVisible()
    finally:
        widget.stop()


# ---- scaling, found by rendering the real archive -----------------------

def test_a_small_bucket_beside_a_huge_one_is_still_drawn(qapp):
    r"""Found by looking at the real CBS archive.

    CBS writes in bursts: one bucket held the overwhelming majority of
    138,683 records, so under linear scaling every other bar rounded to zero
    pixels and the strip read as a single block with nothing around it --
    arithmetically honest and completely useless.

    A square-root scale keeps the ordering (bigger is still taller) while
    leaving a bucket that is a thousandth of the busiest one visible.
    """
    from modules.log_viewer.density_strip import bar_height

    tall = bar_height(1, 100_000, height=44)
    assert tall >= 1, "a real bucket must never be invisible"
    assert bar_height(100_000, 100_000, height=44) == 44
    assert bar_height(50_000, 100_000, height=44) > \
        bar_height(1_000, 100_000, height=44), "ordering must survive"


def test_an_empty_bucket_draws_nothing():
    from modules.log_viewer.density_strip import bar_height
    assert bar_height(0, 100, height=44) == 0
