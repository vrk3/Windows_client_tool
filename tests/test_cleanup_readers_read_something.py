r"""A scanner whose target exists but which finds nothing has not looked.

The counterpart to tools/security_refusal_sweep.py, for the cleanup engine.
Three scanners were found this way, all of which had looked plausible for
as long as they existed:

* `scan_old_restore_points` — docstring "Old System Restore snapshots and
  shadow storage", body scans
  `...systemprofile\AppData\Local\Microsoft\Windows\WinX`, which is the
  Win+X shortcuts folder. It has never had anything to do with restore
  points, and the app already has a Restore Manager module that does.
* `scan_search_index` — looks under `%LOCALAPPDATA%\Microsoft\Search`. The
  index lives in `%ProgramData%\Microsoft\Search\Data\Applications\Windows`
  (Windows.edb). It returns 0 items on every Windows 11 machine.
* `scan_driver_store` — offers the whole 7.13 GB
  `DriverStore\FileRepository` as one deletable item. It is tagged danger
  so it is never auto-selected, but ticking it costs the machine its
  drivers. Superseded packages are `pnputil /enum-drivers` work, not a
  directory delete.

Nothing in 2,500 passing tests could see any of this, because a scanner
finding nothing is indistinguishable from software that is not installed —
which is the normal, correct answer for most of the catalog.
"""
import pytest

from modules.cleanup.cleanup_scanner import catalog


def test_the_restore_point_scanner_is_gone():
    """It measured the Win+X folder. Restore points are RestoreManager's."""
    from modules.cleanup import cleanup_scanner as cs

    assert not hasattr(cs, "scan_old_restore_points")


def test_the_duplicate_recycle_bin_scanner_is_gone():
    """scan_recycle_bin_drive was byte-identical to scan_recycle_bin, and
    per_drive_recycle_bin now covers both."""
    from modules.cleanup import cleanup_scanner as cs

    assert not hasattr(cs, "scan_recycle_bin_drive")


def test_neither_dead_scanner_is_still_wired_to_a_tab():
    from modules.cleanup.cleanup_module import (
        LARGE_EXTRA, LOGS_EXTRA, SYSTEM_EXTRA)

    offered = {fn.__name__ for fn in
               (*SYSTEM_EXTRA, *LOGS_EXTRA, *LARGE_EXTRA)}
    assert "scan_old_restore_points" not in offered
    assert "scan_recycle_bin_drive" not in offered


def test_the_search_index_scanner_looks_where_the_index_actually_is(monkeypatch):
    r"""Asserted on what it ASKS about, not on what it returns.

    `%ProgramData%\Microsoft\Search\Data\Applications\Windows` is not
    readable unelevated, and this suite runs unelevated — so requiring an
    item back would make the test a test of the token, not of the scanner.
    Recording the paths it offers to `_make_item` is the elevation-
    independent question.
    """
    import os

    from modules.cleanup.cleanup_scanner import scanners_system as ss

    asked = []
    real_make_item = ss._make_item

    def _record(path, *args, **kwargs):
        asked.append(os.path.normcase(path))
        return real_make_item(path, *args, **kwargs)

    monkeypatch.setattr(ss, "_make_item", _record)
    ss.scan_search_index(min_age_days=0)

    machine_wide = os.path.normcase(os.path.join(
        os.environ.get("ProgramData", r"C:\ProgramData"),
        r"Microsoft\Search\Data\Applications\Windows"))
    if not os.path.isdir(machine_wide):
        pytest.skip("no machine-wide search index on this machine")
    assert machine_wide in asked, (
        "the search index scanner still only looks at the per-user path, "
        "where nothing has lived since Windows 8")


def test_the_driver_store_scanner_no_longer_offers_a_bulk_delete():
    spec = catalog.load_catalog().get("driver_store")
    assert spec is not None, "keep the entry, with its reason — do not delete it"
    assert spec.disabled_reason, (
        "DriverStore\\FileRepository must not be offered as one deletable "
        "item; superseded packages are pnputil work")
    assert catalog.run_spec(spec).items == []


@pytest.mark.parametrize("spec_id,spec", sorted(catalog.load_catalog().items()))
def test_a_catalog_scanner_with_a_live_target_reports_it(spec_id, spec):
    """If the directory is there and non-empty, the scanner must say so.

    Skipped when the target is absent — "Steam is not installed" is the
    normal answer for most of this catalog and is not a defect.
    """
    import os

    if spec.disabled_reason:
        pytest.skip(spec.disabled_reason)

    def _has_content(target: str) -> bool:
        """True only when we could look AND there was something there.

        A refused directory is not an empty one — the same distinction the
        tweak and security engines draw between ERROR_FILE_NOT_FOUND and
        ERROR_ACCESS_DENIED. Unelevated, C:\\Windows\\Temp raises here.
        """
        try:
            if os.path.isfile(target):
                return True
            with os.scandir(target) as entries:
                return any(True for _ in entries)
        except OSError:
            return False

    live = [t for t in catalog.targets_of(spec) if _has_content(t)]
    if not live:
        pytest.skip("nothing of this scanner's targets is readable and present")

    result = catalog.run_spec(spec, min_age_days=0)
    assert result.items, (
        f"{spec_id} target(s) exist and are non-empty but it found nothing: "
        f"{live[:3]}")
