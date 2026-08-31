"""Choosing the two colours painted inside a message.

The delegate paints exactly two things into the message text: what the Filter
and Find boxes are looking for, and the error codes that mean the line failed.
Both are a text COLOUR and never a background -- the row already carries a
severity tint, and a block behind the match fights it.

Those two are what is choosable here. Everything else on the row (the severity
tint, the component tint, a highlight rule) is a background and already has its
own editor.
"""
import pytest

from core import semantic_colors
from modules.log_viewer.match_colours import (
    CONFIG_KEY, MEANINGS, default_colour, load_colours, save_colours,
)


class _Config:
    """The two methods `load_colours`/`save_colours` use, and a saved flag."""

    def __init__(self, stored=None):
        self._store = dict(stored or {})
        self.saved = False

    def get(self, key, default=None):
        return self._store.get(key, default)

    def set(self, key, value):
        self._store[key] = value

    def save(self):
        self.saved = True


@pytest.fixture(autouse=True)
def _dark_theme():
    """These assertions name colours, so the theme has to be pinned."""
    was = semantic_colors.current_theme()
    semantic_colors.set_theme("dark")
    yield
    semantic_colors.set_theme(was)


# ---- what a colour falls back to ----------------------------------------

def test_an_unset_colour_follows_the_theme():
    """No override means the semantic palette, so a theme switch is still
    followed rather than frozen to whatever the dark theme wanted."""
    assert default_colour("match") == semantic_colors.semantic("match")
    semantic_colors.set_theme("light")
    assert default_colour("match") == semantic_colors.semantic("match")


def test_both_painted_meanings_are_offered():
    assert set(MEANINGS) == {"match", "error"}


# ---- loading ------------------------------------------------------------

def test_nothing_stored_yields_no_overrides():
    assert load_colours(_Config()) == {}


def test_a_stored_colour_is_returned():
    config = _Config({CONFIG_KEY: {"match": "#ff8800"}})
    assert load_colours(config) == {"match": "#ff8800"}


def test_a_malformed_colour_is_dropped_rather_than_painted():
    """A colour reaches `paint`, a reimplemented Qt virtual, where an
    exception is routed to sys.excepthook and then qFatal() -- it cannot be
    caught and the process dies. A hand-edited config must not be able to do
    that."""
    config = _Config({CONFIG_KEY: {"match": "octarine", "error": "#00ff00"}})
    assert load_colours(config) == {"error": "#00ff00"}


def test_a_meaning_nobody_paints_is_dropped():
    """Storing "banana" would put a swatch in the dialog for something the
    delegate never reads."""
    config = _Config({CONFIG_KEY: {"banana": "#00ff00"}})
    assert load_colours(config) == {}


def test_a_stored_value_of_the_wrong_shape_is_survivable():
    """One bad hand-edit must not cost the user the whole setting."""
    assert load_colours(_Config({CONFIG_KEY: ["not", "a", "mapping"]})) == {}
    assert load_colours(_Config({CONFIG_KEY: None})) == {}


# ---- saving -------------------------------------------------------------

def test_saving_writes_and_persists():
    config = _Config()
    save_colours(config, {"match": "#ff8800"})
    assert config.get(CONFIG_KEY) == {"match": "#ff8800"}
    assert config.saved, "the choice would be lost on the next launch"


def test_saving_an_empty_mapping_clears_the_overrides():
    """That is how Reset gets back to following the theme -- storing the
    current semantic values instead would freeze the dark theme's colours
    into the light theme."""
    config = _Config({CONFIG_KEY: {"match": "#ff8800"}})
    save_colours(config, {})
    assert config.get(CONFIG_KEY) == {}


def test_a_malformed_colour_is_refused_at_save_too():
    config = _Config()
    save_colours(config, {"match": "octarine", "error": "#00ff00"})
    assert config.get(CONFIG_KEY) == {"error": "#00ff00"}


# ---- the delegate paints with them --------------------------------------

import re  # noqa: E402

from modules.log_viewer.log_delegate import LogMessageDelegate  # noqa: E402


def _needles(patterns):
    return [re.compile(re.escape(p), re.IGNORECASE) for p in patterns]


def test_the_match_colour_can_be_overridden(qapp):
    html = LogMessageDelegate.rich_text(
        "Opening package alpha", "#123456", _needles(["package"]),
        match_colour="#ff8800")
    assert 'color:#ff8800' in html
    assert semantic_colors.semantic("match") not in html


def test_the_error_colour_can_be_overridden(qapp):
    html = LogMessageDelegate.rich_text(
        "Failed [HRESULT = 0x800f0805]", "#123456", (),
        error_colour="#00ff00")
    assert 'color:#00ff00' in html


def test_an_unset_override_still_uses_the_theme(qapp):
    """Overriding one must not blank the other."""
    html = LogMessageDelegate.rich_text(
        "Failed 0x800f0805 opening package", "#123456",
        _needles(["package"]), match_colour="#ff8800")
    assert 'color:#ff8800' in html
    assert semantic_colors.semantic("error") in html


def test_a_match_is_a_colour_and_never_a_background(qapp):
    """The whole point of the change: the row keeps its severity tint and
    only the matched characters change colour."""
    html = LogMessageDelegate.rich_text(
        "Opening package alpha", "#123456", _needles(["package"]),
        match_colour="#ff8800")
    assert "background" not in html.lower()


def test_the_delegate_carries_the_chosen_colours_into_paint(qapp):
    delegate = LogMessageDelegate()
    delegate.set_needles(["package"])
    delegate.set_colours({"match": "#ff8800"})

    html = delegate.message_html("Opening package alpha", "#123456")

    assert 'color:#ff8800' in html


def test_setting_no_colours_goes_back_to_the_theme(qapp):
    delegate = LogMessageDelegate()
    delegate.set_needles(["package"])
    delegate.set_colours({"match": "#ff8800"})
    delegate.set_colours({})

    html = delegate.message_html("Opening package alpha", "#123456")

    assert semantic_colors.semantic("match") in html


def test_a_malformed_colour_never_reaches_the_delegate(qapp):
    """Belt and braces with `load_colours`: `set_colours` is public, and
    what it accepts is painted inside a Qt virtual."""
    delegate = LogMessageDelegate()
    delegate.set_needles(["package"])
    delegate.set_colours({"match": "octarine"})

    html = delegate.message_html("Opening package alpha", "#123456")

    assert semantic_colors.semantic("match") in html


# ---- the pane wires it together -----------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[Failed to open package alpha]LOG]!><time="13:45:10.000+000" '
    'date="08-20-2026" component="CBS" context="" type="1" thread="1" '
    'file="a.cpp:1">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_the_pane_starts_following_the_theme(viewer):
    assert viewer._match_colours == {}


def test_choosing_a_colour_reaches_the_delegate(viewer):
    viewer.filter_box.setText("package")
    viewer.set_match_colours({"match": "#ff8800"})

    html = viewer.message_delegate.message_html("opening package", "#123456")

    assert 'color:#ff8800' in html


def test_a_malformed_choice_is_refused_by_the_pane(viewer):
    viewer.set_match_colours({"match": "octarine"})
    assert viewer._match_colours == {}


def test_the_button_is_there_to_open_it(viewer):
    assert viewer.colour_button is not None
