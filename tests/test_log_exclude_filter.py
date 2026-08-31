"""Hiding lines that match a pattern -- the inverse of the Filter box.

A real CBS.log is mostly boilerplate: `Appl: detectParent` and
`Plan: Package` account for the large majority of its records, and no
positive filter removes them without also removing everything else. Excluding
two patterns is what makes the rest readable.

Kept apart from the include filter deliberately: they answer different
questions, and sharing one box would mean inventing a syntax for negation.
"""
from datetime import datetime

import pytest

from core.types import LogEntry
from modules.log_viewer.log_model import LogModel, MESSAGE
from modules.log_viewer.log_viewer_module import LogViewerWidget


def _entry(message, level="Info", source="CBS"):
    return LogEntry(timestamp=datetime(2026, 8, 27, 10, 0, 0),
                    source=source, level=level, message=message,
                    raw={"thread": "1"})


def _model(entries=()):
    model = LogModel()
    model.append(list(entries))
    return model


def _messages(model):
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


NOISE = "Appl: detectParent: parent found: Package_1"
SIGNAL = "Failed to open package [HRESULT = 0x800f0805]"


# ---- the model ----------------------------------------------------------

def test_an_exclude_pattern_hides_matching_rows(qapp):
    model = _model([_entry(NOISE), _entry(SIGNAL)])

    model.set_filter(exclude="detectParent")

    assert _messages(model) == [SIGNAL]


def test_no_exclude_pattern_hides_nothing(qapp):
    model = _model([_entry(NOISE), _entry(SIGNAL)])
    assert len(_messages(model)) == 2


def test_clearing_the_exclude_brings_the_rows_back(qapp):
    model = _model([_entry(NOISE), _entry(SIGNAL)])
    model.set_filter(exclude="detectParent")

    model.set_filter(exclude="")

    assert len(_messages(model)) == 2


def test_exclude_is_case_insensitive_like_the_include_filter(qapp):
    model = _model([_entry(NOISE), _entry(SIGNAL)])

    model.set_filter(exclude="DETECTPARENT")

    assert _messages(model) == [SIGNAL]


def test_exclude_applies_after_the_include_filter(qapp):
    """Include narrows, exclude then removes from what is left. The other
    order would let an exclude resurrect a row the include had dropped."""
    model = _model([_entry(NOISE), _entry(SIGNAL), _entry("unrelated")])

    model.set_filter(needle="Package", exclude="detectParent")

    assert _messages(model) == [SIGNAL]


def test_exclude_matches_the_whole_row_not_just_the_message(qapp):
    """The same `haystack()` the include filter and the highlight rules use,
    so the three can never quietly disagree about what "the row" is."""
    model = _model([_entry("nothing special", source="CSI"),
                    _entry("nothing special either", source="CBS")])

    model.set_filter(exclude="CSI")

    assert _messages(model) == ["nothing special either"]


def test_exclude_honours_the_regex_box(qapp):
    model = _model([_entry(NOISE), _entry(SIGNAL)])

    model.set_filter(exclude=r"detect\w+", regex=True)

    assert _messages(model) == [SIGNAL]


def test_a_half_typed_exclude_pattern_hides_nothing(qapp):
    """An unfinished regex is a keystroke, not a request to empty the table.
    The include filter already treats one that way."""
    model = _model([_entry(NOISE), _entry(SIGNAL)])

    model.set_filter(exclude="detect(", regex=True)

    assert len(_messages(model)) == 2
    assert model.exclude_pattern_is_invalid() is True


def test_a_finished_exclude_pattern_is_not_reported_invalid(qapp):
    model = _model([_entry(NOISE)])
    model.set_filter(exclude="detect", regex=True)
    assert model.exclude_pattern_is_invalid() is False


def test_excluding_everything_is_allowed(qapp):
    """Unlike an invalid pattern, a valid one that matches every row is a
    real answer and the table is right to be empty."""
    model = _model([_entry(NOISE), _entry(SIGNAL)])

    model.set_filter(exclude="e")

    assert _messages(model) == []


# ---- the pane -----------------------------------------------------------

CMTRACE = (
    '<![LOG[Appl: detectParent: parent found]LOG]!><time="13:45:12.345+000" '
    'date="08-20-2026" component="CBS" context="" type="1" thread="1" '
    'file="a.cpp:1">\n'
    '<![LOG[Failed to open package]LOG]!><time="13:45:13.000+000" '
    'date="08-20-2026" component="CBS" context="" type="3" thread="1" '
    'file="b.cpp:2">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_typing_in_the_exclude_box_hides_rows(viewer):
    viewer.exclude_box.setText("detectParent")
    assert _messages(viewer.model) == ["Failed to open package"]


def test_clearing_the_exclude_box_restores_the_rows(viewer):
    viewer.exclude_box.setText("detectParent")
    viewer.exclude_box.setText("")
    assert len(_messages(viewer.model)) == 2


def test_an_unfinished_exclude_pattern_says_so_in_the_status(viewer):
    viewer.regex_box.setChecked(True)
    viewer.exclude_box.setText("detect(")
    assert "not finished" in viewer.status.text().lower()
    assert len(_messages(viewer.model)) == 2


def test_the_exclude_survives_a_reopen_and_the_model_agrees(viewer, tmp_path):
    """The include filter deliberately survives opening another log, so this
    does too -- one text box clearing while its neighbour does not would be
    the surprising behaviour.

    What must never happen is the shape that has bitten this pane twice: the
    widget and the model disagreeing about what is filtered. So the assertion
    is that they still match, not that either is empty.
    """
    viewer.exclude_box.setText("detectParent")
    other = tmp_path / "second.log"
    other.write_text(CMTRACE, encoding="utf-8")

    viewer.open(str(other))

    assert viewer.exclude_box.text() == "detectParent"
    assert viewer.model._exclude == "detectParent", \
        "the box and the model disagree about what is hidden"
    assert _messages(viewer.model) == ["Failed to open package"]


def test_the_excluded_term_is_not_coloured_as_a_match(viewer):
    """Colouring marks what you are looking FOR. An excluded term is by
    definition not on screen, so it must not join the match needles."""
    viewer.exclude_box.setText("detectParent")
    patterns = [n.pattern for n in viewer.message_delegate.needles]
    assert "detectParent" not in patterns


# ---- W1-02: saying when a filter matched nothing -------------------------
#
# An empty table reads as "this log has no such records". It is a different
# statement from "your filter removed everything", and the pane has to make
# which one it means unambiguous.

def test_a_filter_matching_nothing_says_so(viewer):
    viewer.filter_box.setText("nothing whatsoever matches this")
    assert "no rows match" in viewer.status.text().lower()


def test_a_filter_matching_something_does_not_say_it(viewer):
    viewer.filter_box.setText("package")
    assert "no rows match" not in viewer.status.text().lower()


def test_an_empty_log_does_not_blame_the_filter(qapp, tmp_path):
    """Nothing loaded is not the same as a filter that removed everything."""
    path = tmp_path / "empty.log"
    path.write_text("", encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.filter_box.setText("anything")
        assert "no rows match" not in widget.status.text().lower()
    finally:
        widget.stop()


def test_the_hide_box_emptying_the_table_says_so_too(viewer):
    viewer.exclude_box.setText("e")
    assert "no rows match" in viewer.status.text().lower()


def test_the_count_updates_on_every_keystroke(viewer):
    """textChanged is already wired; this pins it, because a count that only
    refreshes on commit is worse than none."""
    viewer.filter_box.setText("Failed")
    first = viewer.status.text()
    viewer.filter_box.setText("Failed to open")
    assert viewer.status.text() == first or "1 shown" in viewer.status.text()
    assert "shown of" in viewer.status.text()
