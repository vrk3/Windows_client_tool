r"""A cancelled Cleanup scan must leave the tab usable.

`main_window._on_module_selected` calls `on_deactivate()` on the module you
are leaving, and `CleanupModule.on_deactivate` cancels every in-flight scan
worker. `Worker.cancel()` only sets a flag: `Worker.run` then emits
`cancelled` and NEVER `result` or `error` (core/worker.py). Nothing was
connected to `cancelled`, so the tab's completion counter never reached
zero, `_scanning` was never cleared, and `_cancel_all` reset none of it.

The tab was then dead for the life of the process -- progress bar up,
status stuck on "Scanning...", Scan button disabled, and `_do_scan*`
returning early on `if self._scanning`. Measured on the real app: click
Cleanup, glance at another module while it scans, come back to a tab that
never finishes. That is the "it scanned for over 30 minutes" report; the
scan itself takes 6-36 seconds.
"""
import threading
import time

import pytest
from PyQt6.QtCore import QThreadPool

from modules.cleanup.cleanup_scanner import ScanResult


def _settle(qapp, timeout_ms: int = 30_000) -> None:
    """Let every worker finish and every queued signal be delivered."""
    QThreadPool.globalInstance().waitForDone(timeout_ms)
    deadline = time.time() + 2
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


@pytest.fixture
def blocking_scanner():
    """A scanner the test can hold open, so cancel really lands mid-scan."""
    started = threading.Event()
    release = threading.Event()

    def _scan(min_age_days: int = 0) -> ScanResult:
        started.set()
        release.wait(30)
        return ScanResult()

    _scan.started = started
    _scan.release = release
    return _scan


def test_overview_is_usable_again_after_a_scan_is_cancelled(
        qapp, monkeypatch, blocking_scanner):
    from modules.cleanup.tabs import _overview_tab as ov

    monkeypatch.setattr(ov, "_OV_GROUPS", [("Slow Group", [blocking_scanner])])
    tab = ov._OverviewTab()
    tab._build_table()
    tab._do_scan_all()
    assert blocking_scanner.started.wait(10), "scan never started"

    tab._cancel_all()               # what switching modules does
    blocking_scanner.release.set()
    _settle(qapp)

    assert tab._pending == 0, "cancelled workers never resolved the counter"
    assert tab._scanning is False
    assert tab._scan_btn.isEnabled(), "Scan button left disabled forever"


def test_a_cancelled_overview_scan_can_be_started_again(
        qapp, monkeypatch, blocking_scanner):
    from modules.cleanup.tabs import _overview_tab as ov

    monkeypatch.setattr(ov, "_OV_GROUPS", [("Slow Group", [blocking_scanner])])
    tab = ov._OverviewTab()
    tab._build_table()
    tab._do_scan_all()
    assert blocking_scanner.started.wait(10)
    tab._cancel_all()
    blocking_scanner.release.set()
    _settle(qapp)

    blocking_scanner.started.clear()
    blocking_scanner.release.set()
    tab._do_scan_all()

    assert blocking_scanner.started.wait(10), "Scan did nothing after a cancel"
    _settle(qapp)


def test_scan_tab_is_usable_again_after_a_scan_is_cancelled(
        qapp, blocking_scanner):
    from modules.cleanup.tabs._scan_tab import _ScanTab

    tab = _ScanTab({blocking_scanner: ("Slow", "safe")})
    tab._do_scan()
    assert blocking_scanner.started.wait(10), "scan never started"

    tab._cancel_all()
    blocking_scanner.release.set()
    _settle(qapp)

    assert tab._scanning is False
    assert tab._scan_btn.isEnabled(), "Scan button left disabled forever"


def test_a_cancelled_scan_tab_rescans_on_next_activation(
        qapp, blocking_scanner):
    """A cancelled scan produced no results, so it must not count as scanned."""
    from modules.cleanup.tabs._scan_tab import _ScanTab

    tab = _ScanTab({blocking_scanner: ("Slow", "safe")})
    tab.auto_scan()
    assert blocking_scanner.started.wait(10)
    tab._cancel_all()
    blocking_scanner.release.set()
    _settle(qapp)

    blocking_scanner.started.clear()
    blocking_scanner.release.set()
    tab.auto_scan()

    assert blocking_scanner.started.wait(10), "tab never rescanned"
    _settle(qapp)
