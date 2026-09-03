r"""Scanning must never take the Windows servicing lock.

`scan_winsxs_cleanup` shelled out to
`Dism.exe /Online /Cleanup-Image /AnalyzeComponentStore` with a 120s
timeout. Unelevated DISM refuses in 0.03s (exit 740), which is why this
never showed up in testing — but the app runs elevated, and there the call
**measured 25-30 seconds and returned 0 items** on this machine. It was 70%
of the System Junk tab's entire runtime, for nothing, and it holds the
servicing lock while it runs, blocking Windows Update.

Large Items already has an explicit "Analyze WinSxS" button that runs the
same command on purpose, on its own long-operation pool. A scan does not
get to do it behind the user's back.

This test runs every scanner with subprocess patched and asserts none of
them invokes an image-servicing tool.
"""
import subprocess

import pytest

from modules.cleanup import cleanup_scanner as cs
from modules.cleanup.cleanup_scanner import catalog

#: Tools that take the servicing lock, or otherwise cost minutes.
FORBIDDEN = ("dism", "pkgmgr", "sfc", "compact", "defrag")


def _scanner_functions():
    catalog_names = {f"scan_{spec_id}" for spec_id in catalog.load_catalog()}
    for name in sorted(dir(cs)):
        if not name.startswith("scan_") or name in catalog_names:
            continue
        fn = getattr(cs, name)
        if callable(fn):
            yield name, fn


def test_no_scanner_shells_out_to_an_image_servicing_tool(monkeypatch):
    calls = []

    def _record(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def _no_popen(cmd, *args, **kwargs):
        calls.append(cmd)
        raise AssertionError(f"a scanner spawned a process: {cmd!r}")

    monkeypatch.setattr(subprocess, "run", _record)
    monkeypatch.setattr(subprocess, "Popen", _no_popen)

    for name, fn in _scanner_functions():
        try:
            fn(min_age_days=0)
        except Exception:
            # A scanner failing on this machine is not what this test is
            # about; the recorded commands are.
            pass

    offenders = []
    for cmd in calls:
        argv0 = (cmd[0] if isinstance(cmd, (list, tuple)) else str(cmd)).lower()
        exe = argv0.rsplit("\\", 1)[-1].removesuffix(".exe")
        if exe in FORBIDDEN:
            offenders.append(cmd)

    assert not offenders, (
        f"scanning invoked an image-servicing tool: {offenders}")


def test_no_tab_offers_a_scanner_that_analyses_the_component_store():
    """The Large Items button owns WinSxS analysis; no scan list may."""
    from modules.cleanup.cleanup_module import (
        LARGE_EXTRA, LOGS_EXTRA, SYSTEM_EXTRA)

    offered = {fn.__name__ for fn in
               (*SYSTEM_EXTRA, *LOGS_EXTRA, *LARGE_EXTRA)}
    assert "scan_winsxs_cleanup" not in offered


def test_the_winsxs_scanner_is_gone_entirely():
    assert not hasattr(cs, "scan_winsxs_cleanup"), (
        "removed from the tabs but still exported — it will be wired up again")


@pytest.mark.parametrize("name", ["cleanup_winsxs"])
def test_the_deliberate_winsxs_action_is_kept(name):
    """Removing the scanner must not remove the action behind the button."""
    assert callable(getattr(cs, name, None))
