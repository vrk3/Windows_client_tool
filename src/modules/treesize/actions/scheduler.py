"""Scheduled scans (spec 8.4).

Registers a Windows scheduled task that runs the console harness against a
target and writes a snapshot, so the History view has a trend without anyone
remembering to press anything.

Follows the host application's existing pattern (`WinClientTool_Unattended-
Maintenance`): `schtasks` rather than the COM API, because it needs no extra
dependency and the failure mode is a readable exit code rather than an HRESULT.

Arguments are passed as a LIST, never a formatted command string. A scan
target is user data and there is no reason for it to reach a shell.
"""
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

TASK_NAME = "WinClientTool_TreeSizeScan"
CREATE_NO_WINDOW = 0x08000000
VALID_FREQUENCIES = ("DAILY", "WEEKLY")


def _run(args: list) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            args, capture_output=True, text=True,
            creationflags=CREATE_NO_WINDOW, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output.strip()


def command_for(target: str) -> list:
    """What the scheduled task will run.

    Uses the frozen executable when running frozen, and the interpreter plus
    the harness when running from source -- a task pointing at python.exe would
    simply not exist on a machine with only the portable build.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--treesize-scan", target]
    harness = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "..", "..", "..", "tools", "treesize_scan.py")
    return [sys.executable, os.path.normpath(harness), target, "--snapshot"]


def schedule(target: str, frequency: str = "DAILY",
             at: str = "20:00") -> tuple[bool, str]:
    """Create or replace the scheduled scan. Returns (ok, message)."""
    frequency = (frequency or "").upper()
    if frequency not in VALID_FREQUENCIES:
        return False, f"Unsupported frequency: {frequency}"
    if not target or not target.strip():
        return False, "No scan target given."

    parts = command_for(target)
    # schtasks takes the command as ONE string, so it is quoted here rather
    # than handed to a shell -- subprocess still receives a list.
    command = " ".join(f'"{p}"' if " " in p else p for p in parts)
    code, output = _run([
        "schtasks", "/Create", "/TN", TASK_NAME, "/TR", command,
        "/SC", frequency, "/ST", at, "/F",
    ])
    if code == 0:
        return True, f"Scheduled a {frequency.lower()} scan of {target} at {at}."
    logger.warning("schtasks /Create failed (%s): %s", code, output)
    if "Access is denied" in output:
        return False, ("Creating a scheduled task needs administrator rights. "
                       "Restart the application elevated and try again.")
    return False, f"Could not create the scheduled task: {output or code}"


def unschedule() -> tuple[bool, str]:
    code, output = _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
    if code == 0:
        return True, "Removed the scheduled scan."
    if "cannot find" in output.lower():
        return True, "There was no scheduled scan to remove."
    return False, f"Could not remove the scheduled task: {output or code}"


def is_scheduled() -> bool:
    code, _output = _run(["schtasks", "/Query", "/TN", TASK_NAME])
    return code == 0
