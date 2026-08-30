"""The log viewer module: opening, following, filtering and find, end to end
against real files on disk."""
import os
from datetime import datetime

import pytest

from core.search_provider import SearchQuery
from modules.log_viewer.log_viewer_module import LogViewerModule, LogViewerWidget

CMTRACE = (
    '<![LOG[Starting up]LOG]!><time="13:45:12.345+000" date="08-20-2026" '
    'component="Alpha" context="" type="1" thread="1" file="a.cpp:1">\n'
    '<![LOG[Careful]LOG]!><time="13:45:13.000+000" date="08-20-2026" '
    'component="Beta" context="" type="2" thread="2" file="b.cpp:2">\n'
    '<![LOG[It broke]LOG]!><time="13:45:14.000+000" date="08-20-2026" '
    'component="Beta" context="" type="3" thread="2" file="b.cpp:3">\n'
)


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "ccmexec.log"
    path.write_text(CMTRACE, encoding="utf-8")
    return path


@pytest.fixture
def viewer(qapp, log):
    widget = LogViewerWidget()
    widget.open(str(log))
    yield widget
    widget.stop()


# ---- opening ------------------------------------------------------------

def test_opening_a_log_shows_its_records(viewer):
    assert viewer.model.rowCount() == 3


def test_the_status_line_names_the_file_and_the_counts(viewer):
    text = viewer.status.text()
    assert "ccmexec.log" in text and "3" in text


def test_components_populate_the_filter_box(viewer):
    items = [viewer.component.itemText(i)
             for i in range(viewer.component.count())]
    assert items == ["All", "Alpha", "Beta"]


def test_opening_a_second_log_replaces_the_first(viewer, tmp_path):
    """Appending instead would splice two machines' logs into one timeline."""
    other = tmp_path / "other.log"
    other.write_text("just one line\n", encoding="utf-8")
    viewer.open(str(other))
    assert viewer.model.total == 1


def test_a_plain_text_log_still_opens(qapp, tmp_path):
    path = tmp_path / "plain.log"
    path.write_text("2026-08-20 10:00:00 ERROR disk on fire\nordinary line\n",
                    encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    try:
        assert widget.model.total == 2
    finally:
        widget.stop()


def test_a_missing_file_does_not_raise(qapp, tmp_path):
    widget = LogViewerWidget()
    try:
        widget.open(str(tmp_path / "nope.log"))
        assert widget.model.total == 0
    finally:
        widget.stop()


# ---- following ----------------------------------------------------------

def test_following_picks_up_appended_lines(viewer, log):
    viewer.follow.setChecked(True)
    with open(log, "a", encoding="utf-8") as handle:
        handle.write('<![LOG[later]LOG]!><time="13:45:15.000+000" '
                     'date="08-20-2026" component="Alpha" context="" '
                     'type="1" thread="1" file="a.cpp:9">\n')
    viewer._poll()
    assert viewer.model.total == 4


def test_following_does_not_re_add_what_is_already_shown(viewer):
    """Re-reading the file each tick would double every line."""
    viewer.follow.setChecked(True)
    viewer._poll()
    viewer._poll()
    assert viewer.model.total == 3


def test_the_timer_only_runs_while_following(viewer):
    assert not viewer._timer.isActive()
    viewer.follow.setChecked(True)
    assert viewer._timer.isActive()
    viewer.follow.setChecked(False)
    assert not viewer._timer.isActive()


def test_stopping_the_widget_stops_the_timer(viewer):
    viewer.follow.setChecked(True)
    viewer.stop()
    assert not viewer._timer.isActive()


def test_a_rolled_sibling_is_included_on_request(qapp, tmp_path):
    (tmp_path / "ccm.lo_").write_text("older line\n", encoding="utf-8")
    (tmp_path / "ccm.log").write_text("newer line\n", encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(tmp_path / "ccm.log"))
        assert widget.model.total == 1
        widget.rolled.setChecked(True)          # triggers a reload
        assert widget.model.total == 2
    finally:
        widget.stop()


# ---- filtering ----------------------------------------------------------

def test_unticking_a_severity_hides_it(viewer):
    viewer._level_boxes["Info"].setChecked(False)
    assert viewer.model.rowCount() == 2


def test_all_severities_ticked_filters_nothing(viewer):
    """All boxes on must mean "no filter", not "a set listing every level" --
    a Debug record would vanish under the latter."""
    for box in viewer._level_boxes.values():
        box.setChecked(True)
    assert viewer.model.rowCount() == 3


def test_filtering_by_component(viewer):
    viewer.component.setCurrentText("Beta")
    assert viewer.model.rowCount() == 2


def test_the_filter_box_hides_non_matching_rows(viewer):
    """Replaces the old "Show only matches" checkbox, which shared Find's
    text and only re-applied when toggled."""
    viewer.filter_box.setText("broke")
    assert viewer.model.rowCount() == 1


# ---- find ---------------------------------------------------------------

def test_find_selects_the_matching_row(viewer):
    viewer.find_box.setText("Careful")
    viewer.find_next()
    assert viewer.table.currentIndex().row() == 1


def test_find_with_no_match_says_so_instead_of_moving(viewer):
    viewer.find_box.setText("not in the file")
    viewer.find_next()
    assert "No match" in viewer.status.text()


def test_find_backwards_works(viewer):
    viewer.find_box.setText("Starting")
    viewer.find_previous()
    assert viewer.table.currentIndex().row() == 0


def test_an_empty_find_does_nothing(viewer):
    viewer.find_box.setText("")
    viewer.find_next()          # must not raise


# ---- the module shell ---------------------------------------------------

def test_the_module_declares_itself(qapp):
    module = LogViewerModule()
    assert module.name == "Log Viewer"
    assert module.requires_admin is False


def test_the_module_offers_a_search_provider(qapp, log):
    module = LogViewerModule()
    widget = module.create_widget()
    try:
        widget.open(str(log))
        provider = module.get_search_provider()
        assert provider is not None
        hits = provider.search(SearchQuery(text="broke"))
        assert len(hits) == 1 and hits[0].type == "Error"
    finally:
        widget.stop()


def test_an_empty_query_returns_nothing(qapp, log):
    module = LogViewerModule()
    widget = module.create_widget()
    try:
        widget.open(str(log))
        assert module.get_search_provider().search(SearchQuery(text="")) == []
    finally:
        widget.stop()


def test_deactivating_stops_following(qapp, log):
    module = LogViewerModule()
    widget = module.create_widget()
    try:
        widget.open(str(log))
        widget.follow.setChecked(True)
        module.on_deactivate()
        assert not widget._timer.isActive()
    finally:
        widget.stop()


def test_status_info_before_anything_is_open(qapp):
    module = LogViewerModule()
    module.create_widget()
    assert "No log" in module.get_status_info()


# ---- the follow path must stay cheap and non-destructive ---------------

def test_a_follow_tick_keeps_the_users_selection(viewer, log):
    """A model reset clears it. While following that is every second: click a
    row to read it and it deselects under you."""
    viewer.table.setCurrentIndex(viewer.model.index(1, 4))
    assert viewer.table.currentIndex().row() == 1
    with open(log, "a", encoding="utf-8") as handle:
        handle.write('<![LOG[later]LOG]!><time="13:45:20.000+000" '
                     'date="08-20-2026" component="Alpha" context="" '
                     'type="1" thread="1" file="a.cpp:9">\n')
    viewer._poll()
    assert viewer.table.currentIndex().row() == 1


def test_the_search_provider_is_not_handed_a_fresh_copy_each_tick(viewer, log):
    """Copying the whole deque once a second, to answer a search nobody has
    typed, is work for nothing."""
    first = viewer.provider._entries
    with open(log, "a", encoding="utf-8") as handle:
        handle.write("another line\n")
    viewer._poll()
    assert viewer.provider._entries is first


def test_the_provider_still_sees_records_added_after_it_was_set(viewer, log):
    """The flip side of not copying: it must observe later appends."""
    before = len(viewer.provider.search(SearchQuery(text="broke")))
    with open(log, "a", encoding="utf-8") as handle:
        handle.write('<![LOG[it broke again]LOG]!><time="13:45:21.000+000" '
                     'date="08-20-2026" component="Beta" context="" '
                     'type="3" thread="2" file="b.cpp:9">\n')
    viewer._poll()
    assert len(viewer.provider.search(SearchQuery(text="broke"))) == before + 1


def test_searching_survives_the_log_growing_underneath_it(viewer, log):
    """The provider holds the model's live deque. A search must not blow up
    if that deque is appended to -- it snapshots before iterating."""
    entries = viewer.provider._entries
    results = []

    class _Growing:
        def __iter__(self):
            entries.append(entries[0])      # mutate mid-iteration
            return iter(list(entries))

        def __len__(self):
            return len(entries)

    viewer.provider.set_entries(_Growing())
    results = viewer.provider.search(SearchQuery(text="broke"))
    assert results is not None


# ---- the live filter box ------------------------------------------------
#
# Distinct from Find, which JUMPS to the next match and leaves everything on
# screen. This hides everything that does not match, and does it as you type.

def test_typing_in_the_filter_hides_everything_else(viewer):
    viewer.filter_box.setText("broke")
    assert viewer.model.rowCount() == 1
    assert viewer.model.data(viewer.model.index(0, 4)) == "It broke"


def test_the_filter_is_case_insensitive(viewer):
    """Typing WARNING must find "Warning". Nobody matches case by hand."""
    viewer.filter_box.setText("BROKE")
    assert viewer.model.rowCount() == 1


def test_the_filter_applies_as_you_type_without_pressing_anything(viewer):
    """The old "Show only matches" checkbox needed re-ticking after every
    edit, which is why it was the wrong shape for this."""
    viewer.filter_box.setText("Care")
    assert viewer.model.rowCount() == 1
    viewer.filter_box.setText("Car")
    assert viewer.model.rowCount() == 1
    viewer.filter_box.setText("")
    assert viewer.model.rowCount() == 3


def test_the_filter_matches_the_severity_column_too(viewer):
    """Typing "warning" should find the warning row of a CMTrace log even
    though the word appears in the type attribute, not the message."""
    viewer.filter_box.setText("warning")
    assert viewer.model.rowCount() == 1
    assert viewer.model.data(viewer.model.index(0, 1)) == "Warning"


def test_the_filter_matches_the_component_too(viewer):
    viewer.filter_box.setText("Alpha")
    assert viewer.model.rowCount() == 1


def test_the_filter_combines_with_the_severity_boxes(viewer):
    viewer.filter_box.setText("e")               # matches all three messages
    viewer._level_boxes["Info"].setChecked(False)
    assert viewer.model.rowCount() == 2


def test_a_filter_matching_nothing_shows_nothing_rather_than_everything(viewer):
    viewer.filter_box.setText("no such text anywhere")
    assert viewer.model.rowCount() == 0
    assert viewer.model.total == 3


def test_the_filter_survives_new_lines_arriving(viewer, log):
    """A line appended while a filter is on must be filtered too, not
    smuggled in because the append path skips the predicate."""
    viewer.filter_box.setText("broke")
    with open(log, "a", encoding="utf-8") as handle:
        handle.write('<![LOG[nothing to see]LOG]!><time="13:45:19.000+000" '
                     'date="08-20-2026" component="Alpha" context="" '
                     'type="1" thread="1" file="a.cpp:9">\n')
    viewer._poll()
    assert viewer.model.rowCount() == 1
    assert viewer.model.total == 4


def test_find_still_searches_the_whole_log_not_just_the_filtered_rows(viewer):
    """Find and Filter are different tools; leaving the filter empty must not
    silently narrow what Find can reach."""
    viewer.filter_box.setText("")
    viewer.find_box.setText("Careful")
    viewer.find_next()
    assert viewer.table.currentIndex().row() == 1


# ---- error-code lookup (CMTrace's Error Lookup) -------------------------

def test_the_tooltip_explains_an_error_code(qapp, tmp_path):
    """A line says 0x80070005; the reader needs "access denied"."""
    from PyQt6.QtCore import Qt

    path = tmp_path / "codes.log"
    path.write_text('<![LOG[Install failed (0x80070005)]LOG]!>'
                    '<time="10:00:00.000+000" date="08-20-2026" '
                    'component="C" context="" type="3" thread="1" '
                    'file="f.cpp:1">\n', encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        tip = widget.model.data(widget.model.index(0, 4),
                                Qt.ItemDataRole.ToolTipRole)
        assert "0x80070005" in tip
        assert "denied" in tip.lower()
    finally:
        widget.stop()


def test_selecting_a_row_spells_the_code_out_in_the_detail_pane(qapp, tmp_path):
    """The explanation used to overwrite the status line, which is where the
    file name and the record counts live."""
    path = tmp_path / "codes.log"
    path.write_text('<![LOG[No DP found (0x87D00231)]LOG]!>'
                    '<time="10:00:00.000+000" date="08-20-2026" '
                    'component="C" context="" type="3" thread="1" '
                    'file="f.cpp:1">\n', encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.table.setCurrentIndex(widget.model.index(0, 4))
        detail = widget.detail.toPlainText()
        assert "0x87D00231" in detail
        assert "distribution point" in detail.lower()
        assert "codes.log" in widget.status.text()
    finally:
        widget.stop()


def test_selecting_a_row_leaves_the_status_line_alone(viewer):
    """The counts must not be replaced by whatever row was clicked last."""
    viewer.table.setCurrentIndex(viewer.model.index(0, 4))
    assert "ccmexec.log" in viewer.status.text()
    assert "3" in viewer.status.text()


# ---- the detail pane (defect 5: clipped messages were unreachable) -------

#: Measured on this machine: on `CbsPersist_20260827190818.log`, 3,998 of
#: 4,000 sampled rows are elided, and Message is a Stretch section so the
#: horizontal scroll bar's range is 0..0. The tooltip was the only way to
#: read a line, and CMTrace itself uses a detail pane.
LONG = "Install failed: " + "C:\\Windows\\WinSxS\\amd64_a_very_long_path " * 40


@pytest.fixture
def long_log(tmp_path):
    path = tmp_path / "long.log"
    path.write_text(
        f'<![LOG[{LONG}]LOG]!><time="10:00:00.000+000" date="08-20-2026" '
        'component="Setup" context="" type="3" thread="4242" '
        'file="f.cpp:1">\n', encoding="utf-8")
    return path


def test_the_detail_pane_shows_the_whole_message(qapp, long_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(long_log))
        widget.table.setCurrentIndex(widget.model.index(0, 4))
        assert widget.detail.toPlainText().count("a_very_long_path") == 40
    finally:
        widget.stop()


def test_the_detail_pane_names_the_fields_of_the_record(qapp, long_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(long_log))
        widget.table.setCurrentIndex(widget.model.index(0, 4))
        detail = widget.detail.toPlainText()
        assert "Setup" in detail and "4242" in detail and "Error" in detail
    finally:
        widget.stop()


def test_the_detail_pane_is_visible_by_default(viewer):
    assert viewer.splitter.sizes()[1] > 0


def test_a_detail_pane_dragged_shut_stays_shut(viewer):
    """No setting for it: the splitter position IS the setting."""
    viewer.splitter.setSizes([100, 0])
    viewer.table.setCurrentIndex(viewer.model.index(0, 4))
    viewer.table.setCurrentIndex(viewer.model.index(1, 4))
    assert viewer.splitter.sizes()[1] == 0


def test_opening_another_log_empties_the_detail_pane(viewer, tmp_path):
    viewer.table.setCurrentIndex(viewer.model.index(0, 4))
    assert viewer.detail.toPlainText()
    other = tmp_path / "other.log"
    other.write_text("plain line\n", encoding="utf-8")
    viewer.open(str(other))
    assert viewer.detail.toPlainText() == ""


# ---- the Open dropdown --------------------------------------------------

def test_the_open_button_lists_the_logs_this_machine_has(qapp):
    from modules.log_viewer.known_logs import known_logs

    widget = LogViewerWidget()
    try:
        labels = [a.text() for a in widget.open_menu.actions()
                  if not a.isSeparator()]
        for log in known_logs():
            assert log.label in labels
        assert "Browse…" in labels
    finally:
        widget.stop()


def test_choosing_a_known_log_opens_it(qapp, monkeypatch):
    from modules.log_viewer.known_logs import known_logs

    available = known_logs()
    if not available:
        pytest.skip("no known logs on this machine")

    widget = LogViewerWidget()
    try:
        opened = []
        monkeypatch.setattr(widget, "open", lambda p: opened.append(p))
        widget._build_open_menu()          # rebuild against the patched open
        wanted = available[0]
        for action in widget.open_menu.actions():
            if action.text() == wanted.label:
                action.trigger()
        assert opened == [wanted.path]
    finally:
        widget.stop()


def test_the_menu_is_rebuilt_rather_than_cached(qapp):
    """A ConfigMgr client can appear, and CBS rolls into new archives,
    between one opening of the menu and the next."""
    widget = LogViewerWidget()
    try:
        before = len(widget.open_menu.actions())
        widget._build_open_menu()
        assert len(widget.open_menu.actions()) == before
    finally:
        widget.stop()


# ---- the filter row -----------------------------------------------------

@pytest.fixture
def threaded_log(tmp_path):
    path = tmp_path / "dism.log"
    path.write_text(
        "2026-08-24 21:45:46, Info                  DISM   API: PID=1 "
        "TID=29016 first\n"
        "2026-08-24 21:45:47, Info                  DISM   API: PID=1 "
        "TID=29016 second\n"
        "2026-08-24 22:00:00, Info                  DISM   API: PID=1 "
        "TID=777 third\n", encoding="utf-8")
    return path


def test_the_thread_box_lists_threads_by_how_common_they_are(qapp,
                                                             threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        entries = [widget.thread.itemText(i)
                   for i in range(widget.thread.count())]
        assert entries[0] == "All"
        assert entries[1].startswith("29016")
        assert "(2)" in entries[1]
    finally:
        widget.stop()


def test_choosing_a_thread_filters_the_table(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.thread.setCurrentIndex(widget.thread.findText("777  (1)"))
        assert widget.model.rowCount() == 1
    finally:
        widget.stop()


def test_the_range_boxes_open_on_the_whole_log(qapp, threaded_log):
    """Not on the year 1752, which is what an unset QDateTimeEdit shows."""
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        assert widget.time_from.dateTime().toPyDateTime() == \
            datetime(2026, 8, 24, 21, 45, 46)
        assert widget.time_to.dateTime().toPyDateTime() == \
            datetime(2026, 8, 24, 22, 0, 0)
    finally:
        widget.stop()


def test_narrowing_the_range_filters_the_table(qapp, threaded_log):
    from PyQt6.QtCore import QDateTime

    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.time_to.setDateTime(
            QDateTime(datetime(2026, 8, 24, 21, 46, 0)))
        assert widget.model.rowCount() == 2
    finally:
        widget.stop()


def test_clearing_the_range_brings_every_row_back(qapp, threaded_log):
    from PyQt6.QtCore import QDateTime

    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.time_to.setDateTime(
            QDateTime(datetime(2026, 8, 24, 21, 46, 0)))
        widget.clear_range_button.click()
        assert widget.model.rowCount() == 3
    finally:
        widget.stop()


def test_the_regex_box_switches_the_filter_to_a_pattern(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.regex_box.setChecked(True)
        widget.filter_box.setText(r"TID=29\d+")
        assert widget.model.rowCount() == 2
    finally:
        widget.stop()


def test_a_backwards_range_says_so_rather_than_emptying_the_table(qapp,
                                                                  threaded_log):
    """An empty table reads as "no such records", which is a lie about the
    log rather than a complaint about the range."""
    from PyQt6.QtCore import QDateTime

    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.time_from.setDateTime(
            QDateTime(datetime(2026, 8, 24, 23, 0, 0)))
        assert "range" in widget.status.text().lower()
        assert widget.model.rowCount() == 3, "nothing was filtered away"
    finally:
        widget.stop()


def test_an_invalid_pattern_says_so_instead_of_raising(qapp, threaded_log):
    widget = LogViewerWidget()
    try:
        widget.open(str(threaded_log))
        widget.regex_box.setChecked(True)
        widget.filter_box.setText("[unclosed")
        assert "pattern" in widget.status.text().lower()
    finally:
        widget.stop()
