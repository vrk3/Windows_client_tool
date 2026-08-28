r"""Read-only probe: what the security catalog sees, and how that changes with
administrator rights.

WRITES NOTHING to the machine. Every call here is a Get-* / read: no
Set-MpPreference, no registry write, no service change. The point is to run it
once unelevated and once elevated and diff the two, because several readers do
not FAIL without administrator rights -- they answer, with less.

    .\.venv\Scripts\python.exe tools\security_catalog_probe.py <out.json>

Run elevated through tools/security_catalog_probe.ps1, which redirects its own
output to a file (Start-Process -Verb RunAs cannot redirect for you).
"""
import ctypes
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from modules.security_dashboard import security_reader, snapshots  # noqa: E402
from modules.security_dashboard.catalog import NOT_A_CONTROL, load_catalog  # noqa: E402
from modules.security_dashboard.catalog.model import Category  # noqa: E402

TASK_6 = (Category.DEFENDER, Category.EXPLOIT_CVE)


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def probe() -> dict:
    out = {"elevated": is_elevated(), "when": time.strftime("%Y-%m-%d %H:%M:%S")}

    # -- the raw fields whose unelevated answers were the interesting part ---
    prefs = snapshots.mp_preference()
    status = snapshots.mp_computer_status()
    out["mp_preference_refused"] = snapshots.unavailable("mp_preference")
    out["mp_computer_status_refused"] = snapshots.unavailable("mp_computer_status")
    out["raw"] = {
        field: prefs.get(field)
        for field in ("ExclusionPath", "ExclusionProcess", "ExclusionExtension",
                      "AttackSurfaceReductionRules_Ids",
                      "AttackSurfaceReductionRules_Actions",
                      "ControlledFolderAccessProtectedFolders",
                      "CloudExtendedTimeout", "CloudBlockLevel", "PUAProtection",
                      "MAPSReporting", "EnableNetworkProtection",
                      "EnableControlledFolderAccess", "ScanAvgCPULoadFactor",
                      "LowThreatDefaultAction", "ModerateThreatDefaultAction",
                      "HighThreatDefaultAction", "SevereThreatDefaultAction")
    }
    out["raw"]["IsTamperProtected"] = status.get("IsTamperProtected")
    out["raw"]["AMRunningMode"] = status.get("AMRunningMode")
    out["raw"]["RealTimeProtectionEnabled"] = status.get("RealTimeProtectionEnabled")

    # -- is the SpeculationControl module here at all? ----------------------
    out["speculation_refused"] = snapshots.unavailable("speculation_control")
    out["speculation_fields"] = sorted(snapshots.speculation_control())

    # -- Get-ProcessMitigation, as a census ---------------------------------
    mitigation = snapshots.process_mitigation()
    out["process_mitigation_refused"] = snapshots.unavailable("process_mitigation")
    on, off, notset = security_reader._mitigation_census(mitigation)
    out["mitigation_census"] = {"on": on, "off": off, "notset_count": len(notset)}

    # -- every Task 6 control, as the pane would read it --------------------
    t0 = time.time()
    rows = {}
    for cid, control in load_catalog().items():
        if control.category not in TASK_6:
            continue
        started = time.time()
        value = control.read()
        raw = control.reader() or {}
        rows[cid] = {"read": value, "desired": control.desired,
                     "writable": control.writable, "status": raw.get("status"),
                     "color": raw.get("color"), "available": raw.get("available"),
                     "details": raw.get("details"),
                     "secs": round(time.time() - started, 2)}
    out["controls"] = rows
    out["sweep_secs"] = round(time.time() - t0, 2)
    out["counts"] = {"controls": len(rows), "excluded": len(NOT_A_CONTROL)}
    return out


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "security_catalog_probe.json"
    result = probe()
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, default=str)
    print("elevated=%s  controls=%d  sweep=%.2fs  ->  %s"
          % (result["elevated"], result["counts"]["controls"],
             result["sweep_secs"], target))
