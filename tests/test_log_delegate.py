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
    html = LogMessageDelegate.rich_text("Failed [HRESULT = 0x800f0805]")
    assert "0x800f0805" in html
    assert "<span" in html


def test_html_special_characters_in_a_message_are_escaped(qapp):
    """A CBS line can contain <, > and & -- unescaped they would silently
    eat part of the message."""
    html = LogMessageDelegate.rich_text("a <b> & 0x800f0805")
    assert "&lt;b&gt;" in html and "&amp;" in html
