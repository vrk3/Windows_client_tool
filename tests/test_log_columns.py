"""Choosing which columns to show.

Thread is dead weight on CBS and essential on DISM's 329 threads, so the
choice has to be the reader's.

Stored by NAME, never by index. COLUMNS has changed three times already --
Source, then Package -- and a saved list of positions would be applied to a
different set of columns and hide the wrong ones.
"""
import pytest

from modules.log_viewer.log_model import COLUMNS, MESSAGE, THREAD
from modules.log_viewer.log_viewer_module import LogViewerWidget

CMTRACE = (
    '<![LOG[a line]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
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
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_hiding_a_column_hides_it(viewer):
    viewer.set_column_hidden("Thread", True)
    assert viewer.table.isColumnHidden(THREAD)


def test_showing_it_again_brings_it_back(viewer):
    viewer.set_column_hidden("Thread", True)
    viewer.set_column_hidden("Thread", False)
    assert not viewer.table.isColumnHidden(THREAD)


def test_the_message_column_cannot_be_hidden(viewer):
    """Hiding it would leave a table of metadata about invisible lines."""
    viewer.set_column_hidden("Message", True)
    assert not viewer.table.isColumnHidden(MESSAGE)


def test_the_header_menu_offers_every_hideable_column(viewer):
    menu = viewer.build_column_menu()
    labels = [action.text() for action in menu.actions()]
    assert "Thread" in labels
    assert "Message" not in labels, "Message is not optional"


def test_the_menu_shows_which_columns_are_on(viewer):
    viewer.set_column_hidden("Thread", True)
    menu = viewer.build_column_menu()
    thread = next(a for a in menu.actions() if a.text() == "Thread")
    assert not thread.isChecked()


def test_the_choice_is_saved_and_restored(qapp, tmp_path):
    config = _Config()
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")

    first = LogViewerWidget()
    first._config = config
    try:
        first.open(str(path))
        first.set_column_hidden("Thread", True)
        first.save_layout_now()
    finally:
        first.stop()

    second = LogViewerWidget()
    try:
        from modules.log_viewer.layout import load_layout
        second.apply_layout(load_layout(config))
        second.open(str(path))
        assert second.table.isColumnHidden(THREAD)
    finally:
        second.stop()


def test_a_saved_name_that_is_no_longer_a_column_is_ignored(qapp, tmp_path):
    """Names, not indices, precisely so this is harmless rather than hiding
    whatever now sits at that position."""
    from modules.log_viewer.layout import CONFIG_KEY, load_layout

    config = _Config({CONFIG_KEY: {"hidden_columns": ["Nonexistent"]}})
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")

    widget = LogViewerWidget()
    try:
        widget.apply_layout(load_layout(config))
        widget.open(str(path))
        for column in range(len(COLUMNS)):
            name = COLUMNS[column]
            if name in ("Source", "Package"):
                continue        # hidden for their own reasons
            assert not widget.table.isColumnHidden(column), \
                f"{name} was hidden by a stale saved name"
    finally:
        widget.stop()


def test_a_hidden_column_choice_survives_opening_another_log(viewer, tmp_path):
    viewer.set_column_hidden("Thread", True)
    other = tmp_path / "second.log"
    other.write_text(CMTRACE, encoding="utf-8")

    viewer.open(str(other))

    assert viewer.table.isColumnHidden(THREAD), \
        "the choice was reset by the reopen"
