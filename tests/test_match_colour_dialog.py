"""Picking the two message colours.

Small on purpose: two swatches and a Reset. The colour-picking itself is
`QColorDialog`'s job, so what is tested here is what the dialog reports back
-- which is the thing that gets painted and persisted.
"""
import pytest

from core import semantic_colors
from modules.log_viewer.match_colours import LABELS, MEANINGS
from modules.log_viewer.match_colour_dialog import MatchColourDialog


@pytest.fixture(autouse=True)
def _dark_theme():
    was = semantic_colors.current_theme()
    semantic_colors.set_theme("dark")
    yield
    semantic_colors.set_theme(was)


@pytest.fixture
def dialog(qapp):
    made = MatchColourDialog({})
    yield made
    made.deleteLater()


def test_every_painted_meaning_gets_a_swatch(dialog):
    for meaning in MEANINGS:
        assert dialog.swatch(meaning) is not None


def test_each_swatch_is_labelled_in_words(dialog):
    """"match" is what the code calls it; the dialog has to say what it
    means on screen."""
    assert LABELS["match"] in dialog.label_for("match")
    assert "error" in dialog.label_for("error").lower()


def test_nothing_chosen_reports_no_overrides(dialog):
    """Not the themed values: storing those would freeze the dark theme's
    colours into the light one."""
    assert dialog.chosen() == {}


def test_an_unset_swatch_still_shows_the_themed_colour(dialog):
    """The user has to see what it is now to decide whether to change it."""
    assert dialog.shown_colour("match") == semantic_colors.semantic("match")


def test_choosing_a_colour_reports_it(dialog):
    dialog.set_colour("match", "#ff8800")
    assert dialog.chosen() == {"match": "#ff8800"}
    assert dialog.shown_colour("match") == "#ff8800"


def test_an_existing_override_is_shown_when_the_dialog_opens(qapp):
    made = MatchColourDialog({"error": "#00ff00"})
    try:
        assert made.shown_colour("error") == "#00ff00"
        assert made.chosen() == {"error": "#00ff00"}
    finally:
        made.deleteLater()


def test_reset_goes_back_to_following_the_theme(qapp):
    made = MatchColourDialog({"match": "#ff8800", "error": "#00ff00"})
    try:
        made.reset()
        assert made.chosen() == {}
        assert made.shown_colour("match") == semantic_colors.semantic("match")
    finally:
        made.deleteLater()


def test_the_two_colours_are_set_independently(dialog):
    dialog.set_colour("match", "#ff8800")
    assert dialog.chosen() == {"match": "#ff8800"}, "error was set too"


def test_a_malformed_colour_is_refused_rather_than_shown(dialog):
    """`set_colour` is public and what it takes ends up in a Qt virtual."""
    dialog.set_colour("match", "octarine")
    assert dialog.chosen() == {}


def test_the_preview_shows_a_real_match_in_context(dialog):
    """A hex swatch does not answer "is that readable on a log row". The
    preview is a real message with a real match coloured in it."""
    dialog.set_colour("match", "#ff8800")
    assert "#ff8800" in dialog.preview_html()


def test_the_preview_never_paints_a_background(dialog):
    """The whole reason this dialog exists: a match is a colour, not a
    highlight. A preview that blocked the text would be advertising the bug
    being fixed."""
    dialog.set_colour("match", "#ff8800")
    assert "background" not in dialog.preview_html().lower()
