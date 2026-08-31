r"""Noticing logs that appear after the folder was opened.

A repair run creates new files. Follow tracks the files that are already
open; without this, the log that records the repair never shows up.

**Every test here drives a real folder on disk.** No injected change source:
TreeSize's watcher had two independent fatal bugs behind 21 passing tests for
exactly that reason -- every test handed it a fake source that ENDED, while
the real one blocks forever.
"""
import os

import pytest

from modules.log_viewer.log_set import LogSet
from modules.log_viewer.log_viewer_module import LogViewerWidget


def _line(stamp, message):
    return f"{stamp}, Info                  CBS    {message}\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return str(path)


# ---- the set ------------------------------------------------------------

def test_a_source_can_be_added_after_the_set_was_built(tmp_path):
    a = _write(tmp_path / "cbs.log", _line("2026-08-27 10:00:00", "first"))
    log_set = LogSet([a])
    log_set.read_new()

    b = _write(tmp_path / "dism.log", _line("2026-08-27 10:00:05", "second"))
    log_set.add_source(b)
    fresh = log_set.read_new()

    assert [e.message for e in fresh] == ["second"]
    assert log_set.sources() == ["cbs.log", "dism.log"]


def test_adding_a_source_twice_does_not_duplicate_it(tmp_path):
    a = _write(tmp_path / "cbs.log", _line("2026-08-27 10:00:00", "x"))
    log_set = LogSet([a])
    log_set.add_source(a)
    assert log_set.sources() == ["cbs.log"]


def test_a_new_source_merges_into_the_timeline_in_order(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _line("2026-08-27 10:00:00", "first")
               + _line("2026-08-27 10:00:10", "third"))
    log_set = LogSet([a])
    log_set.read_new()

    b = _write(tmp_path / "dism.log", _line("2026-08-27 10:00:05", "second"))
    log_set.add_source(b)
    log_set.read_new()

    assert [e.message for e in log_set.entries()] == \
        ["first", "second", "third"]


# ---- the pane, against a real folder ------------------------------------

@pytest.fixture
def folder(tmp_path):
    _write(tmp_path / "cbs.log", _line("2026-08-27 10:00:00", "first"))
    return tmp_path


def test_a_log_appearing_after_open_is_picked_up(qapp, folder):
    widget = LogViewerWidget()
    try:
        widget.open_folder(str(folder))
        widget.follow.setChecked(True)
        assert widget.model.total == 1

        # A real file, really created, while the pane is open.
        _write(folder / "repair.log", _line("2026-08-27 10:00:30", "repaired"))
        widget._poll()

        assert widget.model.total == 2
        assert "repair.log" in widget._set.sources()
    finally:
        widget.stop()


def test_nothing_is_picked_up_while_not_following(qapp, folder):
    """Watching costs a directory listing per tick. Not following means not
    watching."""
    widget = LogViewerWidget()
    try:
        widget.open_folder(str(folder))
        _write(folder / "late.log", _line("2026-08-27 10:00:30", "late"))
        widget._poll()
        assert "late.log" not in widget._set.sources()
    finally:
        widget.stop()


def test_a_single_log_is_not_watched_as_a_folder(qapp, folder):
    """Opening one file is not a request to open its neighbours."""
    widget = LogViewerWidget()
    try:
        widget.open(str(folder / "cbs.log"))
        widget.follow.setChecked(True)
        _write(folder / "other.log", _line("2026-08-27 10:00:30", "other"))
        widget._poll()
        assert widget._set.sources() == ["cbs.log"]
    finally:
        widget.stop()


def test_a_log_that_disappears_does_not_raise(qapp, folder):
    widget = LogViewerWidget()
    try:
        widget.open_folder(str(folder))
        widget.follow.setChecked(True)
        os.remove(folder / "cbs.log")
        widget._poll()          # must not raise
    finally:
        widget.stop()


def test_the_folder_itself_disappearing_does_not_raise(qapp, tmp_path):
    inner = tmp_path / "logs"
    inner.mkdir()
    _write(inner / "cbs.log", _line("2026-08-27 10:00:00", "first"))
    widget = LogViewerWidget()
    try:
        widget.open_folder(str(inner))
        widget.follow.setChecked(True)
        os.remove(inner / "cbs.log")
        inner.rmdir()
        widget._poll()          # must not raise
    finally:
        widget.stop()
