"""Remembering what you have filtered on.

You retype the same three patterns all day during an investigation. The list
is deliberately a pure function over a list plus two config calls, so the
ordering rules are testable without a widget.
"""
import pytest

from modules.log_viewer.history import (
    HISTORY_CAP, load_history, remember, save_history,
)


# ---- the ordering rules -------------------------------------------------

def test_a_new_entry_goes_to_the_front():
    assert remember(["old"], "new") == ["new", "old"]


def test_the_most_recent_is_first_so_the_completer_offers_it_first():
    history = []
    for text in ("one", "two", "three"):
        history = remember(history, text)
    assert history == ["three", "two", "one"]


def test_repeating_an_entry_moves_it_rather_than_duplicating():
    assert remember(["b", "a"], "a") == ["a", "b"]


def test_the_history_is_capped():
    history = []
    for number in range(HISTORY_CAP + 10):
        history = remember(history, f"pattern {number}")
    assert len(history) == HISTORY_CAP


def test_the_cap_drops_the_OLDEST():
    history = []
    for number in range(HISTORY_CAP + 1):
        history = remember(history, f"pattern {number}")
    assert "pattern 0" not in history
    assert history[0] == f"pattern {HISTORY_CAP}"


def test_an_empty_pattern_is_not_remembered():
    """The clear button empties the box; that is not a search."""
    assert remember(["a"], "") == ["a"]
    assert remember(["a"], "   ") == ["a"]


def test_the_original_list_is_not_mutated():
    original = ["a"]
    remember(original, "b")
    assert original == ["a"]


# ---- persistence --------------------------------------------------------

class _Config:
    def __init__(self, stored=None):
        self._stored = dict(stored or {})
        self.saved = 0

    def get(self, key, default=None):
        return self._stored.get(key, default)

    def set(self, key, value):
        self._stored[key] = value

    def save(self):
        self.saved += 1


def test_history_round_trips_through_the_config():
    config = _Config()
    save_history(config, ["b", "a"])
    assert load_history(config) == ["b", "a"]
    assert config.saved == 1


def test_no_config_is_not_an_error():
    """The pane runs without one in tests and before a config is attached."""
    assert load_history(None) == []
    save_history(None, ["a"])


def test_a_stored_value_of_the_wrong_shape_is_ignored():
    """Config files get hand-edited. A string where a list belongs must not
    take the pane down on open."""
    assert load_history(_Config({"log_viewer.filter_history": "oops"})) == []
    assert load_history(_Config({"log_viewer.filter_history": [1, 2]})) == []


def test_a_stored_history_longer_than_the_cap_is_trimmed_on_load():
    stored = {"log_viewer.filter_history": [f"p{n}" for n in range(HISTORY_CAP + 5)]}
    assert len(load_history(_Config(stored))) == HISTORY_CAP


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[first line]LOG]!><time="13:45:12.345+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _completions(widget):
    model = widget.filter_box.completer().model()
    return [model.data(model.index(row, 0))
            for row in range(model.rowCount())]


def test_pressing_enter_remembers_the_filter(viewer):
    viewer.filter_box.setText("HRESULT")
    viewer.filter_box.returnPressed.emit()
    assert "HRESULT" in _completions(viewer)


def test_typing_alone_does_not_fill_the_history_with_prefixes(viewer):
    """The filter applies live, so every keystroke would otherwise be
    remembered: H, HR, HRE, HRES... Enter is the commit gesture."""
    viewer.filter_box.setText("H")
    viewer.filter_box.setText("HR")
    viewer.filter_box.setText("HRESULT")
    assert _completions(viewer) == []


def test_the_completer_offers_the_most_recent_first(viewer):
    for text in ("one", "two"):
        viewer.filter_box.setText(text)
        viewer.filter_box.returnPressed.emit()
    assert _completions(viewer) == ["two", "one"]


def test_the_completer_matches_anywhere_in_the_pattern(viewer):
    """A log pattern is rarely recalled from its first character."""
    from PyQt6.QtCore import Qt as _Qt
    assert viewer.filter_box.completer().filterMode() == \
        _Qt.MatchFlag.MatchContains


def test_the_history_survives_a_reopen(viewer, tmp_path):
    viewer.filter_box.setText("HRESULT")
    viewer.filter_box.returnPressed.emit()

    other = tmp_path / "second.log"
    other.write_text(CMTRACE, encoding="utf-8")
    viewer.open(str(other))

    assert "HRESULT" in _completions(viewer)


def test_a_stored_history_is_offered_when_the_module_builds_its_widget(qapp):
    """The completer is only useful across sessions if what was saved is
    read back when the pane is built."""
    from modules.log_viewer.log_viewer_module import LogViewerModule

    config = _Config({"log_viewer.filter_history": ["yesterday", "before"]})

    class _App:
        pass

    app = _App()
    app.config = config
    module = LogViewerModule()
    module.app = app
    widget = module.create_widget()
    try:
        assert _completions(widget) == ["yesterday", "before"]
    finally:
        widget.stop()
