r"""Drive applier.apply_batch against the REAL catalog and this REAL machine,
without writing anything.

WRITES NOTHING. The engine handed to apply_batch records the steps it is given
and returns True without touching Windows -- so every control is then read
back UNCHANGED, which means a correct applier must report every single one as
APPLIED_UNVERIFIED. Any APPLIED_VERIFIED here is the applier believing a write
that never happened.

It also answers three questions no unit test over fake controls can:

* does TweakEngine understand every step type the catalog emits?
* would `check_applicable` refuse any of them before a write is attempted?
  (read-only: it only asks whether services/tasks/packages exist)
* what does the verify pass COST, now that it drops the snapshot caches?

    .\.venv\Scripts\python.exe tools\security_apply_dryrun.py
"""
import os
import sys
import tempfile
import time
from collections import Counter

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from core.backup_service import BackupService  # noqa: E402
from modules.security_dashboard import snapshots  # noqa: E402
from modules.security_dashboard.applier import apply_batch  # noqa: E402
from modules.security_dashboard.catalog import load_catalog  # noqa: E402
from modules.security_dashboard.catalog.model import ControlState  # noqa: E402
from modules.security_dashboard.staging import diff_against  # noqa: E402
from modules.tweaks.tweak_engine import TweakEngine  # noqa: E402

#: Step types tweak_engine._apply_step dispatches on. A catalog step of any
#: other type is logged as "Unknown step type" and SKIPPED -- the tweak then
#: reports success having done nothing at all.
KNOWN_STEP_TYPES = {"registry", "registry_delete", "service", "command",
                    "appx", "scheduled_task", "script"}


class RecordingEngine:
    """Accepts every write, performs none."""

    def __init__(self):
        self.tweaks = []

    def apply_tweak(self, tweak, rp_id, on_error=None):
        self.tweaks.append(tweak)
        return True


class RecordingBackup:
    def __init__(self):
        self.points = []

    def create_restore_point(self, label, module):
        self.points.append((label, module))
        return "dry-run"

    def record_steps(self, *a, **k):
        pass

    def backup_registry_key(self, *a, **k):
        pass


def main() -> int:
    catalog = load_catalog()
    target = {cid: c.desired for cid, c in catalog.items()
              if c.desired is not None}

    t0 = time.time()
    changeset = diff_against(catalog, target)
    staged_secs = time.time() - t0
    print(f"catalog {len(catalog)} controls, {len(target)} with a desired "
          f"value, {len(changeset)} staged in {staged_secs:.2f}s "
          f"({len(changeset.unread_before)} unreadable, "
          f"{len(changeset.one_way_changes)} one-way)")

    # --- what the engine would be handed ---------------------------------
    types = Counter()
    unknown = []
    for change in changeset.changes:
        for step in change.resolved_steps():
            kind = step.get("type")
            types[kind] += 1
            if kind not in KNOWN_STEP_TYPES:
                unknown.append((change.control_id, kind))
    print("step types:", dict(types))
    if unknown:
        print("!! STEPS TweakEngine WOULD SILENTLY SKIP:")
        for control_id, kind in unknown:
            print(f"     {control_id}: {kind!r}")

    # --- would the real engine even try? (read-only) ----------------------
    scratch = tempfile.mkdtemp(prefix="apply-dryrun-")
    real_engine = TweakEngine(BackupService(scratch))
    not_applicable = []
    for change in changeset.changes:
        tweak = {"id": change.control_id,
                 "steps": list(change.resolved_steps())}
        verdict = real_engine.check_applicable(tweak)
        if not verdict.applicable:
            not_applicable.append((change.control_id, verdict.reason))
    print(f"check_applicable: {len(changeset) - len(not_applicable)} of "
          f"{len(changeset)} would be attempted")
    for control_id, reason in not_applicable:
        print(f"     skipped: {control_id}: {reason}")

    # --- the apply path itself -------------------------------------------
    snapshots.invalidate()
    engine, backup = RecordingEngine(), RecordingBackup()
    t0 = time.time()
    result = apply_batch(changeset, engine, backup)
    apply_secs = time.time() - t0

    states = Counter(r.state for r in result.results)
    print(f"\napply_batch: {len(result.results)} results in {apply_secs:.1f}s")
    for state, count in states.most_common():
        print(f"     {state.value}: {count}")

    wrong = [r for r in result.results
             if r.state is ControlState.APPLIED_VERIFIED]
    if wrong:
        print(f"!! {len(wrong)} control(s) reported VERIFIED though nothing "
              "was written:")
        for r in wrong[:10]:
            print(f"     {r.control_id}: requested {r.requested!r}, "
                  f"observed {r.observed!r}")

    reboots = [r for r in result.results
               if r.state is ControlState.APPLIED_PENDING_REBOOT]
    print(f"pending reboot: {len(reboots)}")
    print(f"restore point: {backup.points}")
    return 1 if (wrong or unknown) else 0


if __name__ == "__main__":
    sys.exit(main())
