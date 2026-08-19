import sys
from modules.treesize.store.node_store import NodeStore, DIR, HARDLINK_DUP
from modules.treesize.store.rollup import rollup, compute_depths


def _tree():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    s.add(win, "notepad.exe", size=1000, alloc=4096)
    s.add(win, "regedit.exe", size=2000, alloc=4096)
    users = s.add(root, "Users", attrs=DIR)
    s.add(users, "profile.dat", size=500, alloc=512)
    s.build_child_lists()
    return s, root, win, users


def test_rollup_sums_sizes_bottom_up():
    s, root, win, users = _tree()
    rollup(s)
    assert s.size[win] == 3000
    assert s.size[users] == 500
    assert s.size[root] == 3500


def test_rollup_sums_alloc_independently_of_size():
    s, root, win, users = _tree()
    rollup(s)
    assert s.alloc[win] == 8192
    assert s.alloc[root] == 8704


def test_rollup_counts_files_and_folders_in_subtree():
    s, root, win, users = _tree()
    rollup(s)
    assert (s.file_count[win], s.folder_count[win]) == (2, 0)
    assert (s.file_count[root], s.folder_count[root]) == (3, 2)


def test_rollup_handles_parent_added_after_child():
    s = NodeStore()
    leaf = s.add(1, "leaf.txt", size=7)   # parent not yet added
    folder = s.add(2, "folder", attrs=DIR)
    root = s.add(-1, "C:", attrs=DIR)
    s.build_child_lists()
    rollup(s)
    assert s.size[folder] == 7
    assert s.size[root] == 7
    assert s.file_count[root] == 1
    assert s.folder_count[root] == 1
    assert leaf == 0


def test_hardlink_duplicates_contribute_no_size():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "real.bin", size=1000, alloc=1024)
    s.add(root, "link.bin", size=0, alloc=0, attrs=HARDLINK_DUP)
    s.build_child_lists()
    rollup(s)
    assert s.size[root] == 1000


def test_deep_chain_does_not_recurse():
    # 20k-deep chain would blow a recursive implementation's stack.
    depth = 20_000
    s = NodeStore()
    prev = s.add(-1, "C:", attrs=DIR)
    for i in range(depth):
        prev = s.add(prev, f"d{i}", attrs=DIR)
    s.add(prev, "leaf.txt", size=42)
    s.build_child_lists()
    assert sys.getrecursionlimit() < depth
    rollup(s)
    assert s.size[0] == 42
    assert s.folder_count[0] == depth


def test_compute_depths_assigns_zero_to_roots():
    s, root, win, users = _tree()
    d = compute_depths(s)
    assert d[root] == 0
    assert d[win] == 1
    assert d[users] == 1


def test_2cycle_terminates_and_preserves_normal_tree():
    """Corrupt parent links forming a 2-cycle should not hang and should
    leave normal roots unaffected in rollup."""
    s = NodeStore()
    # Create a 2-cycle: node 0 <-> node 1
    x = s.add(-1, "x", attrs=DIR)      # node 0, parent=-1
    y = s.add(-1, "y", attrs=DIR)      # node 1, parent=-1
    # Corrupt to form cycle: 0 -> 1 -> 0
    s.parent[x] = y
    s.parent[y] = x
    # Add a normal root with a file
    root = s.add(-1, "C:", attrs=DIR)  # node 2
    s.add(root, "file.txt", size=100)
    s.build_child_lists()
    # This should return without hanging
    rollup(s)
    # Normal root should have correct total
    assert s.size[root] == 100


def test_3cycle_compute_depths_terminates():
    """A 3-node cycle should not hang and each node should get a depth >= 0."""
    s = NodeStore()
    a = s.add(-1, "a", attrs=DIR)      # node 0
    b = s.add(-1, "b", attrs=DIR)      # node 1
    c = s.add(-1, "c", attrs=DIR)      # node 2
    # Create cycle: a->b->c->a
    s.parent[a] = b
    s.parent[b] = c
    s.parent[c] = a
    s.build_child_lists()
    # This should return without hanging
    d = compute_depths(s)
    # All nodes should have non-negative depth
    assert d[a] >= 0
    assert d[b] >= 0
    assert d[c] >= 0


def test_empty_store():
    """Both rollup and compute_depths should handle empty store gracefully."""
    s = NodeStore()
    s.build_child_lists()
    # These should not raise and should return sensibly
    d = compute_depths(s)
    assert len(d) == 0
    rollup(s)
    assert len(s) == 0


def test_hardlink_duplicates_are_not_counted_as_extra_files():
    """A hardlink alias is another NAME for a file already counted, not a new file.

    WinSxS is dense with hardlinks, so counting each alias inflates the file
    total well above what the volume actually holds.
    """
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "real.bin", size=1000, alloc=1024)
    s.add(root, "link.bin", size=0, alloc=0, attrs=HARDLINK_DUP)
    s.build_child_lists()
    rollup(s)
    assert s.size[root] == 1000
    assert s.file_count[root] == 1


def test_charged_hardlinks_still_count_once():
    """charge_all_hardlinks omits the flag, so both names carry size AND count."""
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "real.bin", size=1000, alloc=1024)
    s.add(root, "link.bin", size=1000, alloc=1024)
    s.build_child_lists()
    rollup(s)
    assert s.size[root] == 2000
    assert s.file_count[root] == 2
