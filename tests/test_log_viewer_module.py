"""The log viewer module: opening, following, filtering and find, end to end
against real files on disk."""
import os

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


def test_show_only_matches_filters_by_the_find_text(viewer):
    viewer.find_box.setText("broke")
    viewer.only_matching.setChecked(True)
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
