"""Filtering on more than one word at a time.

"these two words, either order" is the everyday case and regex is the wrong
tool for it. Space-separated terms are ANDed; a quoted phrase is one term.
"""
from datetime import datetime

import pytest

from core.types import LogEntry
from modules.log_viewer.log_model import LogModel, MESSAGE


def _entry(message):
    return LogEntry(timestamp=datetime(2026, 8, 27, 10, 0, 0), source="CBS",
                    level="Info", message=message, raw={"thread": "1"})


def _model(messages):
    model = LogModel()
    model.append([_entry(m) for m in messages])
    return model


def _messages(model):
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


ROWS = ["install package alpha",
        "remove package beta",
        "install driver gamma",
        "unrelated line"]


def test_two_terms_are_anded():
    model = _model(ROWS)
    model.set_filter(needle="install package")
    assert _messages(model) == ["install package alpha"]


def test_the_terms_may_appear_in_any_order():
    model = _model(ROWS)
    model.set_filter(needle="package install")
    assert _messages(model) == ["install package alpha"]


def test_one_term_behaves_as_before():
    model = _model(ROWS)
    model.set_filter(needle="package")
    assert len(_messages(model)) == 2


def test_a_quoted_phrase_is_a_single_term():
    model = _model(ROWS)
    model.set_filter(needle='"install package"')
    assert _messages(model) == ["install package alpha"]


def test_a_quoted_phrase_is_not_matched_out_of_order():
    model = _model(ROWS)
    model.set_filter(needle='"package install"')
    assert _messages(model) == []


def test_terms_are_still_case_insensitive():
    model = _model(ROWS)
    model.set_filter(needle="INSTALL Package")
    assert _messages(model) == ["install package alpha"]


def test_regex_mode_treats_the_whole_box_as_one_pattern():
    """A regex contains spaces of its own; splitting it would break it."""
    model = _model(ROWS)
    model.set_filter(needle=r"install (package|driver)", regex=True)
    assert len(_messages(model)) == 2


def test_an_unmatched_quote_does_not_break_the_filter():
    """A half-typed phrase is a keystroke, not a syntax error."""
    model = _model(ROWS)
    model.set_filter(needle='"install')
    assert _messages(model) == ["install package alpha",
                                "install driver gamma"]


def test_extra_spaces_are_not_empty_terms():
    """An empty term matches everything, so leaving one in would silently
    widen the filter back out."""
    model = _model(ROWS)
    model.set_filter(needle="  install   package  ")
    assert _messages(model) == ["install package alpha"]


def test_the_exclude_box_splits_the_same_way():
    model = _model(ROWS)
    model.set_filter(exclude="install package")
    assert "install package alpha" not in _messages(model)
    assert "install driver gamma" in _messages(model)


# ---- the colouring has to follow the same split -------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[install package alpha]LOG]!><time="13:45:10.000+000" '
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


def test_each_term_is_coloured_not_the_whole_box(viewer):
    """The row contains "install" and "package" but never the literal
    "install package" as typed with the words adjacent in that order... it
    does here, but the delegate must still colour them as separate needles,
    or a filter like "package install" would match rows and highlight
    nothing in them."""
    viewer.filter_box.setText("package install")

    patterns = [n.pattern for n in viewer.message_delegate.needles]

    assert "package" in patterns and "install" in patterns
    assert "package install" not in patterns


def test_a_quoted_phrase_is_coloured_as_one_needle(viewer):
    """Asserted by behaviour, not by the escaped spelling: `re.escape` has
    changed which characters it escapes between Python versions."""
    viewer.filter_box.setText('"install package"')

    needles = viewer.message_delegate.needles

    assert len(needles) == 1
    assert needles[0].search("install package alpha")
    assert not needles[0].search("package install alpha")


def test_regex_mode_still_colours_the_whole_pattern(viewer):
    viewer.regex_box.setChecked(True)
    viewer.filter_box.setText(r"install (package|driver)")
    patterns = [n.pattern for n in viewer.message_delegate.needles]
    assert r"install (package|driver)" in patterns
