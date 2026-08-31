r"""The logs you opened recently, and dropping files onto the pane.

Both are about the same thing: getting a log in front of you without typing a
path. You reopen the same handful of paths for the length of an
investigation.
"""
import os

import pytest

from modules.log_viewer.history import (
    RECENT_CAP, load_recent, remember, save_recent,
)
from modules.log_viewer.log_viewer_module import LogViewerWidget

CMTRACE = (
    '<![LOG[first line]LOG]!><time="13:45:12.345+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
)


class _Config:
    def __init__(self, stored=None):
        self._stored = dict(stored or {})

    def get(self, key, default=None):
        return self._stored.get(key, default)

    def set(self, key, value):
        self._stored[key] = value

    def save(self):
        pass


@pytest.fixture
def logs(tmp_path):
    for name in ("cbs.log", "dism.log"):
        (tmp_path / name).write_text(CMTRACE, encoding="utf-8")
    return tmp_path


@pytest.fixture
def viewer(qapp, logs):
    widget = LogViewerWidget()
    yield widget
    widget.stop()


# ---- the list -----------------------------------------------------------

def test_recent_round_trips_through_the_config():
    config = _Config()
    save_recent(config, [r"C:\a.log"])
    assert load_recent(config) == [r"C:\a.log"]


def test_the_recent_list_shares_the_ordering_rules(logs):
    """Same `remember`: most recent first, repeats moved not duplicated."""
    history = remember(remember([], "a"), "b")
    assert remember(history, "a") == ["a", "b"]


def test_recent_is_capped():
    entries = []
    for number in range(RECENT_CAP + 5):
        entries = remember(entries, f"log{number}.log", cap=RECENT_CAP)
    assert len(entries) == RECENT_CAP


# ---- the pane -----------------------------------------------------------

def _menu_labels(widget):
    return [action.text() for action in widget.open_menu.actions()]


def test_opening_a_log_puts_it_in_the_recent_list(viewer, logs):
    viewer.open(str(logs / "cbs.log"))
    assert str(logs / "cbs.log") in viewer._recent


def test_opening_a_folder_is_recorded_as_the_folder(viewer, logs):
    viewer.open_folder(str(logs))
    assert str(logs) in viewer._recent


def test_the_recent_entries_reach_the_open_menu(viewer, logs):
    viewer.open(str(logs / "cbs.log"))
    assert any("cbs.log" in label for label in _menu_labels(viewer))


def test_a_recent_entry_that_is_gone_is_not_offered(viewer, logs):
    """A log can be rolled away between sessions. Offering a path that no
    longer exists is offering an error message."""
    missing = logs / "vanished.log"
    missing.write_text(CMTRACE, encoding="utf-8")
    viewer.open(str(missing))
    os.remove(missing)

    viewer._build_open_menu()

    assert not any("vanished" in label for label in _menu_labels(viewer))


def test_reopening_a_log_does_not_list_it_twice(viewer, logs):
    viewer.open(str(logs / "cbs.log"))
    viewer.open(str(logs / "dism.log"))
    viewer.open(str(logs / "cbs.log"))
    assert viewer._recent.count(str(logs / "cbs.log")) == 1
    assert viewer._recent[0] == str(logs / "cbs.log")


# ---- drag and drop ------------------------------------------------------

def _drop(widget, paths):
    from PyQt6.QtCore import QMimeData, QPointF, QUrl
    from PyQt6.QtGui import QDropEvent
    from PyQt6.QtCore import Qt as _Qt

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(QPointF(1, 1),
                       _Qt.DropAction.CopyAction,
                       mime,
                       _Qt.MouseButton.LeftButton,
                       _Qt.KeyboardModifier.NoModifier)
    widget.dropEvent(event)
    return event


def test_the_pane_accepts_drops(viewer):
    assert viewer.acceptDrops()


def test_dropping_a_log_opens_it(viewer, logs):
    _drop(viewer, [logs / "cbs.log"])
    assert viewer._paths == [str(logs / "cbs.log")]


def test_dropping_a_folder_opens_every_log_in_it(viewer, logs):
    _drop(viewer, [logs])
    assert len(viewer._paths) == 2


def test_dropping_several_files_opens_them_as_one_timeline(viewer, logs):
    _drop(viewer, [logs / "cbs.log", logs / "dism.log"])
    assert len(viewer._paths) == 2


def test_dropping_nothing_useful_says_so_and_keeps_the_current_log(viewer,
                                                                  logs):
    viewer.open(str(logs / "cbs.log"))
    junk = logs / "notes.txt"
    junk.write_text("not a log", encoding="utf-8")

    _drop(viewer, [junk])

    assert viewer._paths == [str(logs / "cbs.log")], "the open log was lost"
    assert "no log" in viewer.status.text().lower()
