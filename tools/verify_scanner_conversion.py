"""Prove each generated ScannerSpec matches the function it replaces.

Runs the hand-written `scan_x()` and the generated spec side by side against
THIS machine and compares what each found — the set of paths, and the total
size. A conversion that is merely plausible is not good enough: these
scanners feed a delete button.

Run before deleting any hand-written scanner:

    python tools/verify_scanner_conversion.py
    python tools/verify_scanner_conversion.py --category system --verbose

Exits 1 if any converted scanner disagrees with its original.
"""
from __future__ import annotations

import argparse
import os
import sys

# Scanner paths carry real filenames, which carry characters cp1252
# cannot encode. Without this the report dies with UnicodeEncodeError
# partway through printing its own findings — audit #08, met in the
# wild while writing this file.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from modules.cleanup.cleanup_scanner import _common  # noqa: E402
from modules.cleanup.cleanup_scanner.catalog import (  # noqa: E402
    load_catalog, run_spec,
)


def _paths(result) -> set:
    return {os.path.normcase(os.path.normpath(i.path)) for i in result.items}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", help="check only this definitions file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog()
    agree, differ, absent, unchecked = [], [], [], []

    for spec_id, spec in sorted(catalog.items()):
        if args.category and spec.category != args.category:
            continue

        # The hand-written original, wherever it still lives.
        original = None
        for module_name in (f"scanners_{spec.category}", "scanners_system"):
            try:
                mod = __import__(
                    f"modules.cleanup.cleanup_scanner.{module_name}",
                    fromlist=["x"])
            except ImportError:
                continue
            original = getattr(mod, f"scan_{spec_id}", None)
            if original is not None:
                break

        if original is None:
            unchecked.append(spec_id)
            continue

        try:
            old = original()
        except Exception as exc:  # the original itself is broken
            differ.append((spec_id, f"original raised: {exc}"))
            continue

        new = run_spec(spec)
        old_paths, new_paths = _paths(old), _paths(new)

        if old_paths == new_paths and old.total_size == new.total_size:
            (absent if not old_paths else agree).append(spec_id)
            if args.verbose and old_paths:
                print(f"  ok    {spec_id}: {len(old_paths)} path(s), "
                      f"{_common.format_size(old.total_size)}")
        else:
            only_old = sorted(old_paths - new_paths)
            only_new = sorted(new_paths - old_paths)
            detail = []
            if only_old:
                detail.append(f"original found {only_old}")
            if only_new:
                detail.append(f"spec found {only_new}")
            if old.total_size != new.total_size and not (only_old or only_new):
                detail.append(f"size {old.total_size} vs {new.total_size}")
            differ.append((spec_id, "; ".join(detail)))

    print()
    print(f"  agree (both found the same paths):   {len(agree)}")
    print(f"  agree (neither found anything here): {len(absent)}")
    print(f"  no original left to compare against: {len(unchecked)}")
    print(f"  DISAGREE:                            {len(differ)}")
    for spec_id, why in differ:
        print(f"      {spec_id}: {why}")

    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
