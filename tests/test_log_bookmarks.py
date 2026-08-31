"""Marked rows you can get back to.

An investigation is a loop of "that line and this line". Right now the only
way back to a row is to remember what it said.

Bookmarks are held as RECORDS, never as row or entry indices. Both shift:
rows shift whenever the filter changes, entry indices shift by the size of
every "load earlier" chunk. That is the same trap the summary panel hit.
"""
from datetime import datetime, timedelta

import pytest

from core.types import LogEntry
from modules.log_viewer.log_model import LogModel, MESSAGE, TIME
from modules.log_viewer.log_viewer_module import LogViewerWidget

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


# ---- the model ----------------------------------------------------------

def test_a_row_can_be_bookmarked_and_unbookmarked(qapp):
    model = _model([_entry("one"), _entry("two")])
    entry = model.entry(0)

    model.toggle_bookmark(entry)
    assert model.is_bookmarked(entry)

    model.toggle_bookmark(entry)
    assert not model.is_bookmarked(entry)


def test_a_bookmarked_row_is_marked_in_the_time_column(qapp):
    """Display only, like the fold suffix -- export reads the record, so the
    marker can never leak into a file."""
    model = _model([_entry("one")])
    model.toggle_bookmark(model.entry(0))
    assert model.data(model.index(0, TIME)).startswith("★")


def test_an_unbookmarked_row_carries_no_marker(qapp):
    model = _model([_entry("one")])
    assert not model.data(model.index(0, TIME)).startswith("★")


def test_bookmarks_survive_a_filter_that_hides_them(qapp):
    """A row you marked and then filtered away is still marked when it
    comes back."""
    model = _model([_entry("keep"), _entry("other")])
    entry = model.entry(0)
    model.toggle_bookmark(entry)

    model.set_filter(needle="other")
    model.set_filter(needle="")

    assert model.is_bookmarked(entry)


def test_bookmarks_survive_a_prepend(qapp):
    """Entry indices shift by the size of the loaded chunk. A bookmark held
    as an index would silently point at a different record."""
    model = _model([_entry("newer", seconds=100)])
    entry = model.entry(0)
    model.toggle_bookmark(entry)

    model.prepend([_entry("older", seconds=n) for n in range(5)])

    assert model.is_bookmarked(entry)
    assert model.data(model.index(model.row_for_record(entry), TIME)) \
        .startswith("★")


def test_the_bookmark_list_is_in_view_order(qapp):
    model = _model([_entry("one"), _entry("two"), _entry("three")])
    model.toggle_bookmark(model.entry(2))
    model.toggle_bookmark(model.entry(0))

    assert [e.message for e in model.bookmarks()] == ["one", "three"]


def test_a_bookmark_whose_record_is_gone_drops_out_of_the_list(qapp):
    """Loading earlier evicts the newest records. A bookmark on one of them
    has nothing to point at and must not linger as a dead row."""
    model = LogModel(cap=2)
    model.append([_entry("a"), _entry("b")])
    doomed = model.entry(1)
    model.toggle_bookmark(doomed)

    model.prepend([_entry("older", seconds=-1)])

    assert doomed not in model.bookmarks()


def test_clearing_the_log_clears_the_bookmarks(qapp):
    model = _model([_entry("one")])
    model.toggle_bookmark(model.entry(0))
    model.clear()
    assert model.bookmarks() == []


# ---- the pane -----------------------------------------------------------

CMTRACE = "".join(
    '<![LOG[line {n}]LOG]!><time="13:45:1{n}.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'.format(
        n=n) for n in range(4))


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_the_shortcut_toggles_a_bookmark_on_the_current_row(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(1, MESSAGE))

    viewer.toggle_bookmark()

    assert viewer.model.is_bookmarked(viewer.model.entry(1))


def test_toggling_twice_removes_it(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(1, MESSAGE))
    viewer.toggle_bookmark()
    viewer.toggle_bookmark()
    assert not viewer.model.is_bookmarked(viewer.model.entry(1))


def test_bookmarking_with_no_row_selected_does_nothing(viewer):
    viewer.table.clearSelection()
    viewer.table.setCurrentIndex(viewer.model.index(-1, -1))
    viewer.toggle_bookmark()            # must not raise
    assert viewer.model.bookmarks() == []


def test_the_summary_lists_the_bookmarks(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(2, MESSAGE))
    viewer.toggle_bookmark()

    viewer.summary_button.setChecked(True)

    rows = [viewer.summary_bookmarks.item(i).text()
            for i in range(viewer.summary_bookmarks.count())]
    assert any("line 2" in text for text in rows)


def test_clicking_a_bookmark_goes_to_it(viewer):
    viewer.table.setCurrentIndex(viewer.model.index(3, MESSAGE))
    viewer.toggle_bookmark()
    viewer.summary_button.setChecked(True)

    viewer.summary_bookmarks.itemClicked.emit(
        viewer.summary_bookmarks.item(0))

    assert viewer.model.entry(viewer.table.currentIndex().row()).message == \
        "line 3"


def test_a_bookmark_shortcut_exists(viewer):
    bound = {s.key().toString() for s in viewer._shortcuts}
    assert "Ctrl+D" in bound
