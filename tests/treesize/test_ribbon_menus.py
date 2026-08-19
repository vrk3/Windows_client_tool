"""Ribbon dropdown menus.

A dropdown arrow that opens nothing reads as broken rather than unfinished, and
a menu entry wired to nothing is worse still — it looks like it worked. These
tests pin both: every arrow has a menu, and every entry in every menu is
connected to something.
"""
import pytest
from PyQt6.QtWidgets import QToolButton

from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.formatting import Unit
from modules.treesize.ui.ribbon import MENUS, RIBBON, Ribbon
from modules.treesize.ui.shell import TreeSizeShell


def _scan():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    s.add(win, "huge.dll", size=9_000_000)
    s.add(root, "tiny.txt", size=9)
    s.build_child_lists()
    rollup(s)
    return s, root


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


# ---- License is gone ----------------------------------------------------

def test_license_is_not_in_the_ribbon(qapp):
    """This module ships inside a host app; it has no licence of its own."""
    ids = {action_id for _tab, groups in RIBBON for _c, buttons in groups
           for action_id, _l, _lg, _d in buttons}
    labels = {label.lower() for _tab, groups in RIBBON for _c, buttons in groups
              for _i, label, _lg, _d in buttons}
    captions = {caption.lower() for _tab, groups in RIBBON for caption, _b in groups}
    assert not any("license" in i for i in ids)
    assert not any("license" in l for l in labels)
    assert "license" not in captions


# ---- every arrow opens something ---------------------------------------

def test_every_dropdown_button_has_a_menu(qapp):
    ribbon = Ribbon()
    for button in ribbon.findChildren(QToolButton):
        if button.defaultAction() is None:
            continue                       # Qt's own tab-bar scroll buttons
        if button.popupMode() == QToolButton.ToolButtonPopupMode.MenuButtonPopup:
            assert button.menu() is not None, (
                f"{button.defaultAction().objectName()} shows an arrow that "
                f"opens nothing")


def test_declared_dropdowns_all_have_menu_contents(qapp):
    """Every button flagged as a dropdown in RIBBON must appear in MENUS."""
    ribbon = Ribbon()
    flagged = {action_id for _tab, groups in RIBBON for _c, buttons in groups
               for action_id, _l, _lg, dropdown in buttons if dropdown}
    missing = {i for i in flagged if i not in MENUS}
    assert missing == set(), f"dropdown declared with no menu: {sorted(missing)}"


def test_menu_actions_are_registered_like_buttons(qapp):
    ribbon = Ribbon()
    for action_id, entries in MENUS.items():
        for entry in entries:
            if entry is None:
                continue
            assert entry[0] in ribbon.actions_by_id, f"{entry[0]} not registered"


def test_a_menu_is_shared_between_the_tabs_that_use_it(qapp):
    """Refresh appears on Home and Scan; both arrows must open the same menu."""
    ribbon = Ribbon()
    # Qt puts its own buttons (tab-bar scrollers) in the tree; those have no
    # default action, so they are skipped rather than crashing the sweep.
    menus = [b.menu() for b in ribbon.findChildren(QToolButton)
             if b.defaultAction() is not None
             and b.defaultAction().objectName() == "scan.refresh"]
    assert len(menus) >= 2
    assert len(set(id(m) for m in menus)) == 1


# ---- every entry does something ----------------------------------------

#: Ribbon ids that are deliberately not implemented yet. Every one of these is
#: a real gap, not a decision — they are listed so the count is honest and so
#: adding a handler shows up as a test failure telling you to shorten the list.
#:
#: Do NOT use QAction.receivers(triggered) to detect this: QToolButton
#: .setDefaultAction() connects to triggered internally, so every action in the
#: ribbon reports a receiver whether or not anything useful happens. An earlier
#: version of this test did exactly that and could never fail.
NOT_YET_IMPLEMENTED = {
    # Comparison and snapshots: spec phase 5, needs saved scans on disk.
    "compare.path", "compare.saved", "compare.snapshot", "view.changes",
    "tools.snapshot",
    # Scheduling and the live watcher: spec phases 5 and 6.
    "scan.schedule", "scan.watch", "tools.scheduled",
    # Separate tools the module does not host.
    "tools.search", "tools.search.open", "tools.software", "tools.restore",
    # Menu parents: the button face does nothing, the arrow opens a working menu.
    "scan.select", "result.export", "scan.exclude", "view.select",
    "view.hidesmall", "unit.decimals",
}


def _connected_ids() -> set:
    """Ids the shell explicitly connects, read from its source.

    Static analysis rather than introspection, for the reason in the comment
    above: Qt's own internal connections make runtime introspection useless
    here.
    """
    import re
    from pathlib import Path
    import modules.treesize.ui.shell as shell_module
    src = Path(shell_module.__file__).read_text(encoding="utf-8")
    ids = set(re.findall(r'action\("([^"]+)"\)\.(?:triggered|toggled)', src))
    ids |= set(re.findall(r'act\("([^"]+)"\)\.(?:triggered|toggled)', src))
    ids |= {"tree.expand.%d" % d for d in (1, 2, 3)}
    ids |= {"unit.decimals.%d" % d for d in (0, 1, 2)}
    ids |= {"view.go." + s for s in ("chart", "details", "extensions",
                                     "groups", "users", "age", "top")}
    ids |= {"hidesmall." + s for s in ("off", "1mb", "10mb", "100mb")}
    ids |= set(re.findall(r'"(mode\.[a-z]+)"', src))
    ids |= set(re.findall(r'"(unit\.[a-z]+)"', src))
    ids |= set(re.findall(r'"(panel\.[a-z]+)"', src))
    return ids


def test_no_ribbon_id_is_silently_unimplemented(qapp):
    """Every id is either wired, or on the list admitting it is not.

    The point is that the gap cannot grow quietly: a new button with no
    handler fails here until someone either wires it or writes it down.
    """
    button_ids = {i for _t, groups in RIBBON for _c, buttons in groups
                  for i, _l, _lg, _d in buttons}
    menu_ids = {e[0] for entries in MENUS.values() for e in entries if e}
    unaccounted = (button_ids | menu_ids) - _connected_ids() - NOT_YET_IMPLEMENTED
    assert unaccounted == set(), (
        f"ribbon ids that do nothing and are not declared unimplemented: "
        f"{sorted(unaccounted)}")


def test_the_unimplemented_list_has_no_stale_entries(qapp):
    """Wiring something must shorten the list, or the count drifts from truth."""
    stale = NOT_YET_IMPLEMENTED & _connected_ids()
    assert stale == set(), f"listed as unimplemented but actually wired: {sorted(stale)}"


def test_scan_target_menu_lists_real_drives(shell):
    menu = shell.ribbon.menu("scan.select")
    labels = [a.text() for a in menu.actions() if a.text()]
    assert any(l.endswith(":\\") for l in labels), "no drive entries"
    assert any("folder" in l.lower() for l in labels), "no browse entry"


# ---- the wiring actually changes state ---------------------------------

def test_decimals_entry_changes_formatting(shell):
    shell.ribbon.action("unit.decimals.2").trigger()
    assert shell.ribbon.action("unit.decimals.2").isChecked()
    assert not shell.ribbon.action("unit.decimals.1").isChecked()
    shell.set_unit(Unit.KB)
    model = shell.directory_tree.tree_model
    from PyQt6.QtCore import QModelIndex, Qt
    root_index = model.index(0, 0, QModelIndex())
    text = model.data(model.index(0, 1, root_index), Qt.ItemDataRole.DisplayRole)
    assert text.count(".") == 1 and len(text.split(".")[1].split()[0]) == 2


def test_view_menu_entries_switch_tabs(shell):
    shell.ribbon.action("view.go.users").trigger()
    assert shell.views.currentWidget() is shell.users
    shell.ribbon.action("view.go.chart").trigger()
    assert shell.views.currentWidget() is shell.chart


def test_collapse_and_expand_entries_drive_the_tree(shell):
    shell.ribbon.action("tree.expand.all").trigger()
    shell.ribbon.action("tree.collapse.all").trigger()      # must not raise


def test_hide_small_sets_a_real_filter(shell):
    shell.ribbon.action("hidesmall.10mb").trigger()
    assert shell._filters.min_size == 10 << 20
    assert shell.ribbon.action("hidesmall.10mb").isChecked()
    assert not shell.ribbon.action("hidesmall.off").isChecked()


def test_clear_exclusions_resets_the_filter_set(shell):
    shell._filters.exclude_globs = ("*.tmp",)
    shell._filters.min_size = 999
    shell.ribbon.action("exclude.clear").trigger()
    assert shell._filters.exclude_globs == ()
    assert shell._filters.min_size == 0


def test_clipboard_export_produces_tab_separated_rows(shell):
    # Assert on the returned text, not on the OS clipboard: reading it back
    # is timing-dependent while widgets churn, and that flakiness says
    # nothing about whether the export is right.
    lines = shell._export_clipboard().splitlines()
    assert lines[0].startswith("Name\tSize (bytes)")
    assert any("Windows" in line for line in lines[1:])


def test_csv_export_writes_a_real_file(shell, tmp_path, monkeypatch):
    target = tmp_path / "out.csv"
    monkeypatch.setattr(
        "modules.treesize.ui.shell.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(target), "CSV (*.csv)"))
    shell.ribbon.action("export.csv").trigger()
    assert target.exists()
    body = target.read_text(encoding="utf-8-sig")
    assert "Name,Size (bytes)" in body
    assert "Windows" in body


def test_export_with_nothing_selected_does_not_write(shell, tmp_path, monkeypatch):
    shell.clear_scan()
    called = []
    monkeypatch.setattr(
        "modules.treesize.ui.shell.QMessageBox.information",
        lambda *a, **k: called.append(a))
    shell.ribbon.action("export.csv").trigger()
    assert called, "should tell the user there is nothing to export"
