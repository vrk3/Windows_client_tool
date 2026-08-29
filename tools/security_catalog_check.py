r"""Drive the REAL catalog against THIS machine, and report what it can answer.

    .venv\Scripts\python.exe tools\security_catalog_check.py out.json
    .venv\Scripts\python.exe tools\security_catalog_check.py --compare a.json b.json

Reads every control, timing each one, and prints: how many answered, how many
came back unreadable, which readers cost the most, and what each tab of the
pane would cost to open. **It never presses a button.** `--apply` is a
separate opt-in that names ONE control id, reads it directly out of the
registry before and after, applies, verifies, reverts, and reads directly a
third time.

Run it once unelevated and once elevated (through a .ps1 wrapper --
Start-Process -Verb RunAs cannot redirect output) and diff the two: a control
whose two answers agree does not need administrator rights to be READ, and
`requires_admin` should say so. The flag gates the write, not the read.
"""
import argparse
import ctypes
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.security_dashboard import snapshots  # noqa: E402
from modules.security_dashboard.catalog import load_catalog  # noqa: E402

SLOW = 0.30
TAB_BUDGET = 3.0


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def read_everything() -> dict:
    catalog = load_catalog()
    snapshots.invalidate()
    rows = {}
    started = time.time()
    for control_id, control in catalog.items():
        t0 = time.time()
        try:
            value = control.read()
            error = ""
        except Exception as exc:            # read() catches its own, but
            value, error = None, repr(exc)  # a catalog bug could still raise
        rows[control_id] = {
            "value": value,
            "seconds": round(time.time() - t0, 3),
            "category": control.category.value,
            "desired": control.desired,
            "writable": control.writable,
            "requires_admin": control.requires_admin,
            "error": error,
        }
    return {
        "elevated": is_elevated(),
        "total_seconds": round(time.time() - started, 2),
        "controls": rows,
        "snapshot_refusals": {name: reason
                              for name, reason in snapshots.availability().items()
                              if reason},
    }


def report(data: dict) -> None:
    rows = data["controls"]
    answered = [c for c, r in rows.items() if r["value"] is not None]
    unread = [c for c, r in rows.items() if r["value"] is None]

    print(f"{'ELEVATED' if data['elevated'] else 'unelevated'}: "
          f"{len(rows)} controls read in {data['total_seconds']}s")
    print(f"   answered   : {len(answered)}")
    print(f"   unreadable : {len(unread)}")

    if data["snapshot_refusals"]:
        print("\nsnapshots that were refused (this is WHY, not a defect):")
        for name, reason in data["snapshot_refusals"].items():
            print(f"   {name:22} {reason[:90]}")

    print(f"\nreaders over {SLOW}s:")
    slow = sorted(((r["seconds"], c) for c, r in rows.items()
                   if r["seconds"] > SLOW), reverse=True)
    for seconds, control_id in slow:
        print(f"   {seconds:6.2f}s  {control_id}")
    if not slow:
        print("   none")

    print("\nper tab, the cost of opening it:")
    per_tab = defaultdict(float)
    per_tab_unread = defaultdict(int)
    for control_id, row in rows.items():
        per_tab[row["category"]] += row["seconds"]
        if row["value"] is None:
            per_tab_unread[row["category"]] += 1
    for name, seconds in sorted(per_tab.items(), key=lambda kv: -kv[1]):
        flag = f"   <- over {TAB_BUDGET}s" if seconds > TAB_BUDGET else ""
        print(f"   {name:24} {seconds:6.2f}s  "
              f"({per_tab_unread[name]} unreadable){flag}")

    problems = [c for c, r in rows.items()
                if r["desired"] is not None and r["value"] is not None
                and r["value"] != r["desired"]]
    print(f"\nnot at the catalog's recommended value: {len(problems)}")
    errors = {c: r["error"] for c, r in rows.items() if r["error"]}
    if errors:
        print("\nREADERS THAT RAISED (a catalog bug, not a refusal):")
        for control_id, error in errors.items():
            print(f"   {control_id}: {error}")


def compare(first: str, second: str) -> int:
    a, b = (json.load(open(p, encoding="utf-8")) for p in (first, second))
    label_a = "elevated" if a["elevated"] else "unelevated"
    label_b = "elevated" if b["elevated"] else "unelevated"
    print(f"{first} ({label_a})  vs  {second} ({label_b})\n")

    rows_a, rows_b = a["controls"], b["controls"]
    differ = []
    for control_id in sorted(set(rows_a) & set(rows_b)):
        if rows_a[control_id]["value"] != rows_b[control_id]["value"]:
            differ.append(control_id)

    print(f"{len(differ)} control(s) answer differently:\n")
    for control_id in differ:
        left, right = rows_a[control_id], rows_b[control_id]
        print(f"   {control_id:34} {str(left['value']):12} -> "
              f"{str(right['value']):12} (requires_admin="
              f"{left['requires_admin']})")

    same = [c for c in set(rows_a) & set(rows_b) if c not in differ]
    admin_but_same = [c for c in same if rows_a[c]["requires_admin"]
                      and rows_a[c]["value"] is not None]
    print(f"\n{len(admin_but_same)} control(s) marked requires_admin read the "
          "SAME both ways.")
    print("   requires_admin gates the WRITE, so that is not automatically "
          "wrong -- but any of these\n   that also writes without elevation "
          "has the flag for no reason.")
    return 0


def round_trip(control_id: str) -> int:
    """Read, apply, verify, revert, verify -- checking the REGISTRY directly.

    Not through the reader that decided in the first place: a reader that is
    wrong in the same way twice looks like a success.
    """
    import tempfile
    import winreg

    from core.backup_service import BackupService
    from modules.security_dashboard.applier import apply_batch
    from modules.security_dashboard.reverting import revert_batch
    from modules.security_dashboard.staging import ChangeSet
    from modules.tweaks.tweak_engine import TweakEngine

    catalog = load_catalog()
    control = catalog[control_id]
    steps = list(control.on_steps) + list(control.off_steps)
    registry = [s for s in steps if s.get("type") == "registry"]
    if not registry:
        print(f"{control_id} writes no registry value; nothing to read "
              "directly. Pick another control.")
        return 2
    key_path, value_name = registry[0]["key"], registry[0]["value"]

    def raw():
        hive_name, _, sub = key_path.partition("\\")
        hive = {"HKLM": winreg.HKEY_LOCAL_MACHINE,
                "HKCU": winreg.HKEY_CURRENT_USER}.get(hive_name.upper())
        try:
            with winreg.OpenKey(hive, sub) as handle:
                return winreg.QueryValueEx(handle, value_name)[0]
        except FileNotFoundError:
            return "<absent>"
        except OSError as exc:
            return f"<{exc.strerror}>"

    before_reader, before_raw = control.read(), raw()
    print(f"{control_id}")
    print(f"   reader says      : {before_reader!r}")
    print(f"   {key_path}\\{value_name} = {before_raw!r}")

    target = not before_reader if isinstance(before_reader, bool) \
        else control.desired
    if target is None or target == before_reader:
        print("   nothing to change; pick a control that is not already at "
              "its target")
        return 2

    store = tempfile.mkdtemp(prefix="catalog-check-")
    backup = BackupService(store)
    changeset = ChangeSet()
    changeset.add(control, target, from_value=before_reader)

    print(f"\n   applying -> {target!r}")
    applied = apply_batch(changeset, TweakEngine(backup), backup)
    for r in applied.results:
        print(f"   {r.state.value}: observed {r.observed!r}")
        if r.reason:
            print(f"      {r.reason.splitlines()[0]}")
    print(f"   registry now     : {raw()!r}")

    print("\n   reverting")
    reverted = revert_batch(applied.rp_id, backup, catalog,
                            expected={control_id: before_reader})
    for r in reverted.results:
        print(f"   {r.state.value}: observed {r.observed!r}")
        if r.reason:
            print(f"      {r.reason.splitlines()[0]}")
    after_raw = raw()
    print(f"   registry now     : {after_raw!r}")
    backup.close()

    ok = after_raw == before_raw
    print(f"\n   back to exactly what it was: {ok}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", help="where to write the readings")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"))
    parser.add_argument("--apply", metavar="CONTROL_ID",
                        help="round-trip ONE control: apply, verify, revert, "
                             "and read the registry directly at every step")
    args = parser.parse_args()

    if args.compare:
        return compare(*args.compare)
    if args.apply:
        return round_trip(args.apply)

    data = read_everything()
    report(data)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, default=str)
        print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
