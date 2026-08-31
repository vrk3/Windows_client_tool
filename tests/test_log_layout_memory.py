r"""Remembering how the pane was arranged.

Deliberately NOT column widths. The narrow columns are ResizeToContents and
cannot be dragged, and that auto-sizing is what stopped the Source column
rendering every CBS archive as "CbsPersist_20…" -- they differ only in the
timestamp at the END of the name. Making them draggable to make them
memorable would trade a real fix for a preference. Column visibility is
W3-06's job.

What IS adjustable, and so worth keeping: the splitter between the table and
the detail pane, and the two checkboxes that change what you see.
"""
import pytest

from modules.log_viewer.layout import (
    CONFIG_KEY, load_layout, save_layout,
)
from modules.log_viewer.log_viewer_module import LogViewerModule


class _Config:
    def __init__(self, stored=None):
        self._stored = dict(stored or {})

    def get(self, key, default=None):
        return self._stored.get(key, default)

    def set(self, key, value):
        self._stored[key] = value

    def save(self):
        pass


# ---- the stored shape ---------------------------------------------------

def test_a_layout_round_trips():
    config = _Config()
    save_layout(config, {"splitter": [600, 160], "fold": False})
    assert load_layout(config) == {"splitter": [600, 160], "fold": False}


def test_no_config_is_not_an_error():
    assert load_layout(None) == {}
    save_layout(None, {"fold": True})


def test_a_stored_value_of_the_wrong_shape_is_ignored():
    """Config files get hand-edited, and this is applied during widget
    construction where a bad value would take the pane down on open."""
    assert load_layout(_Config({CONFIG_KEY: "oops"})) == {}
    assert load_layout(_Config({CONFIG_KEY: [1, 2]})) == {}


def test_a_splitter_that_is_not_a_list_of_numbers_is_dropped():
    stored = {CONFIG_KEY: {"splitter": ["wide", "narrow"], "fold": True}}
    loaded = load_layout(_Config(stored))
    assert "splitter" not in loaded
    assert loaded["fold"] is True, "the sound half must survive"


def test_a_splitter_with_the_wrong_number_of_panes_is_dropped():
    stored = {CONFIG_KEY: {"splitter": [100, 200, 300]}}
    assert "splitter" not in load_layout(_Config(stored))


# ---- the pane -----------------------------------------------------------

def _module_with(config):
    class _App:
        pass
    app = _App()
    app.config = config
    module = LogViewerModule()
    module.app = app
    return module


def test_the_splitter_and_checkboxes_are_saved_on_stop(qapp):
    config = _Config()
    module = _module_with(config)
    widget = module.create_widget()
    try:
        widget.splitter.setSizes([500, 260])
        widget.fold.setChecked(False)
        widget.regex_box.setChecked(True)
        widget.save_layout_now()
    finally:
        widget.stop()

    stored = config.get(CONFIG_KEY)
    assert stored["fold"] is False
    assert stored["regex"] is True
    assert sum(stored["splitter"]) > 0


def test_a_saved_layout_is_applied_when_the_widget_is_built(qapp):
    config = _Config({CONFIG_KEY: {"fold": False, "regex": True}})
    widget = _module_with(config).create_widget()
    try:
        assert widget.fold.isChecked() is False
        assert widget.regex_box.isChecked() is True
    finally:
        widget.stop()


def test_no_saved_layout_leaves_the_defaults_alone(qapp):
    widget = _module_with(_Config()).create_widget()
    try:
        assert widget.fold.isChecked() is True, "folding is on by default"
        assert widget.regex_box.isChecked() is False
    finally:
        widget.stop()


def test_a_corrupt_layout_does_not_stop_the_pane_opening(qapp):
    widget = _module_with(_Config({CONFIG_KEY: "nonsense"})).create_widget()
    try:
        assert widget.fold.isChecked() is True
    finally:
        widget.stop()
