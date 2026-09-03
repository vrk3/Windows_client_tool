"""Right-click menu: the same actions in every pane, and nothing destructive
that has not been through the guardrails first."""
import os

import pytest
from PyQt6.QtWidgets import QMessageBox

from modules.treesize.ui.shell import TreeSizeShell


@pytest.fixture
def shell(qapp, tmp_path):
    (tmp_path / "keep.bin").write_bytes(b"x" * 1000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "inner.bin").write_bytes(b"y" * 500)
    widget = TreeSizeShell()
    widget.start_scan(str(tmp_path))
    assert widget.wait_for_scan(60_000)
    return widget


def _node_named(store, name):
    return next(i for i in range(len(store)) if store.name(i) == name)


def test_menu_offers_pros_actions(shell):
    node = _node_named(shell._store, "keep.bin")
    menu = shell.row_actions.menu_for(node)
    labels = [a.text() for a in menu.actions() if a.text()]
    for expected in ("Open", "Open containing folder", "Copy path",
                     "Exclude from scan", "Delete to Recycle Bin",
                     "Properties"):
        assert expected in labels, f"{expected} missing from {labels}"


def test_folders_can_be_scanned_from_the_menu_but_files_cannot(shell):
    folder = _node_named(shell._store, "sub")
    file_node = _node_named(shell._store, "keep.bin")
    folder_menu = shell.row_actions.menu_for(folder)
    file_menu = shell.row_actions.menu_for(file_node)
    folder_labels = [a.text() for a in folder_menu.actions()]
    file_labels = [a.text() for a in file_menu.actions()]
    assert "Scan this folder" in folder_labels
    assert "Scan this folder" not in file_labels


def test_no_menu_for_an_invalid_node(shell):
    assert shell.row_actions.menu_for(-1) is None
    assert shell.row_actions.menu_for(10_000) is None


def test_delete_is_disabled_for_a_protected_location(shell, monkeypatch):
    """A refused path gets a greyed entry with a reason, not one that looks
    available and then complains."""
    store = shell._store
    monkeypatch.setattr(
        "modules.treesize.ui.context_menu.guardrails.is_allowed",
        lambda path, override=False: False)
    menu = shell.row_actions.menu_for(_node_named(store, "keep.bin"))
    entries = {a.text(): a for a in menu.actions() if a.text()}
    assert not entries["Delete to Recycle Bin"].isEnabled()
    assert "Protected" in entries["Delete to Recycle Bin"].toolTip()


def test_copy_path_puts_the_real_path_on_the_clipboard(shell, qapp):
    from PyQt6.QtWidgets import QApplication
    node = _node_named(shell._store, "keep.bin")
    menu = shell.row_actions.menu_for(node)
    next(a for a in menu.actions() if a.text() == "Copy path").trigger()
    assert QApplication.clipboard().text().endswith("keep.bin")
    assert os.path.exists(QApplication.clipboard().text())


def test_exclude_from_menu_reaches_the_filter_set(shell):
    node = _node_named(shell._store, "keep.bin")
    menu = shell.row_actions.menu_for(node)
    next(a for a in menu.actions() if a.text() == "Exclude from scan").trigger()
    assert shell.wait_for_scan(60_000)
    assert "keep.bin" in shell._filters.exclude_globs


def test_cancelling_the_confirmation_deletes_nothing(shell, tmp_path, monkeypatch):
    node = _node_named(shell._store, "keep.bin")
    target = tmp_path / "keep.bin"
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: QMessageBox.StandardButton.Cancel)
    executed = []
    monkeypatch.setattr("modules.treesize.ui.context_menu.file_ops.execute",
                        lambda *a, **k: executed.append(a) or (True, ""))
    shell.row_actions._delete(node, recycle=True)
    assert not executed, "cancel must not reach execute()"
    assert target.exists()


def test_confirming_runs_through_preflight_and_execute(shell, tmp_path, monkeypatch):
    node = _node_named(shell._store, "keep.bin")
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda self: QMessageBox.StandardButton.Ok)
    seen = {}

    def fake_execute(preflight, recycle=True, dry_run=False, **kwargs):
        seen["paths"] = list(preflight.paths)
        seen["recycle"] = recycle
        seen["show_progress"] = kwargs.get("show_progress")
        return True, "ok"

    monkeypatch.setattr("modules.treesize.ui.context_menu.file_ops.execute",
                        fake_execute)
    monkeypatch.setattr(TreeSizeShell, "refresh_scan", lambda self: None)
    shell.row_actions._delete(node, recycle=True)
    assert seen["show_progress"] is True, (
        "a real delete should get the shell's own progress dialog")
    assert seen["recycle"] is True
    assert seen["paths"] and seen["paths"][0].endswith("keep.bin")


def test_properties_reports_the_stored_numbers(shell, monkeypatch):
    shown = {}
    monkeypatch.setattr(QMessageBox, "information",
                        lambda parent, title, text: shown.update(
                            title=title, text=text))
    shell.row_actions._properties(_node_named(shell._store, "keep.bin"))
    assert shown["title"] == "keep.bin"
    assert "1,000 B" in shown["text"], shown["text"]
    assert "Owner:" in shown["text"]


# ---- Move and Secure erase (spec 7.1) -----------------------------------

def test_the_menu_offers_move_and_secure_erase(shell):
    """Spec 7.1 lists four operations. Two of them had no way in at all."""
    menu = shell.row_actions.menu_for(_node_named(shell._store, "keep.bin"))
    labels = [a.text() for a in menu.actions() if a.text()]
    assert any(label.startswith("Move to") for label in labels), labels
    assert any("Secure erase" in label for label in labels), labels


def test_a_protected_path_disables_every_destructive_entry(shell, monkeypatch):
    """The guardrails already greyed out the two deletes; the two new
    operations are exactly as destructive and must be greyed out with them."""
    monkeypatch.setattr(
        "modules.treesize.ui.context_menu.guardrails.is_allowed",
        lambda path, override=False: False)
    menu = shell.row_actions.menu_for(_node_named(shell._store, "keep.bin"))
    destructive = [a for a in menu.actions()
                   if a.text().startswith(("Delete", "Move to", "Secure"))]
    assert len(destructive) == 4, [a.text() for a in destructive]
    assert not any(action.isEnabled() for action in destructive)


def test_permanent_delete_now_asks_the_user_to_type_it(shell, monkeypatch):
    """Spec 7.2 requires TYPED confirmation for permanent delete. It had a
    plain warning box, which an Enter keypress walks straight through."""
    from modules.treesize.ui import context_menu as menu_module

    seen = {}

    class _Dialog:
        def __init__(self, title, summary, phrase="DELETE", caveat="",
                     parent=None):
            seen["phrase"] = phrase
            seen["caveat"] = caveat
            self.dry_run = type("C", (), {"isChecked": lambda self: False})()

        def exec(self):
            return 0                      # cancelled: nothing must happen

    monkeypatch.setattr(menu_module, "TypedConfirmDialog", _Dialog)
    monkeypatch.setattr(menu_module.file_ops, "execute",
                        lambda *a, **k: pytest.fail("cancelled means nothing runs"))
    shell.row_actions._delete(_node_named(shell._store, "keep.bin"),
                              recycle=False)
    assert seen["phrase"]


def test_secure_erase_states_the_ssd_limitation(shell, monkeypatch):
    """Spec 7.1: the feature ships with the limitation stated, not implying a
    guarantee it cannot make."""
    from modules.treesize.ui import context_menu as menu_module

    seen = {}

    class _Dialog:
        def __init__(self, title, summary, phrase="DELETE", caveat="",
                     parent=None):
            seen["caveat"] = caveat
            self.dry_run = type("C", (), {"isChecked": lambda self: False})()

        def exec(self):
            return 0

    monkeypatch.setattr(menu_module, "TypedConfirmDialog", _Dialog)
    shell.row_actions._secure_erase(_node_named(shell._store, "keep.bin"))
    assert "SSD" in seen["caveat"]


def test_move_asks_where_to_and_does_nothing_when_cancelled(shell, monkeypatch,
                                                            tmp_path):
    from modules.treesize.ui import context_menu as menu_module

    monkeypatch.setattr(menu_module.QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: ""))
    monkeypatch.setattr(menu_module.file_ops, "move",
                        lambda *a, **k: pytest.fail("no destination, no move"))
    shell.row_actions._move(_node_named(shell._store, "keep.bin"))
