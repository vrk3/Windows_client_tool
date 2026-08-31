"""The Message column's delegate.

Only rows whose message actually carries a code take the rich-text path;
Qt paints only the visible rows, so the cost is bounded by the viewport
rather than by the 134,527 records behind it.
"""
from modules.log_viewer.log_delegate import LogMessageDelegate


def test_a_plain_message_keeps_the_fast_path(qapp):
    assert LogMessageDelegate.needs_rich_text("nothing interesting") is False


def test_a_message_with_a_failing_code_is_painted_rich(qapp):
    assert LogMessageDelegate.needs_rich_text(
        "Failed [HRESULT = 0x800f0805]") is True


def test_a_success_code_does_not_earn_rich_text(qapp):
    """97% of the coded lines in a real CBS.log carry nothing but 0x00000000;
    colouring those would put "success" on screen four thousand times."""
    assert LogMessageDelegate.needs_rich_text("done [HRESULT = 0x00000000]") \
        is False


def test_the_delegate_produces_html_marking_the_code(qapp):
    base_colour = "#123456"
    html = LogMessageDelegate.rich_text("Failed [HRESULT = 0x800f0805]",
                                        base_colour)
    assert "0x800f0805" in html
    assert "<span" in html


def test_html_special_characters_in_a_message_are_escaped(qapp):
    """A CBS line can contain <, > and & -- unescaped they would silently
    eat part of the message."""
    base_colour = "#123456"
    html = LogMessageDelegate.rich_text("a <b> & 0x800f0805", base_colour)
    assert "&lt;b&gt;" in html and "&amp;" in html


def test_rich_text_embeds_the_base_colour_in_plain_segments(qapp):
    """The base colour is embedded in the HTML so plain text does not
    inherit the ambient pen colour."""
    base_colour = "#123456"
    html = LogMessageDelegate.rich_text("Failed [HRESULT = 0x800f0805]",
                                        base_colour)
    assert base_colour in html
    # Verify the plain text (not just the code) carries the colour
    assert 'style="color:#123456"' in html


def test_error_code_colour_differs_from_base_colour(qapp):
    """The error code gets its own colour, not the base colour."""
    base_colour = "#123456"
    html = LogMessageDelegate.rich_text("Failed [HRESULT = 0x800f0805]",
                                        base_colour)
    # The base colour appears in the plain text
    assert base_colour in html
    # The error colour is different and also present
    from core.semantic_colors import semantic
    error_colour = semantic("error")
    assert error_colour in html
    # And they are different (not both the same colour)
    assert base_colour != error_colour


# ---- colouring what the Filter and Find boxes are looking for -----------
#
# The text you searched for should be findable by eye in the row the search
# put in front of you. Colour only -- no background -- so it never competes
# with the severity tint the row already carries.

from core.semantic_colors import semantic                        # noqa: E402


def _needles(patterns, regex=False):
    delegate = LogMessageDelegate()
    delegate.set_needles(patterns, regex=regex)
    return delegate.needles


def test_a_message_carrying_the_needle_earns_rich_text(qapp):
    assert LogMessageDelegate.needs_rich_text(
        "Opening package alpha", _needles(["package"])) is True


def test_a_message_without_the_needle_keeps_the_fast_path(qapp):
    """Qt paints only the visible rows, but the fast path still matters --
    every row of a 134,527-record log would otherwise build a QTextDocument."""
    assert LogMessageDelegate.needs_rich_text(
        "Opening package alpha", _needles(["absent"])) is False


def test_no_needle_at_all_keeps_the_fast_path(qapp):
    assert LogMessageDelegate.needs_rich_text("anything", ()) is False


def test_the_needle_is_wrapped_in_the_match_colour(qapp):
    html = LogMessageDelegate.rich_text("Opening package alpha", "#123456",
                                        _needles(["package"]))
    assert f'<span style="color:{semantic("match")}">package</span>' in html


def test_the_match_colour_is_its_own_meaning(qapp):
    """Not the error red and not the info blue -- a match is not a severity."""
    assert semantic("match") != semantic("error")
    assert semantic("match") != semantic("info")


def test_a_match_is_coloured_and_never_given_a_background(qapp):
    """`just color ( not higlight )` -- a background would fight the severity
    tint the row already carries."""
    html = LogMessageDelegate.rich_text("Opening package alpha", "#123456",
                                        _needles(["package"]))
    assert "background" not in html.lower()


def test_matching_ignores_case_the_way_the_filter_does(qapp):
    html = LogMessageDelegate.rich_text("Opening PACKAGE alpha", "#123456",
                                        _needles(["package"]))
    assert f'<span style="color:{semantic("match")}">PACKAGE</span>' in html


def test_every_occurrence_is_coloured_not_just_the_first(qapp):
    html = LogMessageDelegate.rich_text("package and package", "#123456",
                                        _needles(["package"]))
    assert html.count(f'color:{semantic("match")}') == 2


def test_a_plain_needle_is_not_treated_as_a_regular_expression(qapp):
    """With Regex off, `a.c` means those three characters."""
    assert LogMessageDelegate.needs_rich_text("abc", _needles(["a.c"])) is False
    assert LogMessageDelegate.needs_rich_text("a.c", _needles(["a.c"])) is True


def test_a_pattern_matches_when_the_regex_box_is_on(qapp):
    assert LogMessageDelegate.needs_rich_text(
        "abc", _needles(["a.c"], regex=True)) is True


def test_a_half_typed_pattern_colours_nothing_rather_than_raising(qapp):
    """`paint` is a reimplemented Qt virtual: an exception out of it goes to
    sys.excepthook and then qFatal(), so it CANNOT be caught and the process
    dies. A half-typed regex is a keystroke, not a crash."""
    delegate = LogMessageDelegate()
    delegate.set_needles(["Open(package"], regex=True)
    assert delegate.needles == []
    assert LogMessageDelegate.needs_rich_text("Open(package", []) is False


def test_a_failing_code_keeps_its_error_colour_when_a_match_overlaps_it(qapp):
    """Searching for the code must not stop it reading as a failure."""
    html = LogMessageDelegate.rich_text(
        "Failed [HRESULT = 0x800f0805]", "#123456", _needles(["0x800f0805"]))
    assert f'<span style="color:{semantic("error")}">0x800f0805</span>' in html


def test_a_match_beside_a_failing_code_still_gets_its_own_colour(qapp):
    html = LogMessageDelegate.rich_text(
        "Failed opening [HRESULT = 0x800f0805]", "#123456",
        _needles(["opening"]))
    assert f'<span style="color:{semantic("match")}">opening</span>' in html
    assert f'<span style="color:{semantic("error")}">0x800f0805</span>' in html


def test_html_special_characters_around_a_match_are_still_escaped(qapp):
    html = LogMessageDelegate.rich_text("a <b> & package", "#123456",
                                        _needles(["package"]))
    assert "&lt;b&gt;" in html and "&amp;" in html


def test_a_match_containing_html_characters_is_escaped_too(qapp):
    html = LogMessageDelegate.rich_text("tag <b> here", "#123456",
                                        _needles(["<b>"]))
    assert "<b>" not in html.replace("<b>&", "")
    assert "&lt;b&gt;" in html


def test_an_empty_needle_matches_nothing(qapp):
    """An empty Filter box is not a match on every character."""
    assert LogMessageDelegate.needs_rich_text("anything", _needles([""])) \
        is False
