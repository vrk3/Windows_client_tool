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
