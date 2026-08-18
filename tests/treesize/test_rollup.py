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
