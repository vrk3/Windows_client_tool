"""Dump every security_reader `check_*` function's output, or diff two dumps.

Used to prove Task 3's snapshot rewrite did not change any reader's answer,
except where it was deliberately rewritten to carry an explicit `available`
flag (see task-3-brief.md Step 7). Run once against the pre-change source
(via a worktree -- `git stash` does not stash untracked files) and once
against the working tree, then compare.

Usage:
    python tools/reader_parity_check.py <out.json>
    python tools/reader_parity_check.py --compare <before.json> <after.json>
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _dump(out_path: str) -> None:
    from modules.security_dashboard import security_reader

    names = sorted(n for n in dir(security_reader) if n.startswith("check_"))
    results = {}
    start = time.perf_counter()
    for name in names:
        fn = getattr(security_reader, name)
        try:
            results[name] = fn()
        except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
            results[name] = {"__error__": f"{type(exc).__name__}: {exc}"}
    elapsed = time.perf_counter() - start
    payload = {
        "_elapsed_seconds": elapsed,
        "_count": len(names),
        "results": results,
    }
    Path(out_path).write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(f"wrote {len(names)} readers in {elapsed:.2f}s -> {out_path}")


def _compare(before_path: str, after_path: str) -> None:
    before_payload = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after_payload = json.loads(Path(after_path).read_text(encoding="utf-8"))
    before, after = before_payload["results"], after_payload["results"]
    names = sorted(set(before) | set(after))

    diffs = [name for name in names if before.get(name, "<missing>") != after.get(name, "<missing>")]

    print(
        f"before: {before_payload['_count']} readers in "
        f"{before_payload['_elapsed_seconds']:.2f}s"
    )
    print(
        f"after:  {after_payload['_count']} readers in "
        f"{after_payload['_elapsed_seconds']:.2f}s"
    )

    if not diffs:
        print("\nno differences")
        return

    print(f"\n{len(diffs)} readers differ:")
    for name in diffs:
        print(f"\n=== {name} ===")
        print(f"before: {before.get(name, '<missing>')}")
        print(f"after:  {after.get(name, '<missing>')}")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--compare":
        _compare(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 2:
        _dump(sys.argv[1])
    else:
        print(__doc__)
        sys.exit(1)
