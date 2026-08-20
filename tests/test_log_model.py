"""The log viewer's table model: colouring, filtering, the cap, and find."""
from datetime import datetime

import pytest
from PyQt6.QtCore import Qt

from core.types import LogEntry
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.log_model import (
    COMPONENT, LogModel, MESSAGE, SEVERITY, THREAD, TIME,
)


def _entry(message, level="Info", source="C", thread="1", when=None):
    return LogEntry(timestamp=when or datetime(2026, 8, 20, 13, 45, 12),
                    source=source, level=level, message=message,
                    raw={"thread": thread})


def _model(entries=(), cap=None):
    model = LogModel(cap=cap) if cap else LogModel()
    model.append(list(entries))
    return model


# ---- content ------------------------------------------------------------

def test_rows_and_columns(qapp):
    model = _model([_entry("one"), _entry("two")])
    assert model.rowCount() == 2
    assert model.columnCount() == 5


def test_each_column_shows_its_field(qapp):
    model = _model([_entry("hello", level="Error", source="Comp", thread="77")])
    row = model.index(0, 0)
    assert model.data(model.index(0, SEVERITY)) == "Error"
    assert model.data(model.index(0, COMPONENT)) == "Comp"
    assert model.data(model.index(0, THREAD)) == "77"
    assert model.data(model.index(0, MESSAGE)) == "hello"
    assert "2026-08-20 13:45:12" in model.data(model.index(0, TIME))


def test_an_unknown_time_shows_blank_not_year_one(qapp):
    """"0001-01-01" reads as a real timestamp and is not one."""
    model = _model([_entry("x", when=UNKNOWN_TIME)])
    assert model.data(model.index(0, TIME)) == ""


def test_a_multi_line_message_stays_on_one_row(qapp):
    """Letting the newlines through breaks the row height for the whole
    table; the full text is still on the tooltip."""
    model = _model([_entry("first\nsecond")])
    shown = model.data(model.index(0, MESSAGE))
    assert "\n" not in shown
    assert model.data(model.index(0, MESSAGE), Qt.ItemDataRole.ToolTipRole) \
        == "first\nsecond"


# ---- colouring ----------------------------------------------------------

def test_errors_and_warnings_are_coloured(qapp):
    model = _model([_entry("e", level="Error"), _entry("w", level="Warning"),
                    _entry("i", level="Info")])
    background = Qt.ItemDataRole.BackgroundRole
    assert model.data(model.index(0, 0), background) is not None
    assert model.data(model.index(1, 0), background) is not None
    assert model.data(model.index(2, 0), background) is None


def test_error_and_warning_do_not_share_a_colour(qapp):
    model = _model([_entry("e", level="Error"), _entry("w", level="Warning")])
    background = Qt.ItemDataRole.BackgroundRole
    assert (model.data(model.index(0, 0), background)
            != model.data(model.index(1, 0), background))


def test_coloured_rows_have_readable_text(qapp):
    """A background with no matching foreground is how dark themes end up
    with red-on-red."""
    model = _model([_entry("e", level="Error")])
    assert model.data(model.index(0, 0),
                      Qt.ItemDataRole.ForegroundRole) is not None


# ---- filtering ----------------------------------------------------------

def test_filtering_by_level(qapp):
    model = _model([_entry("e", level="Error"), _entry("i", level="Info")])
    model.set_filter(levels={"Error"})
    assert model.rowCount() == 1
    assert model.data(model.index(0, MESSAGE)) == "e"


def test_an_empty_level_filter_shows_everything(qapp):
    model = _model([_entry("e", level="Error"), _entry("i", level="Info")])
    model.set_filter(levels=set())
    assert model.rowCount() == 2


def test_filtering_by_text_is_case_insensitive(qapp):
    model = _model([_entry("Disk On Fire"), _entry("all well")])
    model.set_filter(needle="disk")
    assert model.rowCount() == 1


def test_filtering_by_component(qapp):
    model = _model([_entry("a", source="One"), _entry("b", source="Two")])
    model.set_filter(component="Two")
    assert model.rowCount() == 1
    assert model.data(model.index(0, MESSAGE)) == "b"


def test_filters_combine(qapp):
    model = _model([_entry("boom", level="Error", source="One"),
                    _entry("boom", level="Error", source="Two"),
                    _entry("quiet", level="Error", source="One")])
    model.set_filter(levels={"Error"}, needle="boom", component="One")
    assert model.rowCount() == 1


def test_filtering_does_not_lose_the_records(qapp):
    """A filter hides rows; it must not throw entries away, or clearing it
    would come back to fewer lines than the file has."""
    model = _model([_entry("e", level="Error"), _entry("i", level="Info")])
    model.set_filter(levels={"Error"})
    model.set_filter(levels=set())
    assert model.rowCount() == 2
    assert model.total == 2


def test_components_are_offered_for_the_filter_box(qapp):
    model = _model([_entry("a", source="Beta"), _entry("b", source="Alpha"),
                    _entry("c", source="Beta")])
    assert model.components() == ["Alpha", "Beta"]


# ---- the cap ------------------------------------------------------------

def test_the_oldest_records_age_out(qapp):
    """A 300 MB log cannot all live in the model. The newest is what matters."""
    model = _model([_entry(f"line {i}") for i in range(50)], cap=10)
    assert model.total == 10
    assert model.data(model.index(9, MESSAGE)) == "line 49"


def test_what_was_dropped_is_counted_so_the_ui_can_say_so(qapp):
    """Silently showing 10 of 50 lines is the kind of quiet wrongness that
    makes someone conclude the log is fine."""
    model = _model([_entry(f"line {i}") for i in range(50)], cap=10)
    assert model.dropped == 40


def test_appending_in_batches_still_caps(qapp):
    model = LogModel(cap=5)
    for i in range(4):
        model.append([_entry(f"batch {i} line {j}") for j in range(3)])
    assert model.total == 5
    assert model.data(model.index(4, MESSAGE)) == "batch 3 line 2"


# ---- find ---------------------------------------------------------------

def test_find_returns_the_next_match(qapp):
    model = _model([_entry("alpha"), _entry("beta"), _entry("gamma")])
    assert model.find("beta", start_row=0) == 1


def test_find_wraps_around(qapp):
    """Stopping at the end makes the user scroll back to the top to carry on."""
    model = _model([_entry("alpha"), _entry("beta")])
    assert model.find("alpha", start_row=1) == 0


def test_find_goes_backwards_too(qapp):
    model = _model([_entry("alpha"), _entry("beta"), _entry("alpha")])
    assert model.find("alpha", start_row=2, forwards=False) == 0


def test_find_is_case_insensitive(qapp):
    assert _model([_entry("Alpha")]).find("alpha") == 0


def test_find_with_no_match_returns_minus_one(qapp):
    assert _model([_entry("alpha")]).find("nothing") == -1


def test_find_on_an_empty_model_is_not_an_error(qapp):
    assert LogModel().find("anything") == -1


def test_find_only_searches_what_is_visible(qapp):
    """Jumping to a row hidden by the filter would scroll to nothing."""
    model = _model([_entry("target", level="Info"),
                    _entry("other", level="Error")])
    model.set_filter(levels={"Error"})
    assert model.find("target") == -1


# ---- clearing -----------------------------------------------------------

def test_clearing_empties_everything(qapp):
    model = _model([_entry("a"), _entry("b")])
    model.clear()
    assert model.rowCount() == 0 and model.total == 0 and model.dropped == 0
