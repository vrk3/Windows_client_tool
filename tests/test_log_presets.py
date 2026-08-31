"""Named filters worth keeping.

The knowledge of what to grep for is the expensive part of reading a
servicing log, and it should not live in one person's head.

Every shipped preset is checked against the real log it targets before it is
shipped -- a preset that matches nothing is worse than no preset, because it
answers "there is no such problem here" when it means "I was written wrong".
"""
import pytest

from modules.log_viewer.presets import (
    BUILT_IN, Preset, load_presets, save_presets,
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


# ---- the shipped set ----------------------------------------------------

def test_every_shipped_preset_has_a_name_and_does_something():
    assert BUILT_IN
    for preset in BUILT_IN:
        assert preset.name
        assert preset.needle or preset.exclude or preset.levels, \
            f"{preset.name} filters on nothing"


def test_shipped_names_are_unique():
    names = [preset.name for preset in BUILT_IN]
    assert len(names) == len(set(names))


def test_a_shipped_preset_round_trips_through_a_dict():
    for preset in BUILT_IN:
        assert Preset.from_dict(preset.as_dict()) == preset


# ---- persistence --------------------------------------------------------

def test_user_presets_round_trip():
    config = _Config()
    mine = Preset(name="mine", needle="hello", levels=("Error",))
    save_presets(config, [mine])
    assert load_presets(config) == [mine]


def test_no_config_is_not_an_error():
    assert load_presets(None) == []
    save_presets(None, [])


def test_a_stored_preset_of_the_wrong_shape_is_ignored():
    """Config files get hand-edited and this is applied while the pane is
    being built."""
    assert load_presets(_Config({"log_viewer.presets": "oops"})) == []
    assert load_presets(_Config({"log_viewer.presets": [1, 2]})) == []


def test_a_preset_missing_its_name_is_dropped_not_shown_blank():
    stored = {"log_viewer.presets": [{"needle": "x"}]}
    assert load_presets(_Config(stored)) == []


def test_one_bad_preset_does_not_discard_the_good_ones():
    stored = {"log_viewer.presets": [{"name": "good", "needle": "x"},
                                     {"needle": "nameless"}]}
    loaded = load_presets(_Config(stored))
    assert [p.name for p in loaded] == ["good"]


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[it broke]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
    'component="CBS" context="" type="3" thread="1" file="a.cpp:1">\n'
    '<![LOG[all fine]LOG]!><time="13:45:11.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:2">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_the_menu_lists_the_shipped_presets(viewer):
    labels = [a.text() for a in viewer.preset_menu.actions()]
    for preset in BUILT_IN:
        assert preset.name in labels


def test_applying_a_preset_sets_every_axis_it_names(viewer):
    viewer.apply_preset(Preset(name="errors only", levels=("Error",)))

    assert viewer.model.rowCount() == 1
    assert viewer._level_boxes["Error"].isChecked()
    assert not viewer._level_boxes["Info"].isChecked()


def test_applying_a_preset_sets_the_text_boxes(viewer):
    viewer.apply_preset(Preset(name="broke", needle="broke", exclude="fine"))
    assert viewer.filter_box.text() == "broke"
    assert viewer.exclude_box.text() == "fine"


def test_applying_a_preset_clears_what_it_does_not_name(viewer):
    """A preset is a whole view, not a patch. Leaving yesterday's exclude in
    place would give a result neither the preset nor the user asked for."""
    viewer.exclude_box.setText("leftover")
    viewer.apply_preset(Preset(name="plain", needle="broke"))
    assert viewer.exclude_box.text() == ""


def test_saving_the_current_view_as_a_preset_keeps_it(viewer):
    viewer.filter_box.setText("broke")
    viewer.exclude_box.setText("noise")

    viewer.save_current_preset("my view")

    saved = [p for p in viewer._presets if p.name == "my view"]
    assert saved and saved[0].needle == "broke" and saved[0].exclude == "noise"
