r"""Cleanup must look at every fixed drive, not only C:.

Of 537 scanners, exactly two iterated drive letters -- and they were
`scan_recycle_bin` and `scan_recycle_bin_drive`, byte-identical
duplicates of each other. Everything else hardcoded C: or leaned on
`%windir%` / `%LOCALAPPDATA%`, which are on C: here.

Measured: this machine has C: (1.86 TB) and E: (5.63 TB, 550 GB used), and
`E:\temp` holds **20.36 GB that nothing in the cleaner could ever find**.

`%FIXED_DRIVES%` in a catalog path expands to one path per fixed volume.
Fixed only: expanding onto removable media would offer to delete from
whatever USB stick happens to be plugged in, and onto network drives would
walk the network.
"""
import os

import pytest

from modules.cleanup.cleanup_scanner import catalog, drives


def _fixed_roots_per_psutil():
    import psutil
    return {p.device.upper() for p in psutil.disk_partitions(all=False)
            if "fixed" in p.opts}


def test_fixed_drive_roots_agrees_with_an_independent_source():
    assert {r.upper() for r in drives.fixed_drive_roots()} == \
        _fixed_roots_per_psutil()


def test_removable_media_is_never_offered():
    import psutil
    removable = {p.device.upper() for p in psutil.disk_partitions(all=False)
                 if "removable" in p.opts}
    assert not ({r.upper() for r in drives.fixed_drive_roots()} & removable)


def test_the_token_expands_to_one_path_per_fixed_drive():
    spec = catalog.ScannerSpec(
        id="probe", label="Probe", paths=[r"%FIXED_DRIVES%\temp"])
    expected = {os.path.join(root, "temp") for root in drives.fixed_drive_roots()}
    assert set(catalog.targets_of(spec)) == expected


def test_the_token_composes_with_a_glob():
    spec = catalog.ScannerSpec(
        id="probe", label="Probe", paths=[r"%FIXED_DRIVES%\temp\*.tmp"])
    # Globs are resolved against the filesystem, so assert on the shape:
    # nothing outside a fixed drive may be returned.
    roots = tuple(r.upper() for r in drives.fixed_drive_roots())
    assert all(t.upper().startswith(roots) for t in catalog.targets_of(spec))


def test_an_unset_variable_still_skips_the_path(monkeypatch):
    """The existing contract: a half-expanded path is not a target."""
    monkeypatch.delenv("NOT_A_REAL_VARIABLE", raising=False)
    spec = catalog.ScannerSpec(
        id="probe", label="Probe", paths=[r"%NOT_A_REAL_VARIABLE%\x"])
    assert catalog.targets_of(spec) == []


def test_the_catalog_sweeps_temp_on_every_fixed_drive():
    specs = catalog.load_catalog()
    spec = specs.get("per_drive_temp")
    assert spec is not None, "no per-drive temp scanner in the catalog"
    targets = {os.path.normcase(t) for t in catalog.targets_of(spec)}
    for root in drives.fixed_drive_roots():
        assert os.path.normcase(os.path.join(root, "temp")) in targets


def test_the_recycle_bin_is_swept_on_every_fixed_drive():
    specs = catalog.load_catalog()
    spec = specs.get("per_drive_recycle_bin")
    assert spec is not None, "no per-drive recycle bin scanner in the catalog"
    targets = {os.path.normcase(t) for t in catalog.targets_of(spec)}
    for root in drives.fixed_drive_roots():
        assert os.path.normcase(os.path.join(root, "$Recycle.Bin")) in targets


@pytest.mark.parametrize("spec_id", [
    "per_drive_temp",
    "per_drive_recycle_bin",
    "per_drive_found_clusters",
])
def test_the_per_drive_scanners_are_offered_by_a_tab(spec_id):
    from modules.cleanup.cleanup_scanner.catalog import scanners_for

    offered = {fn.__name__ for fn in scanners_for("system")}
    assert f"scan_{spec_id}" in offered
