"""Phase 2 shell: ribbon, panels, Details view, and the wiring between them."""
import pytest
from PyQt6.QtCore import QModelIndex, Qt

from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.formatting import Mode, Unit
from modules.treesize.ui.panels import (
    DriveList, ScanOverview, TreeSizeStatusBar, format_filetime,
)
from modules.treesize.ui.ribbon import CHECKABLE, RIBBON, Ribbon
from modules.treesize.ui.shell import TreeSizeShell
from modules.treesize.ui.theme import DARK, LIGHT, stylesheet
from modules.treesize.ui.views.details import DetailsView, SIZE_COLUMN


def _scan():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    big = s.add(root, "Windows", size=0, attrs=DIR)
    s.add(big, "huge.dll", size=9_000_000_000, alloc=9_000_000_000)
    s.add(root, "tiny.txt", size=9, alloc=4096)
    s.add(root, "gone.tmp", size=500, attrs=EXCLUDED)
    s.build_child_lists()
    rollup(s)
    return s, root


# ---- ribbon -------------------------------------------------------------

def test_ribbon_tabs_are_the_products_own(qapp):
    ribbon = Ribbon()
    tabs = [ribbon.tab_bar.tabText(i) for i in range(ribbon.tab_bar.count())]
    assert tabs == ["File", "Home", "Scan", "Tools", "View", "Details", "Help"]


def test_the_details_tab_is_contextual_and_starts_hidden(qapp):
    """A contextual tab appears with its object and disappears with it."""
    ribbon = Ribbon()
    index = tabs_index(ribbon, "Details")
    assert not ribbon.tab_bar.isTabVisible(index)
    ribbon.set_contextual_visible("Details", True)
    assert ribbon.tab_bar.isTabVisible(index)


def test_hiding_a_contextual_tab_does_not_strand_the_user_on_it(qapp):
    ribbon = Ribbon()
    index = tabs_index(ribbon, "Details")
    ribbon.set_contextual_visible("Details", True)
    ribbon.tab_bar.setCurrentIndex(index)
    ribbon.set_contextual_visible("Details", False)
    assert ribbon.tab_bar.currentIndex() != index


def tabs_index(ribbon, name):
    return next(i for i in range(ribbon.tab_bar.count())
                if ribbon.tab_bar.tabText(i) == name)


def test_the_details_tab_follows_the_active_view(shell):
    shell.views.setCurrentWidget(shell.details)
    index = tabs_index(shell.ribbon, "Details")
    assert shell.ribbon.tab_bar.isTabVisible(index)
    shell.views.setCurrentWidget(shell.chart)
    assert not shell.ribbon.tab_bar.isTabVisible(index)


def test_details_column_chooser_hides_and_shows(shell):
    from modules.treesize.ui.views.details import COLUMNS
    shell.views.setCurrentWidget(shell.details)
    assert "Path" not in shell.details.visible_columns()
    shell.details.set_visible_columns(COLUMNS)
    assert "Path" in shell.details.visible_columns()


def test_the_name_column_can_never_be_hidden(shell):
    """A table of sizes with no names is useless, and the chooser is reached
    from the header of a table you can no longer read."""
    shell.details.set_visible_columns(("Size",))
    assert "Name" in shell.details.visible_columns()


def test_an_action_shared_by_two_tabs_is_one_object(qapp):
    """Stop is on Home and Scan. Enabling it once must enable it everywhere."""
    ribbon = Ribbon()
    ribbon.set_enabled("scan.stop", False)
    assert not ribbon.action("scan.stop").isEnabled()
    ribbon.set_enabled("scan.stop", True)
    assert ribbon.action("scan.stop").isEnabled()


def test_mode_and_unit_buttons_are_checkable(qapp):
    ribbon = Ribbon()
    assert ribbon.action("mode.size").isCheckable()
    assert ribbon.action("unit.auto").isCheckable()
    assert not ribbon.action("scan.refresh").isCheckable()


def test_every_checkable_id_actually_exists(qapp):
    """CHECKABLE is written by hand; a typo there silently does nothing."""
    ribbon = Ribbon()
    assert CHECKABLE <= set(ribbon.actions_by_id)


def test_portable_installation_is_omitted_not_disabled(qapp):
    """Spec 5.2: this module has no independent installation to make portable,
    so the button is left out rather than shown greyed."""
    labels = {label for _tab, groups in RIBBON for _c, buttons in groups
              for _id, label, _l, _d in buttons}
    assert not any("portable" in label.lower() for label in labels)


def test_switching_tabs_switches_pages(qapp):
    ribbon = Ribbon()
    ribbon.tab_bar.setCurrentIndex(3)          # Tools
    assert ribbon.pages.currentIndex() == 2    # File has no page


# ---- panels -------------------------------------------------------------

def test_drive_list_renders_supplied_drives(qapp):
    drives = DriveList()
    drives.refresh([("C", 1000, 250), ("D", 2000, 1000)])
    assert drives.topLevelItemCount() == 2
    assert drives.topLevelItem(0).text(0) == "C:"
    assert drives.topLevelItem(0).text(3) == "25.0%"


def test_scan_overview_shows_selection_facts(qapp):
    store, root = _scan()
    overview = ScanOverview()
    overview.show_node(store, root)
    assert "8.4 GB" in overview._labels["Size"].text()
    assert overview._labels["Folders"].text().endswith("1")


def test_scan_overview_clears_for_an_invalid_node(qapp):
    overview = ScanOverview()
    overview.show_node(None, -1)
    assert overview._labels["Size"].text() == "Size: —"


def test_unset_filetimes_render_as_a_dash():
    assert format_filetime(0) == "—"
    assert format_filetime(-1) == "—", "a corrupt stamp must not raise"


def test_status_bar_shouts_about_an_incomplete_scan(qapp):
    class Result:
        node_count, excluded, engine = 10, 0, "walk"
        volume_info, complete = None, False
        errors, error_count = (("C:\\locked", "denied"),), 1
    bar = TreeSizeStatusBar()
    bar.show_result(Result())
    assert "INCOMPLETE" in bar._notice.text()


def test_status_bar_flags_a_degraded_walk_scan(qapp):
    class Result:
        node_count, excluded, engine = 10, 0, "walk"
        volume_info, complete = None, True
        errors, error_count = (), 0
    bar = TreeSizeStatusBar()
    bar.show_result(Result())
    assert "MFT" in bar._notice.text(), "spec 5.9: say when the fast path was unavailable"


# ---- details ------------------------------------------------------------

def test_details_sorts_on_the_number_not_the_formatted_text(qapp):
    """Text sorting puts "9 B" above "9.0 GB"; this is the bug that check
    catches."""
    store, root = _scan()
    view = DetailsView()
    view.show_children_of(store, root)
    assert view.topLevelItemCount() == 2, "excluded nodes must not appear"
    view.sortByColumn(SIZE_COLUMN, Qt.SortOrder.DescendingOrder)
    assert view.topLevelItem(0).text(0) == "Windows"
    view.sortByColumn(SIZE_COLUMN, Qt.SortOrder.AscendingOrder)
    assert view.topLevelItem(0).text(0) == "tiny.txt"


def test_details_shows_counts_only_for_folders(qapp):
    store, root = _scan()
    view = DetailsView()
    view.show_children_of(store, root)
    rows = {view.topLevelItem(i).text(0): view.topLevelItem(i)
            for i in range(view.topLevelItemCount())}
    assert rows["tiny.txt"].text(3) == ""
    assert rows["Windows"].text(3) == "1"


# ---- theme --------------------------------------------------------------

def test_both_themes_define_the_same_tokens():
    assert set(DARK) == set(LIGHT)


def test_stylesheet_renders_without_unfilled_placeholders():
    """A missing token leaves a literal "{name}" in the sheet, which Qt drops
    silently -- the rule just stops applying with no error anywhere."""
    import re
    for light in (True, False):
        leftover = re.findall(r"\{[a-z_]+\}", stylesheet(light))
        assert leftover == []


# ---- shell wiring -------------------------------------------------------

@pytest.fixture
def shell(qapp):
    widget = TreeSizeShell()
    store, root = _scan()

    class Result:
        pass
    result = Result()
    result.store, result.root = store, root
    result.node_count, result.excluded, result.engine = len(store), 0, "mft"
    result.volume_info, result.complete = None, True
    result.errors, result.error_count = (), 0
    widget.show_result(result)
    return widget


def test_showing_a_result_populates_the_tree_and_overview(shell):
    model = shell.directory_tree.tree_model
    assert model.rowCount(QModelIndex()) == 1
    assert "8.4 GB" in shell.scan_overview._labels["Size"].text()


def test_only_the_visible_view_is_populated(shell):
    """Building all six views per selection would walk the subtree six times
    for five views nobody is looking at."""
    shell.views.setCurrentWidget(shell.details)
    assert shell.details.topLevelItemCount() == 2
    assert shell.extensions.topLevelItemCount() == 0
    shell.views.setCurrentWidget(shell.extensions)
    assert shell.extensions.topLevelItemCount() > 0


def test_mode_buttons_are_mutually_exclusive(shell):
    shell.set_mode(Mode.FILES)
    assert shell.ribbon.action("mode.files").isChecked()
    assert not shell.ribbon.action("mode.size").isChecked()
    assert shell.directory_tree.tree_model.mode is Mode.FILES


def test_unit_buttons_are_mutually_exclusive(shell):
    shell.set_unit(Unit.MB)
    assert shell.ribbon.action("unit.mb").isChecked()
    assert not shell.ribbon.action("unit.auto").isChecked()


def test_panel_toggles_hide_and_show(shell):
    action = shell.ribbon.action("panel.drives")
    assert action.isChecked()
    action.setChecked(False)
    assert shell.drive_list.isHidden()
    action.setChecked(True)
    assert not shell.drive_list.isHidden()


def test_clearing_a_scan_empties_every_pane(shell):
    shell.clear_scan()
    assert shell.directory_tree.tree_model.rowCount(QModelIndex()) == 0
    assert shell.details.topLevelItemCount() == 0
    assert shell.scan_overview._labels["Size"].text() == "Size: —"


def test_the_tree_lists_the_largest_child_first(shell):
    """The defining behaviour of the tool: the answer is the first row."""
    model = shell.directory_tree.tree_model
    root_index = model.index(0, 0, QModelIndex())
    first = model.index(0, 0, root_index)
    assert model.data(first, Qt.ItemDataRole.DisplayRole) == "Windows"


def test_sort_order_survives_expanding_a_new_folder(shell):
    """Sorting only the already-materialised children means a folder expanded
    afterwards silently comes back in MFT order."""
    model = shell.directory_tree.tree_model
    root_index = model.index(0, 0, QModelIndex())
    windows = model.index(0, 0, root_index)
    assert model.rowCount(windows) == 1
    assert model.data(model.index(0, 0, windows),
                      Qt.ItemDataRole.DisplayRole) == "huge.dll"


# ---- phase 3 views ------------------------------------------------------

def test_chart_tab_is_first_because_the_chart_is_a_view_not_a_panel(shell):
    """Spec 5.1: the chart lives in the right-hand tab strip."""
    assert shell.views.tabText(0) == "Chart"
    assert [shell.views.tabText(i) for i in range(shell.views.count())] == [
        "Chart", "Details", "Extensions", "File groups", "Users",
        "Age of Files", "Top Files"]


def test_extensions_view_totals_the_subtree(shell):
    shell.views.setCurrentWidget(shell.extensions)
    rows = {shell.extensions.topLevelItem(i).text(0): shell.extensions.topLevelItem(i)
            for i in range(shell.extensions.topLevelItemCount())}
    assert "dll" in rows
    assert rows["dll"].text(1) == "1"


def test_age_view_keeps_buckets_in_chronological_order(shell):
    """Sorting an age histogram by size makes it unreadable as a distribution."""
    shell.views.setCurrentWidget(shell.ages)
    labels = [shell.ages.topLevelItem(i).text(0)
              for i in range(shell.ages.topLevelItemCount())]
    assert labels == ["Today", "This week", "This month", "Last 6 months",
                      "This year", "Older"]
    assert not shell.ages.isSortingEnabled()


def test_top_files_lists_the_largest_first(shell):
    shell.views.setCurrentWidget(shell.top_files)
    assert shell.top_files.topLevelItem(0).text(0) == "huge.dll"


def test_chart_lays_out_the_selected_subtree(shell):
    shell.views.setCurrentWidget(shell.chart)
    shell.chart.treemap.resize(400, 300)
    shell.chart.set_scan(shell._store, shell._root)
    assert len(shell.chart.treemap._rects) > 1


def test_chart_breadcrumb_tracks_drilling(shell):
    shell.views.setCurrentWidget(shell.chart)
    shell.chart.set_scan(shell._store, shell._root)
    windows = next(i for i in range(len(shell._store))
                   if shell._store.name(i) == "Windows")
    shell.chart.drill_to(windows)
    assert shell.chart._trail[-1] == windows
    shell.chart.drill_to(shell._root)
    assert shell.chart._trail == [shell._root], "clicking back up truncates the trail"


def test_clearing_empties_the_aggregate_views(shell):
    shell.views.setCurrentWidget(shell.extensions)
    assert shell.extensions.topLevelItemCount() > 0
    shell.clear_scan()
    assert shell.extensions.topLevelItemCount() == 0


# ---- title row, find box, backstage -------------------------------------

def test_quick_access_buttons_show_glyphs_not_labels(shell):
    """setDefaultAction would bind the button text to the action label and the
    QAT would read 'Refresh scan / Stop / Export', swamping the row."""
    from PyQt6.QtWidgets import QToolButton
    glyphs = [b.text() for b in shell.title_row.findChildren(QToolButton)]
    assert glyphs == ["⟳", "■", "⇪"]
    tips = [b.toolTip() for b in shell.title_row.findChildren(QToolButton)]
    assert tips == ["Refresh scan", "Stop", "Export"]


def test_quick_access_buttons_follow_action_enablement(shell):
    from PyQt6.QtWidgets import QToolButton
    stop_button = shell.title_row.findChildren(QToolButton)[1]
    shell.ribbon.action("scan.stop").setEnabled(False)
    assert not stop_button.isEnabled()
    shell.ribbon.action("scan.stop").setEnabled(True)
    assert stop_button.isEnabled()


def test_find_box_searches_ribbon_commands(shell):
    """Pro's Find option finds COMMANDS, not files."""
    shell.title_row.find_box.setText("expand")
    assert shell.find_results.count() > 0
    labels = [shell.find_results.item(i).text()
              for i in range(shell.find_results.count())]
    assert any("Expand" in l for l in labels)


def test_find_box_stays_quiet_for_one_character(shell):
    shell.title_row.find_box.setText("e")
    assert shell.find_results.isHidden()


def test_choosing_a_find_result_runs_the_command(shell):
    shell.views.setCurrentWidget(shell.details)
    shell.title_row.find_box.setText("Users")
    item = next(shell.find_results.item(i)
                for i in range(shell.find_results.count())
                if "view.go.users" in shell.find_results.item(i).text())
    shell.find_results._chosen(item)
    assert shell.views.currentWidget() is shell.users


def test_the_file_tab_opens_the_backstage_and_hides_the_body(shell):
    # isHidden(), not isVisible(): the fixture never calls show(), so nothing
    # is "visible" and isVisible() would be False for every widget either way.
    # isHidden() reports the explicit hide state, which is what is under test.
    shell.ribbon.tab_bar.setCurrentIndex(0)          # File
    assert not shell.backstage.isHidden()
    assert shell.nav_bar.isHidden(), "the nav bar must not show through"
    assert shell.splitter.isHidden()
    assert shell.ribbon.pages.isHidden()


def test_leaving_the_file_tab_restores_the_body(shell):
    shell.ribbon.tab_bar.setCurrentIndex(0)
    shell.ribbon.tab_bar.setCurrentIndex(1)
    assert shell.backstage.isHidden()
    assert not shell.nav_bar.isHidden()
    assert not shell.splitter.isHidden()
    assert not shell.ribbon.pages.isHidden()


def test_closing_the_backstage_honours_panel_toggles(shell):
    """Restoring the body must not force back a panel the user switched off."""
    shell.ribbon.action("panel.status").setChecked(False)
    shell.ribbon.tab_bar.setCurrentIndex(0)
    shell.ribbon.tab_bar.setCurrentIndex(1)
    assert shell.status_bar.isHidden()


def test_backstage_lists_recent_targets(shell, tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x")
    shell.start_scan(str(tmp_path))
    assert shell.wait_for_scan(60_000)
    shell.ribbon.tab_bar.setCurrentIndex(0)
    entries = [shell.backstage.recent.item(i).text()
               for i in range(shell.backstage.recent.count())]
    assert str(tmp_path) in entries


def test_backstage_shows_a_hint_when_there_are_no_scans(qapp):
    from modules.treesize.ui.backstage import Backstage
    page = Backstage()
    page.set_recent([])
    assert page.recent.count() == 1
    assert not (page.recent.item(0).flags() & Qt.ItemFlag.ItemIsEnabled)


# ---- find, hide empty, chart modes --------------------------------------

def test_find_selects_the_largest_match(shell):
    """A name fragment matches hundreds of nodes on a real scan; the one worth
    jumping to is almost always the big one."""
    shell.find_in_tree("dll")
    assert shell._store.name(shell._selected) == "huge.dll"


def test_find_reports_when_nothing_matches(shell):
    shell.find_in_tree("zzzz-no-such-thing")
    assert "No match" in shell.scan_state.text()


def test_find_ignores_an_empty_query(shell):
    before = shell.scan_state.text()
    shell.find_in_tree("   ")
    assert shell.scan_state.text() == before


def test_reveal_expands_the_tree_to_the_node(shell):
    from PyQt6.QtCore import QModelIndex
    target = next(i for i in range(len(shell._store))
                  if shell._store.name(i) == "huge.dll")
    shell.reveal_node(target)
    assert shell._selected == target
    root_index = shell.directory_tree.tree_model.index(0, 0, QModelIndex())
    assert shell.directory_tree.isExpanded(root_index)


def test_hide_empty_folders_removes_zero_sized_ones(qapp):
    from modules.treesize.store.node_store import NodeStore, DIR
    from modules.treesize.store.rollup import rollup
    from modules.treesize.ui.tree_model import DirectoryTreeModel
    from PyQt6.QtCore import QModelIndex

    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    store.add(root, "full", size=0, attrs=DIR)
    store.add(store.add(root, "empty", size=0, attrs=DIR), "x", size=0)
    store.add(root, "data.bin", size=500)
    store.build_child_lists()
    rollup(store)

    model = DirectoryTreeModel()
    model.set_scan(store, root)
    root_index = model.index(0, 0, QModelIndex())
    before = model.rowCount(root_index)
    model.set_hide_empty(True)
    root_index = model.index(0, 0, QModelIndex())
    assert model.rowCount(root_index) < before


def test_hide_empty_keeps_zero_byte_files(qapp):
    """'Empty' means a folder that frees nothing, not every zero-byte entry."""
    from modules.treesize.store.node_store import NodeStore, DIR
    from modules.treesize.store.rollup import rollup
    from modules.treesize.ui.tree_model import DirectoryTreeModel
    from PyQt6.QtCore import QModelIndex, Qt

    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    store.add(root, "marker.txt", size=0)
    store.build_child_lists()
    rollup(store)
    model = DirectoryTreeModel()
    model.set_scan(store, root)
    model.set_hide_empty(True)
    root_index = model.index(0, 0, QModelIndex())
    assert model.rowCount(root_index) == 1


def test_chart_offers_treemap_pie_and_bar(shell):
    labels = [b.text() for b in shell.chart._mode_buttons.buttons()]
    assert labels == ["Treemap", "Pie", "Bar"]


def test_switching_chart_mode_swaps_the_widget(shell):
    shell.chart.set_chart_mode(1)
    assert shell.chart.pie.isHidden() is False
    assert shell.chart.treemap.isHidden() is True
    shell.chart.set_chart_mode(2)
    assert shell.chart.bars.isHidden() is False
    assert shell.chart.pie.isHidden() is True


def test_pie_folds_the_tail_into_one_other_slice(qapp):
    """Cycling the palette would reuse a hue for an unrelated folder, and
    dropping the tail would stop the percentages adding to 100."""
    from modules.treesize.store.node_store import NodeStore, DIR
    from modules.treesize.store.rollup import rollup
    from modules.treesize.ui.views.chart import SliceChart

    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    for i in range(30):
        store.add(root, f"f{i}.bin", size=100 * (30 - i))
    store.build_child_lists()
    rollup(store)

    chart = SliceChart()
    chart.set_scan(store, root)
    assert len(chart._rows) == SliceChart.MAX_SLICES + 1
    assert chart._rows[-1][1].startswith("Other (")
    assert sum(row[3] for row in chart._rows) == pytest.approx(1.0)


def test_settings_import_ignores_unknown_keys(shell, tmp_path):
    import json
    from modules.treesize.ui.options_dialog import DEFAULTS
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"decimals": 2, "evil": "payload"}))
    from PyQt6.QtWidgets import QFileDialog
    original = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(path), ""))
    try:
        shell.import_settings()
    finally:
        QFileDialog.getOpenFileName = original
    assert shell._settings["decimals"] == 2
    assert "evil" not in shell._settings
    assert set(shell._settings) == set(DEFAULTS)
