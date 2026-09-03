r"""Ask every cleanup scanner whether it actually read anything.

The sibling of `tools/security_refusal_sweep.py` and
`tools/tweak_refusal_sweep.py`, for the cleanup engine. Same idea, same
reason it exists: a reader whose answer never varies has not read
anything, and nothing in a green suite can see it.

Three scanners were found this way, each of which had looked perfectly
plausible for as long as it existed:

* `scan_old_restore_points` said "Old System Restore snapshots and shadow
  storage" and scanned the Win+X shortcuts folder.
* `scan_search_index` looked under %LOCALAPPDATA%, where the Windows Search
  index has not lived since Windows 8, so it answered "nothing" on every
  Windows 11 machine.
* `scan_driver_store` offered the entire 7.13 GB DriverStore as one
  deletable item.

The trick is that "found nothing" is the CORRECT answer for most of this
catalog — 385 of 456 specs point at software that is not installed here.
So the question is narrower: **its target directory exists and has content
in it, and the scanner still reports nothing.** That is not a preference,
it is a defect.

Run it unelevated first: that is what most of these paths are read as, and
a refused read that gets reported as "clean" is the exact shape being
hunted. Then run it elevated to see which findings were only refusals.

    .venv\Scripts\python.exe tools\cleanup_reader_sweep.py
    .venv\Scripts\python.exe tools\cleanup_reader_sweep.py --json out.json
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.cleanup import cleanup_scanner as cs            # noqa: E402
from modules.cleanup.cleanup_scanner import catalog          # noqa: E402


def _readable_with_content(path: str):
    """(exists, has_content, refused) — three answers, never two.

    A directory that cannot be opened is not an empty one. Collapsing
    those is how `check_bitlocker` came to report a refused read as "C: is
    not encrypted", and it is the same mistake here.
    """
    if not os.path.exists(path):
        return False, False, False
    if os.path.isfile(path):
        return True, os.path.getsize(path) > 0, False
    try:
        with os.scandir(path) as entries:
            return True, any(True for _ in entries), False
    except PermissionError:
        return True, False, True
    except OSError:
        return True, False, True


def sweep():
    findings = []
    checked = 0

    specs = catalog.load_catalog()
    for spec_id, spec in sorted(specs.items()):
        if spec.disabled_reason:
            continue
        live, refused = [], []
        for target in catalog.targets_of(spec):
            exists, has_content, was_refused = _readable_with_content(target)
            if was_refused:
                refused.append(target)
            elif exists and has_content:
                live.append(target)
        if not live:
            continue
        checked += 1
        result = catalog.run_spec(spec, min_age_days=0)
        if not result.items:
            findings.append({
                "scanner": f"scan_{spec_id}",
                "kind": "catalog",
                "label": spec.label,
                "live_targets": live[:5],
                "refused_targets": refused[:5],
            })

    catalog_names = {f"scan_{spec_id}" for spec_id in specs}
    for name in sorted(dir(cs)):
        if not name.startswith("scan_") or name in catalog_names:
            continue
        fn = getattr(cs, name)
        if not callable(fn):
            continue
        try:
            result = fn(min_age_days=0)
        except Exception as exc:                       # noqa: BLE001
            findings.append({"scanner": name, "kind": "hand-written",
                             "error": f"{type(exc).__name__}: {exc}"})
            continue
        checked += 1
        if not result.items:
            # A hand-written scanner builds its own targets, so there is no
            # path list to check against. Reported as "worth a look", not
            # as a defect — most of these are for software not installed.
            findings.append({"scanner": name, "kind": "hand-written",
                             "note": "returned nothing"})
    return checked, findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the findings to this file")
    parser.add_argument("--catalog-only", action="store_true",
                        help="skip the hand-written scanners, which have no "
                             "declared target list to check against")
    args = parser.parse_args()

    elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    print(f"elevated: {elevated}")
    start = time.perf_counter()
    checked, findings = sweep()
    if args.catalog_only:
        findings = [f for f in findings if f["kind"] == "catalog"]
    elapsed = time.perf_counter() - start

    hard = [f for f in findings if f["kind"] == "catalog"]
    soft = [f for f in findings if f["kind"] != "catalog"]

    print(f"\n{checked} scanners had something to read, in {elapsed:.1f}s")
    print(f"\n== DEFECTS: target exists with content, scanner found nothing "
          f"({len(hard)}) ==")
    for finding in hard:
        print(f"  {finding['scanner']}")
        for target in finding["live_targets"]:
            print(f"      live:    {target}")
        for target in finding.get("refused_targets", []):
            print(f"      refused: {target}")
    if not hard:
        print("  (none)")

    if not args.catalog_only:
        print(f"\n== worth a look: hand-written scanners that returned "
              f"nothing ({len(soft)}) ==")
        for finding in soft:
            detail = finding.get("error") or finding.get("note", "")
            print(f"  {finding['scanner']}: {detail}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"elevated": elevated, "checked": checked,
                       "findings": findings}, handle, indent=2)
        print(f"\nwrote {args.json}")

    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
