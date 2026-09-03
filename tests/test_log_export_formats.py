"""Markdown for a ticket, HTML for a colleague.

The text and CSV writers drop exactly the information the colouring was added
to carry: which rows are failures. HTML keeps it. Markdown keeps none of it
but pastes into a ticket without reformatting, which is the other half of
getting a finding out of the tool.
"""
from datetime import datetime


from core.types import LogEntry
from modules.log_viewer.log_export import as_html, as_markdown


def _entry(message, level="Info", source="CBS", thread="1"):
    return LogEntry(timestamp=datetime(2026, 8, 27, 10, 0, 0),
                    source=source, level=level, message=message,
                    raw={"thread": thread})


# ---- Markdown -----------------------------------------------------------

def test_markdown_has_a_header_row_and_a_rule():
    out = as_markdown([_entry("hello")])
    lines = out.splitlines()
    assert lines[0].startswith("| Time")
    assert set(lines[1].replace("|", "").replace(" ", "")) <= {"-", ":"}


def test_markdown_carries_every_column():
    out = as_markdown([_entry("hello", level="Error", source="CSI",
                              thread="42")])
    assert "Error" in out and "CSI" in out and "42" in out and "hello" in out


def test_a_pipe_in_a_message_is_escaped():
    """CBS messages contain pipes. Unescaped, one row silently becomes two
    columns and every row after it is misaligned."""
    out = as_markdown([_entry("a | b")])
    assert r"a \| b" in out


def test_a_newline_in_a_message_does_not_break_the_table():
    """A stack trace is one entry. A raw newline would end the row."""
    out = as_markdown([_entry("line one\nline two")])
    assert len(out.splitlines()) == 3, "header, rule, one row"


def test_no_entries_still_yields_a_usable_table():
    out = as_markdown([])
    assert out.splitlines()[0].startswith("| Time")


def test_markdown_writes_the_real_message_not_the_display_suffix():
    """The `(+N lines)` suffix is display-only; the existing exports pin the
    same rule."""
    out = as_markdown([_entry("Performing 3 operations")])
    assert "(+" not in out


# ---- HTML ---------------------------------------------------------------

def test_html_is_a_whole_document():
    out = as_html([_entry("hello")])
    assert out.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in out


def test_html_escapes_angle_brackets():
    """A CMTrace record is literally `<![LOG[...]]>`. Unescaped it would eat
    the rest of the document."""
    out = as_html([_entry("<![LOG[boom]LOG]!> & more")])
    assert "&lt;![LOG[boom]LOG]!&gt;" in out
    assert "&amp; more" in out


def test_html_marks_an_error_row_differently_from_an_info_row():
    out = as_html([_entry("bad", level="Error"), _entry("fine")])
    assert 'class="Error"' in out
    assert 'class="Info"' in out


def test_html_carries_a_style_for_every_severity_it_uses():
    out = as_html([_entry("bad", level="Error")])
    assert ".Error" in out, "the class is emitted but never styled"


def test_html_says_what_it_is():
    """Same provenance note the text export carries: a parsed view, not a
    byte-for-byte copy."""
    out = as_html([_entry("hello")])
    assert "not a byte-for-byte copy" in out


def test_html_with_no_entries_is_still_valid():
    out = as_html([])
    assert "</html>" in out
