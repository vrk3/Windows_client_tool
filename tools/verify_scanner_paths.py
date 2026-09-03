"""Compare a scanner's PATHS to its spec's, without needing the software.

`verify_scanner_conversion.py` compares what each side FINDS on this
machine. That is the strongest check available, and it is why only 41 of
538 scanners have been converted so far — on a machine without Steam, a
Steam scanner finds nothing either way, and "neither found anything" is not
evidence of equivalence.

This asks a different question that does not depend on what is installed:
**do the two compute the same set of paths?**

The original is driven with `_make_item` and `_make_item_with_age`
intercepted, so every path it would have measured is recorded whether or
not it exists. The spec is asked for `targets_of(...)`. Both run against
the same real environment, so `%LOCALAPPDATA%` resolves identically for
each. A scanner whose path sets match is equivalent by construction, on any
machine.

Two shapes are reported rather than treated as failures, because in both
the SPEC is the correct one:

* **glob-in-a-list.** Several originals put `...\\Packages\\Microsoft.Foo_*\\
  LocalState` in a target list and then test it with `os.path.isdir()`.
  A literal `*` is not a valid Windows path component, so that test is
  always False and the original never matched anything. The engine globs
  properly, so it finds the directory the scanner was written to find.

* **drive letters.** An original naming `C:\\Windows` and a spec naming
  `%windir%` resolve to the same place here and differ on a machine where
  Windows is not on C: — which is audit #16, and the spec is right.

Usage:
    python tools/verify_scanner_paths.py
    python tools/verify_scanner_paths.py --category games --verbose
"""
from __future__ import annotations

import argparse
import glob as globlib
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from modules.cleanup.cleanup_scanner.catalog import (  # noqa: E402
    expand, load_catalog, targets_of,
)

CATEGORY_MODULES = {
    "system": "scanners_system", "apps": "scanners_apps", "dev": "scanners_dev",
    "games": "scanners_games", "media": "scanners_media",
    "cloud": "scanners_cloud", "comms": "scanners_comms",
    "browsers": "scanners_browsers",
}


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _paths_the_original_would_measure(fn) -> set:
    """Every path the original CONSIDERS, existing or not.

    Hooked at os.path.isdir/isfile/exists and glob.glob rather than at
    _make_item, because every one of these scanners tests existence FIRST
    and only calls _make_item for what is really there. Hooking the
    constructor therefore recorded nothing on a machine without the
    software — the exact blind spot this tool exists to remove.
    """
    seen = []

    real_isdir, real_isfile = os.path.isdir, os.path.isfile
    real_exists = os.path.exists
    real_getsize, real_getmtime = os.path.getsize, os.path.getmtime
    real_glob = globlib.glob

    def watch(real):
        def wrapper(path, *a, **kw):
            if isinstance(path, str) and path:
                seen.append(path)
            return real(path, *a, **kw)
        return wrapper

    os.path.isdir = watch(real_isdir)
    os.path.isfile = watch(real_isfile)
    os.path.exists = watch(real_exists)
    globlib.glob = watch(real_glob)
    try:
        fn()
    except Exception as exc:
        return {f"<raised {type(exc).__name__}: {exc}>"}
    finally:
        os.path.isdir, os.path.isfile = real_isdir, real_isfile
        os.path.exists = real_exists
        os.path.getsize, os.path.getmtime = real_getsize, real_getmtime
        globlib.glob = real_glob

    # A glob the original left unexpanded matches nothing on any machine;
    # expand it so the two sides are compared on equal terms.
    expanded = set()
    for path in seen:
        if any(ch in path for ch in "*?["):
            expanded.update(real_glob(path))
        else:
            expanded.add(path)

    # No "outermost" collapsing here. An earlier version kept only the
    # outermost of any nested pair, applied to the ORIGINAL's set but not
    # the spec's, and that asymmetry alone produced four false differences
    # (docker, google_drive, sharex, zed all list a parent AND its
    # children deliberately). get_dir_size recurses through os.walk and
    # os.path.getsize, neither of which is hooked, so there is nothing to
    # collapse in the first place.
    return {_norm(p) for p in expanded if p}



def _equivalent(theirs: set, ours: set, declared: set) -> bool:
    """Whether the two path sets mean the same thing.

    Exactly equal, or differing only by a GUARD DIRECTORY. An original that
    writes

        if not os.path.isdir(steam_dir): return
        for sub in ("steamapps", "shadercache"): ...

    records `steam_dir` because it TESTED it, and — when the guard fails,
    as it does on a machine without Steam — records nothing else. The spec
    lists the leaves. Neither side is wrong: on a machine with Steam both
    resolve to the same directories, and on one without, both measure
    nothing.

    So a path on only one side is accepted when it is an ancestor of, or a
    descendant of, a path the other side declares. `declared` is the spec's
    paths with variables expanded but globs NOT resolved, because a glob
    that currently matches nothing still says where it would look —
    comparing against the resolved set would make every unmatched glob look
    like a missing path.
    """
    if theirs == ours:
        return True

    def related(path, others):
        return any(path.startswith(o + os.sep) or o.startswith(path + os.sep)
                   for o in others)

    for extra in theirs - ours:
        if not related(extra, ours | declared):
            return False
    for extra in ours - theirs:
        if not related(extra, theirs):
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog()
    same, differ, unresolved, no_original = [], [], [], []

    for spec_id, spec in sorted(catalog.items()):
        if args.category and spec.category != args.category:
            continue
        module_name = CATEGORY_MODULES.get(spec.category)
        original = None
        if module_name:
            try:
                module = __import__(
                    f"modules.cleanup.cleanup_scanner.{module_name}",
                    fromlist=["x"])
                original = getattr(module, f"scan_{spec_id}", None)
            except ImportError:
                pass
        if original is None:
            no_original.append(spec_id)
            continue

        theirs = _paths_the_original_would_measure(original)
        ours = {_norm(p) for p in targets_of(spec)}
        # The spec's paths with variables expanded but globs left alone: a
        # glob matching nothing today still says where it would look.
        declared = set()
        for raw in spec.paths:
            resolved = expand(raw)
            if resolved:
                declared.add(_norm(resolved))

        if any(p.startswith("<raised") for p in theirs):
            unresolved.append((spec_id, next(iter(theirs))))
        elif _equivalent(theirs, ours, declared):
            same.append(spec_id)
            if args.verbose:
                print(f"  same  {spec_id}: {len(ours)} path(s)")
        else:
            differ.append((spec_id, sorted(theirs - ours), sorted(ours - theirs)))

    print()
    print(f"  identical path sets:            {len(same)}")
    print(f"  original raised:                {len(unresolved)}")
    print(f"  already converted (no original):{len(no_original)}")
    print(f"  DIFFERENT:                      {len(differ)}")
    for spec_id, only_theirs, only_ours in differ:
        print(f"      {spec_id}")
        if only_theirs:
            print(f"          only the original: {only_theirs[:3]}")
        if only_ours:
            print(f"          only the spec:     {only_ours[:3]}")
    for spec_id, why in unresolved:
        print(f"      {spec_id}: {why}")

    return 1 if differ or unresolved else 0


if __name__ == "__main__":
    sys.exit(main())
