"""Row colours for the process tree.

The tint is most of what makes 270 rows readable, and the thing worth
testing is the ORDER: a row is often several categories at once, so which
one it shows is a real decision rather than an implementation detail.
"""
from modules.process_explorer.color_scheme import (
    CATEGORIES, ProcessColor, category_of, describe, get_row_color,
    get_row_text_color,
)
from modules.process_explorer.process_node import ProcessNode


def _node(**kwargs):
    defaults = dict(pid=100, name="test.exe", exe="", cmdline="",
                    user="testuser", status="running", parent_pid=0)
    defaults.update(kwargs)
    return ProcessNode(**defaults)


# ---- each category ------------------------------------------------------

def test_every_category_has_its_own_colour():
    node_colours = {}
    for attribute, colour, label in CATEGORIES:
        assert get_row_color(_node(**{attribute: True})) == colour, attribute
        node_colours[attribute] = colour.name()
    assert len(set(node_colours.values())) == len(CATEGORIES), \
        "two categories share a colour, so they cannot be told apart"


def test_an_ordinary_process_is_not_tinted():
    assert get_row_color(_node()) == ProcessColor.DEFAULT


def test_every_category_has_a_label():
    for _attribute, _colour, label in CATEGORIES:
        assert label and label.strip() == label


# ---- the order ----------------------------------------------------------

def test_what_just_happened_outranks_what_a_process_is():
    """A process appearing or dying is the most perishable thing about it,
    and the reason the eye goes there at all."""
    assert get_row_color(_node(is_new=True, is_service=True,
                               is_dotnet=True)) == ProcessColor.NEW
    assert get_row_color(_node(is_deleted=True,
                               is_system=True)) == ProcessColor.DELETED


def test_new_outranks_deleted():
    """A pid that came back is a new process, not the old one returning."""
    assert get_row_color(_node(is_new=True,
                               is_deleted=True)) == ProcessColor.NEW


def test_suspended_outranks_what_kind_of_image_it_is():
    assert get_row_color(_node(is_suspended=True,
                               is_dotnet=True)) == ProcessColor.SUSPENDED


def test_a_guess_never_outranks_a_fact():
    """`is_packed` is section entropy, and on this machine it flags
    OneNote. A .NET process with compressed resources must still read as
    .NET rather than as something suspicious."""
    assert get_row_color(_node(is_packed=True,
                               is_dotnet=True)) == ProcessColor.DOTNET
    assert get_row_color(_node(is_packed=True,
                               is_service=True)) == ProcessColor.SERVICE


def test_system_outranks_own():
    assert get_row_color(_node(is_system=True,
                               is_own=True)) == ProcessColor.SYSTEM


def test_gpu_activity_is_not_a_row_colour():
    """It used to be, tinting anything over 0.5%. That colour had never
    once appeared, because `gpu_percent` was never written to -- so it was
    dead code that would have come alive as a REGRESSION the moment the
    GPU column started reporting, overriding the .NET and service tints
    for every process that touches the GPU. Process Explorer has no such
    category; the GPU column carries the number instead.
    """
    assert get_row_color(_node(gpu_percent=99.0)) == ProcessColor.DEFAULT
    assert not hasattr(ProcessColor, "GPU")


# ---- contrast -----------------------------------------------------------

def test_a_tinted_row_gets_dark_text():
    """The app's theme is dark, so its default light text is unreadable on
    every pastel here."""
    for attribute, _colour, _label in CATEGORIES:
        node = _node(**{attribute: True})
        assert get_row_text_color(node) == ProcessColor.TEXT_ON_COLOR


def test_an_untinted_row_leaves_the_text_to_the_palette():
    assert get_row_text_color(_node()).alpha() == 0


def test_every_tint_is_light_enough_for_dark_text():
    """Computed, not eyeballed: dark text on a mid-tone pastel is the same
    unreadable smear the semantic palette exists to prevent."""
    for _attribute, colour, label in CATEGORIES:
        luminance = (0.2126 * colour.redF() + 0.7152 * colour.greenF()
                     + 0.0722 * colour.blueF())
        assert luminance > 0.45, f"{label} is too dark for black text"


# ---- the tooltip --------------------------------------------------------

def test_the_tooltip_names_every_category_not_only_the_visible_one():
    """A row shows one colour but can be four things at once, and the
    three it is not showing are the ones nobody would otherwise find."""
    text = describe(_node(is_new=True, is_service=True, is_dotnet=True,
                          is_own=True))
    for expected in ("Started just now", "Hosts a service", ".NET",
                     "Your process"):
        assert expected in text


def test_the_tooltip_hedges_the_packed_guess_and_shows_its_number():
    text = describe(_node(is_packed=True, packed_entropy=7.42))
    assert "7.42" in text
    assert "heuristic" in text


def test_an_ordinary_process_has_nothing_to_say():
    assert describe(_node()) == ""


def test_category_of_an_ordinary_process_is_none():
    assert category_of(_node()) is None
