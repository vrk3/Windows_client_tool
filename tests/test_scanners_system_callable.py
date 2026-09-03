"""Every scanner in scanners_system can actually be called.

Written because one of them could not. `scan_ide_caches` read
`os.environ["TEMP"]` into a local at the top and used it two hundred lines
later, under `if temp:`. A lint pass removed the assignment -- ruff had
flagged the `home` local on the line above it as unused, and the two went
out together -- and the whole 4,148-test suite stayed green, because
nothing in it calls this module's scanners at all.

That is the gap this file closes. It does not assert what they find: these
read the real machine, so the answer depends on what is installed. It
asserts they run, which is the part that was broken.
"""
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from modules.cleanup.cleanup_scanner import scanners_system
from modules.cleanup.cleanup_scanner._common import ScanResult


def _scanners():
    for name, fn in vars(scanners_system).items():
        if not name.startswith("scan_") or not inspect.isfunction(fn):
            continue
        if fn.__module__ != scanners_system.__name__:
            continue
        yield name, fn


def test_there_are_scanners_to_check():
    assert len(list(_scanners())) > 5


@pytest.mark.parametrize("name,fn", list(_scanners()), ids=lambda v: v if isinstance(v, str) else "")
def test_scanner_runs_and_returns_a_scan_result(name, fn, tmp_path, monkeypatch):
    """Point every well-known directory at an empty temp dir, so this reads
    nothing real and still executes each scanner top to bottom."""
    for var in ("TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "USERPROFILE",
                "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "windir"):
        monkeypatch.setenv(var, str(tmp_path))

    result = fn()

    assert isinstance(result, ScanResult), f"{name} returned {type(result).__name__}"
    assert result.total_size >= 0
