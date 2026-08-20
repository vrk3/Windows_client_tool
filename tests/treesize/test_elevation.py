"""Spec 9: the elevation offer.

"When not elevated, the Home tab's *Start as administrator* button and an
inline banner offer the fast path, reusing the existing restart flow at
`src/ui/main_window.py:106`."

Two things were missing. There was no banner at all, and the ribbon button did
not reuse the restart flow -- it opened a message box explaining that the user
could restart the application themselves, which is a description of the
feature rather than the feature.
"""
import pytest
from PyQt6.QtWidgets import QMessageBox

from modules.treesize.ui.panels import ElevationBanner
from modules.treesize.ui.shell import TreeSizeShell


# ---- the banner ---------------------------------------------------------

def test_the_banner_offers_the_action_not_just_the_news(qapp):
    """An inline banner that only states a fact is a worse message box."""
    banner = ElevationBanner()
    assert banner.button.text() == "Start as administrator"


def test_the_banner_is_hidden_when_already_elevated(qapp):
    banner = ElevationBanner()
    banner.set_elevated(True)
    assert not banner.isVisible()


def test_the_banner_appears_when_not_elevated(qapp):
    banner = ElevationBanner()
    banner.set_elevated(False)
    banner.show()
    assert banner.isVisibleTo(banner.parentWidget() or banner)
    assert "faster" in banner.text().lower()


def test_the_banner_stays_dismissed(qapp):
    """Dismissing is a decision about this session, not about this scan --
    re-showing it after every scan would make it an alert, not a banner."""
    banner = ElevationBanner()
    banner.set_elevated(False)
    banner.dismiss()
    banner.set_elevated(False)
    assert not banner.isVisible()


def test_the_button_relays_a_request(qapp):
    banner = ElevationBanner()
    seen = []
    banner.elevation_requested.connect(lambda: seen.append(True))
    banner.button.click()
    assert seen == [True]


# ---- the shell wiring ---------------------------------------------------

def test_the_shell_carries_the_banner(qapp):
    shell = TreeSizeShell()
    assert isinstance(shell.elevation_banner, ElevationBanner)


def test_requesting_elevation_reuses_the_apps_restart_flow(qapp, monkeypatch):
    """Spec 9 names the existing flow. Telling the user to go and restart the
    application themselves is not reusing it."""
    shell = TreeSizeShell()
    calls = []
    monkeypatch.setattr(shell, "_is_elevated", lambda: False)
    monkeypatch.setattr(shell, "_confirm_restart", lambda: True)
    monkeypatch.setattr("modules.treesize.ui.shell.restart_as_admin",
                        lambda: calls.append("restarted"))
    assert shell.request_elevation() is True
    assert calls == ["restarted"]


def test_declining_the_confirmation_does_not_restart(qapp, monkeypatch):
    shell = TreeSizeShell()
    calls = []
    monkeypatch.setattr(shell, "_is_elevated", lambda: False)
    monkeypatch.setattr(shell, "_confirm_restart", lambda: False)
    monkeypatch.setattr("modules.treesize.ui.shell.restart_as_admin",
                        lambda: calls.append("restarted"))
    assert shell.request_elevation() is False
    assert calls == []


def test_an_already_elevated_session_never_restarts(qapp, monkeypatch):
    """Restarting an elevated session to become elevated would drop the
    user's scan to achieve nothing."""
    shell = TreeSizeShell()
    calls = []
    monkeypatch.setattr(shell, "_is_elevated", lambda: True)
    monkeypatch.setattr(shell, "_confirm_restart",
                        lambda: pytest.fail("should not have asked"))
    monkeypatch.setattr("modules.treesize.ui.shell.restart_as_admin",
                        lambda: calls.append("restarted"))
    # The "already elevated" branch shows a real modal. Left unpatched it
    # blocks the run until something dismisses it -- five minutes, once.
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    assert shell.request_elevation() is False
    assert calls == []


def test_the_banner_button_is_wired_to_the_shell(qapp, monkeypatch):
    shell = TreeSizeShell()
    calls = []
    monkeypatch.setattr(shell, "_is_elevated", lambda: False)
    monkeypatch.setattr(shell, "_confirm_restart", lambda: True)
    monkeypatch.setattr("modules.treesize.ui.shell.restart_as_admin",
                        lambda: calls.append("restarted"))
    shell.elevation_banner.button.click()
    assert calls == ["restarted"]


def test_the_ribbon_button_is_wired_to_the_same_thing(qapp, monkeypatch):
    shell = TreeSizeShell()
    calls = []
    monkeypatch.setattr(shell, "_is_elevated", lambda: False)
    monkeypatch.setattr(shell, "_confirm_restart", lambda: True)
    monkeypatch.setattr("modules.treesize.ui.shell.restart_as_admin",
                        lambda: calls.append("restarted"))
    shell.ribbon.action("tools.admin").trigger()
    assert calls == ["restarted"]
