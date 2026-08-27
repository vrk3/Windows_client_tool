"""The Unblock Program / Unblock Folder buttons, driven through the real pane.

These run the actual Workers on the real global thread pool and pump the Qt
event loop, so the queued-signal wiring is exercised rather than mocked out —
that wiring is where the bugs live. Only netsh itself is faked.
"""
import pytest
from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QFileDialog, QMessageBox

from modules.firewall_rules import firewall_manager_module as fw
from modules.firewall_rules.firewall_manager_module import (
    FirewallManagerModule, FirewallRule,
)

VLC = r"C:\Program Files\VideoLAN\VLC\vlc.exe"
UPDATER = r"C:\Program Files\VideoLAN\updater.exe"


def _rule(name, program, action="Block", direction="Out"):
    return FirewallRule(
        name=name, enabled="Yes", direction=direction, action=action,
        protocol="Any", local_port="Any", remote_port="Any",
        program=program, profile="Private",
    )


BLOCKED = [
    _rule("Block vlc", VLC),
    _rule("Block vlc", VLC, direction="In"),
    _rule("Allow vlc", VLC, action="Allow"),
    _rule("Block updater", UPDATER),
    _rule("Block notepad", r"C:\Windows\System32\notepad.exe"),
]


@pytest.fixture
def pane(qapp):
    module = FirewallManagerModule()
    module.on_start(None)
    module.create_widget()
    return module


@pytest.fixture
def dialogs(monkeypatch):
    """Capture every message box instead of showing it."""
    seen = {"info": [], "warn": []}
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda p, t, m, *a, **k: seen["info"].append((t, m))),
    )
    monkeypatch.setattr(
        QMessageBox, "warning",
        staticmethod(lambda p, t, m, *a, **k: seen["warn"].append((t, m))),
    )
    return seen


def _pump(qapp, tries=60):
    """Let the workers finish and their queued signals be delivered."""
    for _ in range(tries):
        QThreadPool.globalInstance().waitForDone(100)
        qapp.processEvents()


@pytest.fixture
def fake_firewall(monkeypatch):
    """A live rule set that netsh 'deletes' from, so verification is real."""
    state = {"rules": list(BLOCKED), "deleted": []}

    def fake_fetch():
        return list(state["rules"])

    def fake_delete(rule):
        state["deleted"].append((rule.name, rule.program, rule.direction))
        before = len(state["rules"])
        state["rules"] = [
            r for r in state["rules"]
            if not (r.name == rule.name and r.program == rule.program
                    and r.direction == rule.direction)
        ]
        return (True, "Ok.") if len(state["rules"]) < before else (False, "No rules match")

    monkeypatch.setattr(fw, "fetch_firewall_rules", fake_fetch)
    monkeypatch.setattr(fw, "netsh_delete_matching_rule", fake_delete)
    return state


# ── the buttons exist and follow the pane's enabled state ───────────────────

def test_both_unblock_buttons_are_on_the_toolbar(pane):
    assert pane._unblock_btn.text() == "Unblock Program"
    assert pane._unblock_folder_btn.text() == "Unblock Folder"


def test_unblock_buttons_are_disabled_while_the_pane_is_busy(pane):
    pane._set_buttons_enabled(False)
    assert pane._unblock_btn.isEnabled() is False
    assert pane._unblock_folder_btn.isEnabled() is False

    pane._set_buttons_enabled(True)
    assert pane._unblock_btn.isEnabled() is True
    assert pane._unblock_folder_btn.isEnabled() is True


# ── unblock a program ───────────────────────────────────────────────────────

def test_unblocking_a_program_removes_only_its_block_rules(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (VLC, ""))
    )
    monkeypatch.setattr(fw, "confirm_destructive", lambda *a, **k: True)

    pane._unblock_program()
    _pump(qapp)

    assert sorted(n for n, _p, _d in fake_firewall["deleted"]) == [
        "Block vlc", "Block vlc"
    ]
    remaining = {r.name for r in fake_firewall["rules"]}
    assert remaining == {"Allow vlc", "Block updater", "Block notepad"}
    assert dialogs["info"] and dialogs["info"][0][0] == "Unblocked"
    assert dialogs["warn"] == []
    assert "2 rule(s) removed" in pane._status_lbl.text()


def test_declining_the_confirmation_deletes_nothing(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (VLC, ""))
    )
    monkeypatch.setattr(fw, "confirm_destructive", lambda *a, **k: False)

    pane._unblock_program()
    _pump(qapp)

    assert fake_firewall["deleted"] == []
    assert len(fake_firewall["rules"]) == len(BLOCKED)
    assert pane._status_lbl.text() == "Unblock cancelled."


def test_a_program_with_no_block_rule_says_so_and_never_asks(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **k: (r"C:\Tools\clean.exe", "")),
    )
    monkeypatch.setattr(
        fw, "confirm_destructive",
        lambda *a, **k: pytest.fail("asked to delete nothing"),
    )

    pane._unblock_program()
    _pump(qapp)

    assert fake_firewall["deleted"] == []
    assert dialogs["info"] and dialogs["info"][0][0] == "Nothing to Unblock"


def test_cancelling_the_file_dialog_does_nothing(pane, monkeypatch, fake_firewall):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    monkeypatch.setattr(
        fw, "fetch_firewall_rules", lambda: pytest.fail("scanned after cancel")
    )
    pane._unblock_program()


# ── unblock a folder ────────────────────────────────────────────────────────

def test_unblocking_a_folder_clears_every_block_rule_beneath_it(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: r"C:\Program Files\VideoLAN"),
    )
    monkeypatch.setattr(fw, "confirm_destructive", lambda *a, **k: True)

    pane._unblock_folder()
    _pump(qapp)

    # Both vlc.exe block rules plus the sibling updater.exe, and nothing else.
    assert {r.name for r in fake_firewall["rules"]} == {"Allow vlc", "Block notepad"}
    assert dialogs["warn"] == []
    assert "3 rule(s) removed" in pane._status_lbl.text()


def test_an_unrelated_folder_reports_nothing_to_unblock(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: r"C:\Users\someone\Downloads"),
    )
    pane._unblock_folder()
    _pump(qapp)

    assert fake_firewall["deleted"] == []
    assert dialogs["info"] and dialogs["info"][0][0] == "Nothing to Unblock"


# ── failure is reported, not swallowed ──────────────────────────────────────

def test_a_rule_that_survives_deletion_is_reported(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    """netsh can exit 0 and leave the rule in place; the pane re-reads the
    rules and must say so rather than claiming success."""
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (VLC, ""))
    )
    monkeypatch.setattr(fw, "confirm_destructive", lambda *a, **k: True)
    monkeypatch.setattr(fw, "netsh_delete_matching_rule", lambda r: (True, "Ok."))

    pane._unblock_program()
    _pump(qapp)

    assert dialogs["info"] == [], "must not claim success while rules remain"
    assert dialogs["warn"] and dialogs["warn"][0][0] == "Unblock Incomplete"
    assert "2 block rule(s) remain" in pane._status_lbl.text()


def test_a_netsh_error_is_surfaced_with_its_message(
    pane, qapp, monkeypatch, dialogs, fake_firewall
):
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (VLC, ""))
    )
    monkeypatch.setattr(fw, "confirm_destructive", lambda *a, **k: True)
    monkeypatch.setattr(
        fw, "netsh_delete_matching_rule", lambda r: (False, "Access is denied.")
    )

    pane._unblock_program()
    _pump(qapp)

    assert dialogs["warn"]
    assert "Access is denied." in dialogs["warn"][0][1]
