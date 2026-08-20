"""Drive the real pane with a REAL, LARGE scan and time everything.

    .venv\Scripts\python.exe tools\treesize_ui_scale_check.py [target] [outdir]

Defaults to C:\Windows. Exits 1 if anything fails or blows its budget.
Needs no display: it runs on the offscreen Qt platform.

The views, the treemap, sorting, search and the duplicate finder have only
ever been exercised with a handful of nodes. Sorting once lost its order on
expand, and size columns once sorted as text -- both found by looking at a
screenshot. This does the same at 243k nodes, and times it, because a view
that takes forty seconds is broken even when it is correct.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QModelIndex, Qt
from PyQt6.QtWidgets import QApplication

from modules.treesize.scan.walk_scanner import WalkScanner
from modules.treesize.store.node_store import NodeStore
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.shell import TreeSizeShell
from modules.treesize.ui.theme import apply_theme

TARGET = sys.argv[1] if len(sys.argv) > 1 else r"C:\Windows"
OUT = sys.argv[2] if len(sys.argv) > 2 else "."
failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{'' if ok else '  -> ' + detail}")
    if not ok:
        failures.append(label)


def timed(label, fn, budget):
    started = time.monotonic()
    result = fn()
    seconds = time.monotonic() - started
    ok = seconds <= budget
    print(f"  {'ok  ' if ok else 'SLOW'} {label:<34} {seconds:6.2f}s "
          f"(budget {budget}s)")
    if not ok:
        failures.append(f"{label} took {seconds:.1f}s")
    return result


app = QApplication([])

print(f"scanning {TARGET} ...")
store = NodeStore()
scanner = WalkScanner(TARGET, bytes_per_cluster=4096)
scanner.scan(store)
root = scanner.root
store.build_child_lists()
rollup(store)
print(f"  {len(store):,} nodes\n")


class VolumeInfo:
    bytes_per_cluster = 4096


class Result:
    pass


result = Result()
result.store, result.root = store, root
result.node_count, result.excluded, result.engine = len(store), 0, "walk"
result.volume_info, result.complete = VolumeInfo(), True
result.errors, result.error_count, result.elapsed = (), 0, 5.0

shell = TreeSizeShell()
apply_theme(shell)
shell.resize(1600, 950)

print("loading the scan into the pane:")
timed("show_result", lambda: shell.show_result(result), 8.0)
app.processEvents()

print("\npopulating every view:")
views = [("Chart", shell.chart), ("Details", shell.details),
         ("Extensions", shell.extensions), ("File groups", shell.file_groups),
         ("Users", shell.users), ("Age of Files", shell.ages),
         ("Top Files", shell.top_files)]
for name, widget in views:
    def switch(w=widget):
        shell.views.setCurrentWidget(w)
        app.processEvents()
    timed(f"view: {name}", switch, 15.0)

print("\nthe treemap at a real size:")
shell.views.setCurrentWidget(shell.chart)
shell.chart.treemap.resize(1100, 800)
timed("build_treemap", lambda: shell.chart.set_scan(store, root), 10.0)
rects = shell.chart.treemap._rects
check("treemap produced rectangles", len(rects) > 100, f"{len(rects)}")
grid = shell.chart.treemap._grid
hit = grid.hit(550.0, 400.0) if grid else None
check("hit testing finds something in the middle", hit is not None)

print("\nsorting the tree (the column that used to sort as TEXT):")
model = shell.directory_tree.tree_model
for order, label in ((Qt.SortOrder.DescendingOrder, "descending"),
                     (Qt.SortOrder.AscendingOrder, "ascending")):
    timed(f"sort by size, {label}",
          lambda o=order: model.sort(1, o), 5.0)

model.sort(1, Qt.SortOrder.DescendingOrder)
top = model.index(0, 0, QModelIndex())
kids = [model.index(r, 0, top) for r in range(min(30, model.rowCount(top)))]
sizes = [store.size[int(i.internalId()) - 1] for i in kids]
check("children sort by NUMBER, biggest first",
      sizes == sorted(sizes, reverse=True),
      f"{sizes[:6]}")

print("\nexpanding, which once lost the sort order:")
timed("expandToDepth(2)", lambda: shell.directory_tree.expandToDepth(2), 20.0)
top = model.index(0, 0, QModelIndex())
first = model.index(0, 0, top)
grand = [model.index(r, 0, first) for r in range(min(20, model.rowCount(first)))]
grand_sizes = [store.size[int(i.internalId()) - 1] for i in grand]
check("grandchildren are sorted too",
      grand_sizes == sorted(grand_sizes, reverse=True),
      f"{grand_sizes[:6]}")

print("\nsearch and duplicates at real scale:")
from modules.treesize.store import duplicates, search as store_search

hits = timed("search *.dll",
             lambda: store_search.search(store, root,
                                         store_search.Query(pattern="*.dll")),
             10.0)
check("search found .dll files", len(hits) > 0, f"{len(hits)}")

# 1 MB, which is what the UI's spinbox defaults to. The LIBRARY default is
# min_size=1 -- one byte -- and on this tree that is 172,540 files to hash
# against 4,341, so 160s against 15s. Timing the library default here once
# looked like a product defect and was purely an artefact of the harness.
groups = timed("duplicates (1 MB, the UI default)",
               lambda: duplicates.find_duplicates(store, root,
                                                  min_size=1024 ** 2), 60.0)
print(f"       ({len(groups):,} duplicate group(s))")

print("\nrendering:")
shell.views.setCurrentWidget(shell.chart)
shell.directory_tree.expandToDepth(1)
app.processEvents()
path = os.path.join(OUT, "pane-scale.png")
shell.grab().save(path)
print("  wrote", path)

print()
print("FAILED: " + "; ".join(failures) if failures else "All checks passed.")
raise SystemExit(1 if failures else 0)
