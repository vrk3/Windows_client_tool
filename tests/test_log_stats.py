"""What is going wrong most often.

Turns "something is wrong" into "this is wrong four thousand times". Counts
records, not rows: folding is a reading convenience and must not change an
answer about what the log contains.

Qt-free, like the reader and the merge engine it sits beside.
"""
from datetime import datetime

import pytest

from core.types import LogEntry
from modules.log_viewer.log_stats import (
    top_codes, top_components, top_messages,
)


def _entry(message, source="CBS", level="Info", continuation=False):
    raw = {"thread": "1"}
    if continuation:
        raw["continuation"] = "1"
    return LogEntry(timestamp=datetime(2026, 8, 27, 10, 0, 0),
                    source=source, level=level, message=message, raw=raw)


# ---- codes --------------------------------------------------------------

def test_failing_codes_are_counted_most_frequent_first():
    entries = [_entry("failed [HRESULT = 0x800f0805]"),
               _entry("failed [HRESULT = 0x800f0805]"),
               _entry("failed [HRESULT = 0x80073701]")]
    assert top_codes(entries) == [(0x800f0805, 2), (0x80073701, 1)]


def test_success_codes_are_not_counted():
    """97% of the coded lines in a real CBS.log carry nothing but
    0x00000000. Counting those would bury the nine failures that matter."""
    entries = [_entry("done [HRESULT = 0x00000000]")] * 5 + [
        _entry("failed [HRESULT = 0x800f0805]")]
    assert top_codes(entries) == [(0x800f0805, 1)]


def test_a_code_appearing_twice_on_one_line_counts_once_for_that_line():
    """A row is one occurrence of a problem, however many times the line
    happens to repeat the number."""
    entries = [_entry("0x800f0805 and again 0x800f0805")]
    assert top_codes(entries) == [(0x800f0805, 1)]


def test_ties_are_broken_by_the_code_so_the_order_is_stable():
    """Equal counts sort by the code itself, ascending. Not cosmetic: without
    a tie-break two codes swap places between refreshes, and a panel that
    reorders under the cursor while you read it is worse than an arbitrary
    one."""
    entries = [_entry("[0x800f0805]"), _entry("[0x80073701]")]
    assert top_codes(entries) == [(0x80073701, 1), (0x800f0805, 1)]


def test_only_the_top_n_are_returned():
    entries = [_entry(f"[0x800f080{n}]") for n in range(1, 6)]
    assert len(top_codes(entries, 3)) == 3


def test_a_log_with_no_codes_yields_an_empty_list():
    assert top_codes([_entry("nothing interesting")]) == []


def test_no_entries_at_all_is_not_an_error():
    assert top_codes([]) == []
    assert top_components([]) == []
    assert top_messages([]) == []


# ---- components ---------------------------------------------------------

def test_components_are_counted():
    entries = [_entry("a", source="CBS"), _entry("b", source="CBS"),
               _entry("c", source="CSI")]
    assert top_components(entries) == [("CBS", 2), ("CSI", 1)]


def test_records_with_no_component_are_not_counted_as_a_blank_one():
    entries = [_entry("a", source="CBS"), _entry("b", source="")]
    assert top_components(entries) == [("CBS", 1)]


def test_counting_ignores_whether_a_row_is_folded():
    """Folding hides continuations for reading. A count of what the log
    CONTAINS must not change because of it."""
    entries = [_entry("parent", source="CSI"),
               _entry("  continued", source="CSI", continuation=True)]
    assert top_components(entries) == [("CSI", 2)]


# ---- messages -----------------------------------------------------------

def test_messages_are_counted_verbatim_by_default():
    entries = [_entry("same line"), _entry("same line"), _entry("other")]
    assert top_messages(entries) == [("same line", 2), ("other", 1)]


def test_a_key_function_lets_near_identical_lines_be_grouped():
    """Real CBS lines differ by GUID and version, so a verbatim count is
    almost all ones. The normaliser that fixes that is its own task; this
    is the seam it plugs into."""
    entries = [_entry("Package_A installed"), _entry("Package_B installed")]

    counted = top_messages(entries, key=lambda text: text.split(" ", 1)[1])

    assert counted == [("installed", 2)]


def test_an_empty_message_is_not_counted():
    assert top_messages([_entry(""), _entry("real")]) == [("real", 1)]


# ---- the panel ----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[failed [HRESULT = 0x800f0805]]LOG]!><time="13:45:12.000+000" '
    'date="08-20-2026" component="CBS" context="" type="3" thread="1" '
    'file="a.cpp:1">\n'
    '<![LOG[failed again [HRESULT = 0x800f0805]]LOG]!>'
    '<time="13:45:13.000+000" date="08-20-2026" component="CBS" context="" '
    'type="3" thread="1" file="a.cpp:2">\n'
    '<![LOG[all fine]LOG]!><time="13:45:14.000+000" date="08-20-2026" '
    'component="CSI" context="" type="1" thread="1" file="a.cpp:3">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _rows(listing):
    return [listing.item(row).text() for row in range(listing.count())]


def test_the_summary_is_hidden_until_asked_for(viewer):
    assert not viewer.summary_panel.isVisible()


def test_showing_the_summary_fills_it(viewer):
    viewer.summary_button.setChecked(True)
    assert any("0x800f0805" in text for text in _rows(viewer.summary_codes))
    assert any("CBS" in text for text in _rows(viewer.summary_components))


def test_the_summary_counts_what_the_filter_left(viewer):
    """It answers "what is in what I am looking at", so it has to move with
    the filter rather than describe the whole file forever."""
    viewer.summary_button.setChecked(True)
    viewer.filter_box.setText("all fine")
    viewer._refresh_summary()

    assert _rows(viewer.summary_codes) == []
    assert any("CSI" in text for text in _rows(viewer.summary_components))


def test_refreshing_is_debounced_rather_than_run_per_keystroke(viewer):
    """top_codes costs 297 ms over the real archive's 138,683 records.
    Running that on every character typed would make the Filter box
    unusable on exactly the logs the panel is for."""
    viewer.summary_button.setChecked(True)

    viewer.filter_box.setText("f")

    assert viewer._summary_timer.isActive(), "no debounce; it ran inline"
    assert viewer._summary_timer.isSingleShot()


def test_nothing_is_computed_while_the_panel_is_hidden(viewer):
    """A panel nobody is looking at must not cost 297 ms a keystroke."""
    assert not viewer.summary_button.isChecked()
    viewer.filter_box.setText("f")
    assert not viewer._summary_timer.isActive()


def test_clicking_a_component_filters_by_it(viewer):
    viewer.summary_button.setChecked(True)
    row = next(index for index in range(viewer.summary_components.count())
               if "CSI" in viewer.summary_components.item(index).text())

    viewer.summary_components.itemClicked.emit(
        viewer.summary_components.item(row))

    assert viewer.selected_components() == {"CSI"}


def test_clicking_a_code_filters_by_it(viewer):
    viewer.summary_button.setChecked(True)

    viewer.summary_codes.itemClicked.emit(viewer.summary_codes.item(0))

    assert viewer.filter_box.text() == "0x800f0805"
    assert viewer.model.rowCount() == 2


def test_hiding_the_panel_again_leaves_the_filters_alone(viewer):
    viewer.summary_button.setChecked(True)
    viewer.summary_button.setChecked(False)
    assert viewer.model.rowCount() == 3
