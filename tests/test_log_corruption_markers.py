r"""Phrases that mean the component store is damaged.

A servicing failure says so in words as often as in a code, and those words
currently render as ordinary Info-coloured text. `0x800f0805` gets picked out;
"cannot repair the file" does not, and it is the more actionable of the two.

Every fixture below is a real line shape from this machine's own CBS logs.
The narrowness matters: a marker that fires on prose would colour thousands of
rows and stop meaning anything, so each pattern is anchored to the wording
Windows actually emits.
"""

from modules.log_viewer.error_codes import corruption_spans


def _labels(text):
    return [label for _start, _end, label in corruption_spans(text)]


def _marked(text):
    return [text[start:end] for start, end, _label in corruption_spans(text)]


# ---- what must be flagged ----------------------------------------------

def test_an_sxs_status_is_flagged():
    text = ("Failed to pin deployment while resolving Update: "
            "[HRESULT = 0x80073701 - STATUS_SXS_ASSEMBLY_MISSING]")
    assert "STATUS_SXS_ASSEMBLY_MISSING" in _marked(text)


def test_any_sxs_status_is_flagged_not_just_a_known_list():
    """New SXS statuses appear with new Windows builds; the pattern must not
    be a hardcoded roster that silently stops matching."""
    assert "STATUS_SXS_SOMETHING_NEW" in _marked(
        "hr = STATUS_SXS_SOMETHING_NEW here")


def test_cannot_repair_is_flagged():
    text = ("CSI Store check FAILED: cannot repair member file "
            "[l:24]'msxml3.dll'")
    assert _marked(text) == ["cannot repair"]


def test_store_corruption_is_flagged():
    assert _marked("Detected store corruption; beginning repair") == \
        ["store corruption"]


def test_a_hash_mismatch_is_flagged():
    text = ("Hashes for file member \\SystemRoot\\WinSxS\\msxml3.dll do not "
            "match actual file")
    assert _marked(text) == ["do not match"]


def test_several_markers_in_one_line_are_all_flagged():
    text = "store corruption found, cannot repair member"
    assert _marked(text) == ["store corruption", "cannot repair"]


def test_the_label_names_what_was_found():
    labels = _labels("Detected store corruption")
    assert labels == ["store corruption"]


# ---- what must NOT be flagged -------------------------------------------

def test_an_ordinary_line_is_not_flagged():
    assert corruption_spans(
        "Appl: detectParent: parent found: Package_1, state: Installed") == []


def test_a_successful_repair_is_not_flagged():
    """"Repair" on its own is routine -- CBS says it constantly while
    everything is fine."""
    assert corruption_spans("Repair session completed successfully") == []


def test_the_word_corruption_alone_is_not_enough():
    """Prose about corruption is not a corrupt store."""
    assert corruption_spans("checking for corruption") == []


def test_matching_is_case_insensitive():
    assert _marked("CANNOT REPAIR the member") == ["CANNOT REPAIR"]


def test_an_empty_message_is_handled():
    assert corruption_spans("") == []


# ---- the spans have to be usable by the delegate ------------------------

def test_spans_are_returned_in_order_and_do_not_overlap():
    text = "store corruption then cannot repair then STATUS_SXS_X"
    spans = corruption_spans(text)
    assert spans == sorted(spans)
    for earlier, later in zip(spans, spans[1:]):
        assert earlier[1] <= later[0], "overlapping spans would nest tags"


def test_the_span_offsets_actually_bracket_the_marker():
    text = "prefix cannot repair suffix"
    start, end, label = corruption_spans(text)[0]
    assert text[start:end].lower() == label
