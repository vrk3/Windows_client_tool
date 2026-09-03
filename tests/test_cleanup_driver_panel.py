r"""The Large Items driver-store panel.

Superseded driver packages are deliberately NOT in the checkbox tree that
`delete_items` walks: that path deletes directories, and deleting a
`DriverStore\FileRepository` folder out from under Windows is how a machine
loses a driver it still believes it has. The only correct removal is
`pnputil /delete-driver <published>`, so it lives behind its own explicit,
confirmed action.
"""
import time

import pytest
from PyQt6.QtCore import QThreadPool

from modules.cleanup.cleanup_scanner import driver_store


def _settle(qapp):
    QThreadPool.globalInstance().waitForDone(60_000)
    deadline = time.time() + 2
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


@pytest.fixture
def panel(qapp):
    from modules.cleanup.tabs._driver_panel import _DriverStorePanel
    return _DriverStorePanel()


def _report(available=True, count=2, total=2_000_000, unsized=0):
    import datetime

    from modules.cleanup.cleanup_scanner.driver_store import (
        DriverPackage, SupersededReport)

    def _pkg(index):
        return DriverPackage(
            published=f"oem{index}.inf", original="thing.inf",
            provider="Vendor", class_guid="{g}", version=(1, index),
            date=datetime.date(2025, 1, 1), version_text=f"01/01/2025 1.{index}")

    # The real wording, because the panel's job is to show the reason it
    # was given rather than to invent one.
    reason = ("pnputil could not enumerate the driver store — it needs "
              "elevation, and unelevated it prints its usage banner and "
              "exits 0 rather than reporting an error."
              if not available else
              f"63 driver packages installed, {count} superseded.")
    return SupersededReport(
        available=available,
        packages=[_pkg(i) for i in range(count)],
        total_bytes=total,
        unsized=[_pkg(100 + i) for i in range(unsized)],
        reason=reason)


def test_the_panel_starts_idle_with_removal_unavailable(panel):
    assert panel._remove_btn.isEnabled() is False
    assert panel._analyze_btn.isEnabled() is True


def test_a_refused_enumeration_says_so_and_offers_no_removal(qapp, panel):
    panel._on_report(_report(available=False, count=0, total=0))
    assert panel._remove_btn.isEnabled() is False
    assert "elevat" in panel._output.toPlainText().lower() or \
        "could not" in panel._output.toPlainText().lower()


def test_findings_enable_removal_and_are_listed(qapp, panel):
    panel._on_report(_report(count=2))
    text = panel._output.toPlainText()
    assert "oem0.inf" in text and "oem1.inf" in text
    assert panel._remove_btn.isEnabled() is True


def test_nothing_superseded_leaves_removal_disabled(qapp, panel):
    panel._on_report(_report(count=0, total=0))
    assert panel._remove_btn.isEnabled() is False


def test_packages_that_could_not_be_sized_are_shown_as_unknown(qapp, panel):
    panel._on_report(_report(count=1, total=1000, unsized=2))
    text = panel._output.toPlainText().lower()
    assert "unknown" in text or "could not" in text, (
        "packages with no measurable size were folded in silently")


def test_the_panel_never_hands_a_driver_to_delete_items(qapp, panel):
    """The whole safety property: no ScanItem, no checkbox, no rm -rf."""
    from modules.cleanup.cleanup_scanner import ScanItem

    panel._on_report(_report(count=2))
    for attr in vars(panel).values():
        assert not isinstance(attr, ScanItem)
        if isinstance(attr, (list, tuple)):
            assert not any(isinstance(x, ScanItem) for x in attr)


def test_removal_uses_pnputil_and_never_a_path_delete():
    import datetime

    from modules.cleanup.cleanup_scanner.driver_store import DriverPackage

    package = DriverPackage(
        published="oem35.inf", original="amd3dvcache.inf", provider="AMD",
        class_guid="{g}", version=(1, 0, 0, 11),
        date=datetime.date(2025, 9, 9))
    command = driver_store.removal_command(package)
    assert command[0].lower().startswith("pnputil")
    assert "/delete-driver" in command
    assert "oem35.inf" in command
    assert not any("FileRepository" in part for part in command), (
        "removal addressed the store directory instead of the package")


def test_the_analyze_button_runs_off_the_ui_thread(qapp, panel, monkeypatch):
    calls = []

    def _slow_report():
        calls.append(time.time())
        return _report(count=1)

    monkeypatch.setattr(driver_store, "superseded_report", _slow_report)
    panel._analyze()
    assert panel._analyze_btn.isEnabled() is False, "button stayed live"
    _settle(qapp)
    assert calls, "the report never ran"
    assert panel._analyze_btn.isEnabled() is True, "button never came back"
