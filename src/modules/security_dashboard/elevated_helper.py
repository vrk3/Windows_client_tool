r"""Run one batch elevated, and report back through a file.

Three things this file exists to get right, each of which has already cost
this project a round trip somewhere else:

* **The command line is quoted.** `subprocess.list2cmdline` does it;
  `" ".join(sys.argv)` -- which `core.admin_utils.restart_as_admin` still uses
  -- breaks on the first path with a space in it, and the batch file lives
  under `C:\Users\<name>\AppData\Local\...`.

* **The child reports through a file.** A `ShellExecuteW`-launched process
  cannot have its stdout captured by the parent (the same reason
  `tools/security_catalog_probe.ps1` redirects for itself), so the child
  writes the result and the parent reads it. No file, or an unreadable one,
  means the outcome is UNKNOWN -- never success.

* **The value the user reviewed travels with the change.** A batch of
  `(control_id, target)` pairs forces the child to re-read the machine for
  every `from_value` -- 12.7s unelevated, 31.4s elevated, all of it after the
  UAC prompt was granted -- and the revert it computes from that fresh reading
  need not be the one the review dialog showed. So `from_value` is in the file.
"""
import json
import logging
import os
import subprocess
import sys
from typing import Any, List, Optional, Sequence, Tuple

from .applier import BatchResult, ControlResult
from .catalog.model import ControlState

logger = logging.getLogger(__name__)

FLAG = "--apply-security-batch"
RESULT_FLAG = "--result"


def build_elevated_command(batch_path: str, result_path: str) -> Tuple[str, str]:
    """(executable, argument string) for ShellExecuteW(..., "runas", ...)."""
    args: List[str] = []
    if not getattr(sys, "frozen", False):
        # The script, absolute: the elevated child does not inherit this
        # process's working directory, so a relative argv[0] would not resolve.
        args.append(os.path.abspath(sys.argv[0]))
    args += [FLAG, batch_path, RESULT_FLAG, result_path]
    return sys.executable, subprocess.list2cmdline(args)


def changes_of(changeset) -> List[Tuple[str, Any, Any]]:
    """`(control_id, to_value, from_value)` for everything staged."""
    return [(c.control_id, c.to_value, c.from_value) for c in changeset.changes]


def write_batch_file(changes, path: str) -> None:
    """Write a ChangeSet -- or a plain sequence of tuples -- for the child.

    A row is `[control_id, to_value]` or `[control_id, to_value, from_value]`;
    the third field is what the parent read before staging, and the child uses
    it rather than reading the machine again.
    """
    if hasattr(changes, "changes"):
        rows: Sequence = changes_of(changes)
    else:
        rows = changes
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "changes": [list(c) for c in rows]}, handle)


def read_result_file(path: str) -> Optional[BatchResult]:
    """The helper's report, or None if it never wrote a usable one.

    None means the outcome is UNKNOWN. The caller re-reads the controls and
    shows what the machine actually says; it must never treat a missing
    result as either success or failure. A state string this build does not
    know makes the whole file unusable rather than a guess -- guessing is how
    a refusal gets rendered as a success.
    """
    try:
        # utf-8-sig, not utf-8: a JSON file that has been through Notepad or
        # PowerShell's Out-File carries a UTF-8 BOM, and json.load refuses it
        # outright -- "Unexpected UTF-8 BOM". Found by running the FROZEN exe
        # against a batch file PowerShell had written. utf-8-sig strips a BOM
        # if there is one and is identical to utf-8 if there is not.
        with open(path, encoding="utf-8-sig") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("no usable result file at %s: %s", path, exc)
        return None

    try:
        results = [
            ControlResult(
                control_id=row["control_id"],
                state=ControlState(row["state"]),
                requested=row.get("requested"),
                observed=row.get("observed"),
                reason=row.get("reason", ""))
            for row in payload.get("results", [])]
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("result file %s is not readable by this build: %s",
                       path, exc)
        return None

    return BatchResult(
        rp_id=payload.get("rp_id", ""),
        results=results,
        windows_restore_point=payload.get("windows_restore_point"),
        error=payload.get("error", ""))


def _payload(result: BatchResult) -> dict:
    return {
        "version": 1,
        "rp_id": result.rp_id,
        "windows_restore_point": result.windows_restore_point,
        "error": result.error,
        "results": [
            {"control_id": r.control_id, "state": r.state.value,
             "requested": r.requested, "observed": r.observed,
             "reason": r.reason}
            for r in result.results],
    }


def run_from_file(batch_path: str, result_path: str) -> int:
    """Entry point for the elevated child process.

    Always writes `result_path`, including when it fails: the parent has no
    other channel, and a batch that vanished without a word is indistinguishable
    from one that never ran.
    """
    from core.backup_service import BackupService
    from core.system_restore import create_restore_point
    from modules.tweaks.tweak_engine import TweakEngine

    from .applier import apply_batch
    from .catalog import load_catalog
    from .staging import ChangeSet

    backup = None
    try:
        # utf-8-sig for the same reason as read_result_file above.
        with open(batch_path, encoding="utf-8-sig") as handle:
            batch = json.load(handle)

        catalog = load_catalog()
        changeset = ChangeSet()
        for row in batch["changes"]:
            control_id, desired = row[0], row[1]
            control = catalog.get(control_id)
            if control is None:
                logger.warning("batch names control %r, which this build does "
                               "not have", control_id)
                continue
            if len(row) > 2:
                changeset.add(control, desired, from_value=row[2])
            else:
                changeset.add(control, desired)

        # src/app.py:18 -- there is no core/paths.py, and the pane reads the
        # records out of this same store.
        from app import _get_app_data_dir
        backup = BackupService(_get_app_data_dir())
        # This process is the elevated one, so it is the only place a real
        # Windows checkpoint can be taken; apply_batch spends the 30s only
        # when the batch carries a HIGH-risk control.
        result = apply_batch(changeset, TweakEngine(backup), backup,
                             create_windows_restore_point=create_restore_point)
        payload = _payload(result)
    except Exception as exc:
        logger.exception("the elevated batch could not be run")
        payload = {"version": 1, "rp_id": "", "windows_restore_point": None,
                   "results": [], "error": f"{type(exc).__name__}: {exc}"}
    finally:
        if backup is not None:
            backup.close()

    try:
        with open(result_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except OSError:
        logger.exception("could not write the result file at %s", result_path)
        return 2
    return 1 if payload.get("error") else 0
