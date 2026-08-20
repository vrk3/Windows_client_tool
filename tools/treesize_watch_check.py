"""Drive the REAL watcher against a real directory and print what happens.

Why this exists: "Watch for file system changes" shipped with 21 passing
tests and two independent fatal bugs. Every one of those tests injected a fake
change source, and every fake source *ended* -- which is exactly the property
`ReadDirectoryChangesW` does not have. It blocks. Both bugs were found in the
first minute of running this instead.

    .venv\\Scripts\\python.exe tools\\treesize_watch_check.py
    .venv\\Scripts\\python.exe tools\\treesize_watch_check.py --engine-only

Two phases. The ENGINE phase drives Watcher and apply_change directly. The
SHELL phase drives the other half -- watcher thread, `_changes_seen` signal,
`_on_watched_changes`, `refresh_structure()` -- and checks that a created file
actually becomes a row in the model and a deleted one actually leaves it.
Both halves had to be checked separately; the engine being right says nothing
about whether the model was ever told.

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


def engine_phase() -> None:
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


def _pump(app, seconds: float) -> None:
    """Run the Qt loop for real time, so queued signals get delivered.

    The watcher fires from its own thread and the shell consumes it through a
    signal, so nothing at all happens without an event loop turning.
    """
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def shell_phase() -> None:
    """The Qt half: does the MODEL end up showing the change?"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtCore import QModelIndex
    from PyQt6.QtWidgets import QApplication

    from modules.treesize.ui.shell import TreeSizeShell

    app = QApplication.instance() or QApplication([])
    target = tempfile.mkdtemp(prefix="tsshell-")
    try:
        with open(os.path.join(target, "existing.bin"), "wb") as handle:
            handle.write(b"x" * 1000)

        store = NodeStore()
        scanner = WalkScanner(target, bytes_per_cluster=CLUSTER)
        scanner.scan(store)
        root = scanner.root
        store.build_child_lists()
        rollup(store)

        class VolumeInfo:
            bytes_per_cluster = CLUSTER

        class Result:
            pass

        result = Result()
        result.store, result.root = store, root
        result.node_count, result.excluded, result.engine = len(store), 0, "walk"
        result.volume_info, result.complete = VolumeInfo(), True
        result.errors, result.error_count, result.elapsed = (), 0, 0.1

        shell = TreeSizeShell()
        shell.resize(1200, 800)
        shell.show_result(result)
        shell.path_combo.setEditText(target)

        def rows():
            model = shell.directory_tree.tree_model
            root_index = model.index(0, 0, QModelIndex())
            return [str(model.data(model.index(r, 0, root_index), 0))
                    for r in range(model.rowCount(root_index))]

        shell.set_watching(True)
        _pump(app, 0.5)
        check("watcher running",
              shell._watcher is not None and shell._watcher.running, True)

        print("\n-- create a file in the watched folder --")
        with open(os.path.join(target, "brand-new.bin"), "wb") as handle:
            handle.write(b"z" * 3000)
        _pump(app, 2.5)
        print(f"    rows: {rows()}")
        check("the new file is a row in the model",
              any("brand-new.bin" in r for r in rows()), True)
        check("root size after create", store.size[root], 4000)
        check("root files after create", store.file_count[root], 2)

        print("\n-- delete it again --")
        os.remove(os.path.join(target, "brand-new.bin"))
        _pump(app, 2.5)
        print(f"    rows: {rows()}")
        check("the deleted file left the model",
              any("brand-new.bin" in r for r in rows()), False)
        check("root size after delete", store.size[root], 1000)
        check("root files after delete", store.file_count[root], 1)

        shell.set_watching(False)
        _pump(app, 0.3)
        check("watcher stopped", shell._watcher, None)
    finally:
        shutil.rmtree(target, ignore_errors=True)


def main() -> int:
    print("=== ENGINE: Watcher + apply_change ===")
    engine_phase()
    if "--engine-only" not in sys.argv:
        print("\n=== SHELL: signal -> _on_watched_changes -> the model ===")
        shell_phase()

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
