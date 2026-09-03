r"""The same directory must not be walked once per tab.

Overview, System Junk and Quick Cleanup all run overlapping scanner sets,
and every one of them re-walks the same trees. %TEMP% on this machine is
47.36 GB across 46,825 directories and 53,926 files — a ~3s walk — and
scan_temp_files and scan_user_crash_dumps both measure it, on the Overview
AND again on System Junk AND again on Quick Cleanup's auto-refresh.

A short-lived shared cache collapses that. Two things it must get right:

* callers get their OWN ScanItems. The UI toggles `selected` on them, so a
  shared object would let one tab's checkbox state show up in another's.
* a delete invalidates it. Serving a pre-delete measurement afterwards
  would report space as still reclaimable when it is already gone.
"""
import time

import pytest

from modules.cleanup.cleanup_scanner import ScanItem, ScanResult, scan_cache


@pytest.fixture(autouse=True)
def _clean_cache():
    scan_cache.invalidate()
    yield
    scan_cache.invalidate()


def _counting_scanner():
    calls = []

    def scan_counted(min_age_days: int = 0) -> ScanResult:
        calls.append(min_age_days)
        result = ScanResult()
        result.items = [ScanItem(path=r"C:\somewhere", size=10, is_dir=True)]
        result.total_size = 10
        return result

    scan_counted.calls = calls
    return scan_counted


def test_a_second_call_inside_the_ttl_does_not_rerun_the_scanner():
    scanner = _counting_scanner()
    scan_cache.cached_scan(scanner, 0)
    scan_cache.cached_scan(scanner, 0)
    assert len(scanner.calls) == 1


def test_the_scanner_runs_again_once_the_entry_is_stale():
    scanner = _counting_scanner()
    scan_cache.cached_scan(scanner, 0, ttl_seconds=0.05)
    time.sleep(0.1)
    scan_cache.cached_scan(scanner, 0, ttl_seconds=0.05)
    assert len(scanner.calls) == 2


def test_a_different_age_filter_is_a_different_measurement():
    scanner = _counting_scanner()
    scan_cache.cached_scan(scanner, 0)
    scan_cache.cached_scan(scanner, 30)
    assert scanner.calls == [0, 30]


def test_each_caller_gets_its_own_items_to_tick():
    scanner = _counting_scanner()
    first = scan_cache.cached_scan(scanner, 0)
    first.items[0].selected = False

    second = scan_cache.cached_scan(scanner, 0)
    assert second.items[0].selected is True, (
        "one tab's checkbox state leaked into another's results")
    assert second.items[0] is not first.items[0]


def test_deleting_invalidates_the_cache(monkeypatch, tmp_path):
    """A pre-delete measurement must never be served after the delete."""
    from modules.cleanup.cleanup_scanner import scanners_system as ss

    scanner = _counting_scanner()
    scan_cache.cached_scan(scanner, 0)

    victim = tmp_path / "gone.txt"
    victim.write_text("x")
    ss.delete_items([ScanItem(path=str(victim), size=1, is_dir=False,
                              selected=True)])

    scan_cache.cached_scan(scanner, 0)
    assert len(scanner.calls) == 2, "stale sizes served after a delete"


def test_the_scan_tab_measures_a_shared_scanner_once(qapp):
    """Two tabs over the same scanner walk the tree once between them."""
    from PyQt6.QtCore import QThreadPool
    from modules.cleanup.tabs._scan_tab import _ScanTab

    scanner = _counting_scanner()
    first = _ScanTab({scanner: ("Shared", "safe")})
    second = _ScanTab({scanner: ("Shared", "safe")})
    first._do_scan()
    QThreadPool.globalInstance().waitForDone(30_000)
    second._do_scan()
    QThreadPool.globalInstance().waitForDone(30_000)

    deadline = time.time() + 2
    while time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert len(scanner.calls) == 1, (
        f"the tree was walked {len(scanner.calls)} times for two tabs")
