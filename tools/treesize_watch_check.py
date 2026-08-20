"""Drive the REAL watcher against a real directory and print what happens.

Why this exists: "Watch for file system changes" shipped with 21 passing
tests and two independent fatal bugs. Every one of those tests injected a fake
change source, and every fake source *ended* -- which is exactly the property
`ReadDirectoryChangesW` does not have. It blocks. Both bugs were found in the
first minute of running this instead.

    .venv\\Scripts\\python.exe tools\\treesize_watch_check.py

Exits 1 if any step fails, so it can be run as a check rather than read.

Expected, on a 4096-byte cluster:

    grow    1000 ->  5000 B   alloc  4096 ->  8192
    create  +2000 B           files     1 ->     2, alloc 12288
    delete  -2000 B           both reversed

Check the numbers by hand. A plausible number that is wrong is the failure
mode this whole module has had, five times over.
"""
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.treesize.scan.walk_scanner import WalkScanner       # noqa: E402
from modules.treesize.scan.watcher import Watcher, apply_change  # noqa: E402
from modules.treesize.store.node_store import NodeStore          # noqa: E402
from modules.treesize.store.rollup import rollup                 # noqa: E402

CLUSTER = 4096
WAIT = 3.0

failures = []


def check(label, got, want):
    ok = got == want
    print(f"    {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        failures.append(label)


def main() -> int:
    root_dir = tempfile.mkdtemp(prefix="tswatch-")
    try:
        os.makedirs(os.path.join(root_dir, "sub"))
        with open(os.path.join(root_dir, "sub", "a.bin"), "wb") as handle:
            handle.write(b"x" * 1000)

        store = NodeStore()
        scanner = WalkScanner(root_dir, bytes_per_cluster=CLUSTER)
        scanner.scan(store)
        root = scanner.root
        store.build_child_lists()
        rollup(store)
        print(f"scanned: size={store.size[root]} alloc={store.alloc[root]} "
              f"files={store.file_count[root]}")

        batches = []
        arrived = threading.Event()

        def on_changes(batch):
            batches.append(batch)
            arrived.set()

        watcher = Watcher(root_dir, on_changes)      # the REAL source
        watcher.start()
        time.sleep(0.4)

        def step(label, act):
            batches.clear()
            arrived.clear()
            act()
            delivered = arrived.wait(WAIT)
            print(f"\n-- {label} --")
            check("delivered without a further change", delivered, True)
            total = 0
            for batch in batches:
                for change in batch:
                    applied = apply_change(store, root, change.path, CLUSTER)
                    total += applied.delta
                    print(f"    {os.path.relpath(change.path, root_dir)}  "
                          f"action={change.action}  delta={applied.delta}  "
                          f"structural={applied.structural}")
            return total

        new_file = os.path.join(root_dir, "sub", "new.bin")

        step("grow an existing file, then go quiet",
             lambda: open(os.path.join(root_dir, "sub", "a.bin"), "wb")
             .write(b"x" * 5000))
        check("size after grow", store.size[root], 5000)
        check("alloc after grow", store.alloc[root], 8192)

        step("create a new file",
             lambda: open(new_file, "wb").write(b"z" * 2000))
        check("size after create", store.size[root], 7000)
        check("alloc after create", store.alloc[root], 12288)
        check("files after create", store.file_count[root], 2)

        step("delete it again", lambda: os.remove(new_file))
        check("size after delete", store.size[root], 5000)
        check("alloc after delete", store.alloc[root], 8192)
        check("files after delete", store.file_count[root], 1)

        watcher.stop()
        check("watcher recorded no error", watcher.error, None)
    finally:
        shutil.rmtree(root_dir, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
