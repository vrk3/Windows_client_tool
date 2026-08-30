"""Where the codes ARE in a line, so the delegate can colour them in place."""
from modules.log_viewer.error_codes import code_spans, find_codes


def test_spans_point_at_the_code_in_the_text():
    text = "Failed to open package. [HRESULT = 0x800f0805 - CBS_E_INVALID]"
    spans = code_spans(text)
    assert len(spans) == 1
    start, end, code = spans[0]
    assert text[start:end] == "0x800f0805"
    assert code == 0x800F0805


def test_every_occurrence_gets_a_span_even_when_the_code_repeats():
    """find_codes de-duplicates because it answers "which codes"; the
    delegate asks "where", and both occurrences must be coloured."""
    text = "0x80070005 then 0x80070005 again"
    assert len(find_codes(text)) == 1
    assert len(code_spans(text)) == 2


def test_no_codes_is_an_empty_list():
    assert code_spans("nothing to see") == []
    assert code_spans("") == []
