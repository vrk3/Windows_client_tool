"""Round-trip a REAL, LARGE scan through the saved-scan format.

    .venv\Scripts\python.exe tools\treesize_scanfile_check.py [target]

Defaults to C:\Windows. Exits 1 on any mismatch.

Every existing test uses a handful of nodes. The format has never carried a
real store: hundreds of thousands of nodes and a name blob in the tens of
megabytes. If it loses or transposes anything at that size, a user's saved
scan or snapshot is silently wrong, which is the worst failure this format
has available to it.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.treesize.scan.walk_scanner import WalkScanner
from modules.treesize.store import scan_file
from modules.treesize.store.node_store import NodeStore
from modules.treesize.store.rollup import rollup

TARGET = sys.argv[1] if len(sys.argv) > 1 else r"C:\Windows"

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{'' if ok else '  ' + detail}")
    if not ok:
        failures.append(label)


print(f"scanning {TARGET} ...")
started = time.monotonic()
store = NodeStore()
scanner = WalkScanner(TARGET, bytes_per_cluster=4096)
scanner.scan(store)
root = scanner.root
store.build_child_lists()
rollup(store)
print(f"  {len(store):,} nodes, {store.size[root]:,} bytes, "
      f"name blob {len(store.names) / 1e6:.1f} MB, "
      f"{time.monotonic() - started:.1f}s")

if len(store) < 50_000:
    print("WARNING: that is not a large store; results prove little.")

path = os.path.join(tempfile.mkdtemp(prefix="tsscale-"), "big.tsscan")
header = scan_file.ScanHeader(target=TARGET, engine="walk",
                              bytes_per_cluster=4096)

started = time.monotonic()
scan_file.save(path, store, root, header)
save_seconds = time.monotonic() - started
on_disk = os.path.getsize(path)

started = time.monotonic()
loaded, loaded_root, loaded_header = scan_file.load(path)
load_seconds = time.monotonic() - started

raw = sum(getattr(store, name).itemsize * len(store)
          for name, _t in scan_file.COLUMNS) + len(store.names)
print(f"\nsaved {on_disk / 1e6:.1f} MB in {save_seconds:.2f}s "
      f"(raw {raw / 1e6:.1f} MB, {on_disk / raw:.0%} of it); "
      f"loaded in {load_seconds:.2f}s")

print("\ncomparing every column element by element:")
check("node count", len(loaded) == len(store),
      f"{len(loaded)} != {len(store)}")
check("root index", loaded_root == root, f"{loaded_root} != {root}")
check("name blob bytes", bytes(loaded.names) == bytes(store.names))

for name, _typecode in scan_file.COLUMNS:
    before = getattr(store, name)
    after = getattr(loaded, name)
    same = len(before) == len(after) and all(
        a == b for a, b in zip(before, after))
    detail = ""
    if not same:
        for i, (a, b) in enumerate(zip(before, after)):
            if a != b:
                detail = f"first difference at {i}: {a} != {b}"
                break
        else:
            detail = f"length {len(before)} != {len(after)}"
    check(f"column {name}", same, detail)

check("owner table", loaded._owners == store._owners)
check("header target", loaded_header.target == TARGET)
check("header cluster size", loaded_header.bytes_per_cluster == 4096)
check("rolled-up root size", loaded.size[loaded_root] == store.size[root])
check("rolled-up file count",
      loaded.file_count[loaded_root] == store.file_count[root])

# Names must survive as STRINGS, not just as bytes -- the blob comparison
# above would pass even if name_off/name_len were transposed.
mismatch = next((i for i in range(len(store))
                 if loaded.name(i) != store.name(i)), None)
check("every name decodes identically", mismatch is None,
      f"node {mismatch}" if mismatch is not None else "")

# And the tree has to still be navigable, not merely present.
deepest = max(range(len(store)), key=lambda i: len(store.path(i)))
check("deepest path reconstructs", loaded.path(deepest) == store.path(deepest),
      f"{loaded.path(deepest)!r} != {store.path(deepest)!r}")

os.remove(path)
print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("All checks passed.")
