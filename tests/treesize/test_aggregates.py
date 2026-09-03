"""Spec 4.3: per-view aggregates."""

from modules.treesize.store.aggregates import (
    AGE_BUCKETS, AggregateCache, FILETIME_TICKS_PER_DAY, Row, by_age,
    by_extension, by_file_group, by_owner, extension_of, subtree_files,
    top_files,
)
from modules.treesize.store.node_store import (
    NodeStore, DIR, EXCLUDED, HARDLINK_DUP,
)
from modules.treesize.store.rollup import rollup

NOW = 140_000_000_000_000_000


def _tree():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    docs = s.add(root, "Docs", attrs=DIR)
    s.add(docs, "report.pdf", size=1000, alloc=1024,
          mtime=NOW - 2 * FILETIME_TICKS_PER_DAY, owner_id=s.intern_owner("alice"))
    s.add(docs, "notes.txt", size=200, alloc=256,
          mtime=NOW - 200 * FILETIME_TICKS_PER_DAY, owner_id=s.intern_owner("bob"))
    s.add(root, "movie.mkv", size=9000, alloc=9216,
          mtime=NOW - 10 * FILETIME_TICKS_PER_DAY, owner_id=s.intern_owner("alice"))
    s.add(root, "setup.exe", size=500, alloc=512,
          mtime=NOW, owner_id=s.intern_owner("alice"))
    s.add(root, "dropped.tmp", size=7777, attrs=EXCLUDED)
    s.add(root, "alias.mkv", size=0, attrs=HARDLINK_DUP)
    s.build_child_lists()
    rollup(s)
    return s, root


def test_extension_parsing():
    assert extension_of("report.pdf") == "pdf"
    assert extension_of("ARCHIVE.TAR.GZ") == "gz"
    assert extension_of("Makefile") == ""
    assert extension_of(".gitignore") == "", "a dotfile is a name, not an extension"
    assert extension_of("trailing.") == ""


def test_subtree_walk_skips_excluded_and_hardlink_aliases():
    s, root = _tree()
    names = {s.name(n) for n in subtree_files(s, root)}
    assert names == {"report.pdf", "notes.txt", "movie.mkv", "setup.exe"}


def test_subtree_walk_survives_a_deep_tree():
    """Iterative, for the same reason rollup is: 20k deep must not overflow."""
    s = NodeStore()
    node = s.add(-1, "C:", attrs=DIR)
    for i in range(20_000):
        node = s.add(node, f"d{i}", attrs=DIR)
    s.add(node, "leaf.bin", size=5)
    s.build_child_lists()
    assert len(list(subtree_files(s, 0))) == 1


def test_by_extension_is_sorted_largest_first():
    s, root = _tree()
    rows = by_extension(s, root)
    assert rows[0] == Row("mkv", 1, 9000, 9216)
    assert [r.label for r in rows] == ["mkv", "pdf", "exe", "txt"]


def test_by_file_group_uses_pros_groupings():
    s, root = _tree()
    groups = {r.label: r for r in by_file_group(s, root)}
    assert groups["Videos"].size == 9000
    assert groups["Documents"].count == 2, "pdf and txt are both Documents"
    assert groups["Programs"].size == 500


def test_unknown_extensions_land_in_other():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "thing.qqq", size=10)
    s.build_child_lists()
    assert by_file_group(s, root)[0].label == "Other"


def test_by_owner_groups_and_totals():
    s, root = _tree()
    owners = {r.label: r for r in by_owner(s, root)}
    assert owners["alice"].count == 3
    assert owners["alice"].size == 10500
    assert owners["bob"].count == 1


def test_by_age_buckets_chronologically_not_by_size():
    s, root = _tree()
    rows = by_age(s, root, NOW)
    assert [r.label for r in rows] == [label for label, _ in AGE_BUCKETS]
    by_label = {r.label: r for r in rows}
    # A file lands in the FIRST bucket it fits, so a 2-day-old file is "This
    # week" and never also "This month" -- the buckets partition, they do not
    # nest. Counting it in both would double the histogram's total.
    assert by_label["Today"].count == 1          # setup.exe, 0 days
    assert by_label["This week"].count == 1      # report.pdf, 2 days
    assert by_label["This month"].count == 1     # movie.mkv, 10 days
    assert by_label["This year"].count == 1      # notes.txt, 200 days
    assert sum(r.count for r in rows) == 4


def test_files_with_no_timestamp_land_in_the_oldest_bucket():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "nostamp.bin", size=5, mtime=0)
    s.build_child_lists()
    assert by_age(s, root, NOW)[-1].count == 1


def test_a_future_timestamp_does_not_crash_or_vanish():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "future.bin", size=5, mtime=NOW + 10 * FILETIME_TICKS_PER_DAY)
    s.build_child_lists()
    assert sum(r.count for r in by_age(s, root, NOW)) == 1


def test_top_files_is_bounded_and_ordered():
    s, root = _tree()
    top = top_files(s, root, limit=2)
    assert [s.name(n) for n, _ in top] == ["movie.mkv", "report.pdf"]


def test_top_files_limit_larger_than_the_tree_is_fine():
    s, root = _tree()
    assert len(top_files(s, root, limit=1000)) == 4


def test_aggregate_cache_recomputes_only_once():
    s, root = _tree()
    calls = []

    def compute(store, node):
        calls.append(node)
        return by_extension(store, node)

    cache = AggregateCache()
    cache.get(s, root, "ext", compute)
    cache.get(s, root, "ext", compute)
    assert len(calls) == 1


def test_aggregate_cache_does_not_serve_a_previous_scans_numbers():
    """Node indices repeat across scans; a node-only key would silently return
    the last scan's totals for this scan's folder."""
    first, root = _tree()
    cache = AggregateCache()
    assert cache.get(first, root, "ext", by_extension)[0].size == 9000

    second = NodeStore()
    r2 = second.add(-1, "C:", attrs=DIR)
    second.add(r2, "tiny.txt", size=1)
    second.build_child_lists()
    rollup(second)
    assert cache.get(second, r2, "ext", by_extension)[0].size == 1
