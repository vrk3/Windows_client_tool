"""The cleanup scanners are data, not 538 near-identical functions.

Each was the same three lines: expand some environment variables into paths,
hand each to `_make_item`, sum the sizes. A census found 430 that were a
plain path list and 79 more that differed only by a glob — 95% of 440 KB was
boilerplate around the 5% that was actually knowledge.

The Tweaks module already proved the shape: ~700 entries in JSON behind one
engine, with one structural test that asks every entry a question at once.
These are those questions, and none of them could be asked reliably by
reading 538 functions.
"""
import os

import pytest

from modules.cleanup.cleanup_scanner.catalog import (
    SAFETY_LEVELS, ScannerSpec, expand, load_catalog, run_spec, scanner_for,
    targets_of,
)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


# ── structure ──────────────────────────────────────────────────────────

def test_the_catalog_holds_the_verified_pilot(catalog):
    """41 scanners so far, not 538.

    The extractor could convert 521 of 538, but the verifier — which runs
    the original and the spec side by side against a real machine —
    disagreed on 28 of the 93 it could actually check. A 30% error rate on
    the checkable subset means "neither found anything here" proves nothing
    about the other 428, so only the ones that were verified against real
    data are shipped. tools/verify_scanner_conversion.py is how the next
    batch earns its place.
    """
    assert len(catalog) >= 41, f"only {len(catalog)} scanners loaded"


def test_every_spec_declares_a_valid_safety_level(catalog):
    """The thing a review cannot reliably check by eye, and the thing that
    decides whether "Clean All Safe" touches it."""
    for spec_id, spec in catalog.items():
        assert spec.safety in SAFETY_LEVELS, f"{spec_id}: {spec.safety!r}"


def test_no_two_scanners_share_a_label(catalog):
    """Two rows reading "Chrome Cache" in the same list is a bug the user
    sees and cannot resolve."""
    seen = {}
    for spec_id, spec in catalog.items():
        assert spec.label not in seen, (
            f"{spec_id} and {seen[spec.label]} are both labelled {spec.label!r}")
        seen[spec.label] = spec_id


def test_every_scanner_has_a_label_and_at_least_one_path(catalog):
    for spec_id, spec in catalog.items():
        assert spec.label.strip(), f"{spec_id} has no label"
        assert spec.paths, f"{spec_id} points at nothing"


def test_no_scanner_hardcodes_a_drive_letter(catalog):
    """audit #16 — Windows need not be on C:, and a scanner that assumes it
    finds nothing on a machine where it is not, silently."""
    offenders = [
        f"{spec_id}: {path}"
        for spec_id, spec in catalog.items()
        for path in spec.paths
        if len(path) > 2 and path[1:3] == ":\\"
    ]
    assert offenders == [], "\n  ".join([""] + offenders)


def test_every_path_uses_a_variable_that_exists_on_windows(catalog):
    """A typo in a variable name is invisible: the path simply never
    resolves and the scanner reports nothing found."""
    known = {
        "LOCALAPPDATA", "APPDATA", "USERPROFILE", "ProgramData", "windir",
        "TEMP", "TMP", "PUBLIC", "ProgramFiles", "ProgramFiles(x86)",
        "SystemDrive", "SystemRoot", "ALLUSERSPROFILE", "HOMEDRIVE",
    }
    import re
    bad = []
    for spec_id, spec in catalog.items():
        for path in spec.paths:
            for name in re.findall(r"%([^%]+)%", path):
                if name not in known:
                    bad.append(f"{spec_id}: %{name}%")
    assert bad == [], "\n  ".join([""] + bad)


# ── engine behaviour ───────────────────────────────────────────────────

def test_a_spec_pointing_nowhere_returns_an_empty_result_not_an_error():
    """Most of these belong to optional software. "Steam is not installed"
    is the normal answer, not a failure."""
    spec = ScannerSpec(id="nope", label="Nope", category="test",
                       paths=[r"%LOCALAPPDATA%\definitely-not-here-9f3a"])
    result = run_spec(spec)
    assert result.items == []
    assert result.total_size == 0


def test_an_unset_variable_skips_the_path_rather_than_matching_it_literally(monkeypatch):
    """os.path.expandvars leaves %FOO% intact when FOO is unset, and
    os.path.exists cheerfully says False for it — so the scanner silently
    reports nothing rather than saying it could not look."""
    monkeypatch.delenv("WCT_TEST_UNSET", raising=False)
    spec = ScannerSpec(id="unset", label="Unset", category="test",
                       paths=[r"%WCT_TEST_UNSET%\cache"])
    assert expand(spec.paths[0]) is None
    assert targets_of(spec) == []


def test_a_glob_expands_to_what_is_there(tmp_path, monkeypatch):
    monkeypatch.setenv("WCT_TEST_ROOT", str(tmp_path))
    (tmp_path / "profile-a").mkdir()
    (tmp_path / "profile-b").mkdir()
    spec = ScannerSpec(id="globbed", label="Globbed", category="test",
                       paths=[r"%WCT_TEST_ROOT%\profile-*"])
    assert len(targets_of(spec)) == 2


def test_a_bad_safety_level_is_refused_at_load_time():
    with pytest.raises(ValueError, match="safety"):
        ScannerSpec(id="x", label="X", category="test", paths=["%TEMP%"],
                    safety="mostly-fine")


def test_a_scanner_with_no_paths_is_refused():
    with pytest.raises(ValueError, match="measures nothing"):
        ScannerSpec(id="x", label="X", category="test", paths=[])


def test_run_spec_measures_what_is_really_there(tmp_path, monkeypatch):
    monkeypatch.setenv("WCT_TEST_ROOT", str(tmp_path))
    payload = tmp_path / "junk.bin"
    payload.write_bytes(b"x" * 4096)
    spec = ScannerSpec(id="real", label="Real", category="test",
                       paths=[r"%WCT_TEST_ROOT%\junk.bin"], safety="caution")
    result = run_spec(spec)
    assert result.total_size == 4096
    assert result.items[0].safety == "caution"


def test_the_min_age_floor_is_honoured(tmp_path, monkeypatch):
    """A spec's min_age_default keeps recently-touched data out even when
    the tab's slider is at zero."""
    monkeypatch.setenv("WCT_TEST_ROOT", str(tmp_path))
    (tmp_path / "fresh.bin").write_bytes(b"x" * 10)
    spec = ScannerSpec(id="aged", label="Aged", category="test",
                       paths=[r"%WCT_TEST_ROOT%\fresh.bin"], min_age_default=30)
    assert run_spec(spec).items == []


# ── the compatibility surface the tabs rely on ─────────────────────────

def test_generated_scanners_keep_the_old_signature(catalog):
    """The cleanup tabs pass {function: label} dicts around, so a generated
    scanner has to be indistinguishable from the hand-written one it
    replaced."""
    spec_id = next(iter(catalog))
    fn = scanner_for(spec_id)
    assert fn.__name__ == f"scan_{spec_id}"
    result = fn()               # no arguments
    result_aged = fn(30)        # positional min_age_days
    assert result.total_size >= 0 and result_aged.total_size >= 0


def test_the_package_still_exports_the_scan_names(catalog):
    from modules.cleanup import cleanup_scanner
    for spec_id in list(catalog)[:25]:
        assert hasattr(cleanup_scanner, f"scan_{spec_id}"), spec_id
        assert callable(getattr(cleanup_scanner, f"scan_{spec_id}"))
