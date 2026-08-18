from modules.treesize.store.node_store import NodeStore, DIR


def test_add_returns_sequential_indices():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    child = s.add(root, "Windows", size=100, attrs=DIR)
    assert (root, child) == (0, 1)
    assert len(s) == 2


def test_name_roundtrips_unicode():
    s = NodeStore()
    i = s.add(-1, "Ünïcödé — 文字")
    assert s.name(i) == "Ünïcödé — 文字"


def test_path_walks_parents():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    f = s.add(win, "notepad.exe", size=1024)
    assert s.path(f) == "C:\\Windows\\notepad.exe"


def test_size_and_alloc_are_independent():
    s = NodeStore()
    i = s.add(-1, "sparse.dat", size=385_000, alloc=4_096)
    assert s.size[i] == 385_000
    assert s.alloc[i] == 4_096


def test_owner_interning_dedupes():
    s = NodeStore()
    a = s.intern_owner("S-1-5-18")
    b = s.intern_owner("S-1-5-18")
    c = s.intern_owner("S-1-5-32-544")
    assert a == b
    assert a != c
    assert s.owner(c) == "S-1-5-32-544"


def test_build_child_lists_handles_out_of_order_parents():
    # MFT order gives no guarantee a parent is added before its child.
    s = NodeStore()
    child = s.add(2, "child.txt", size=5)   # parent index 2 does not exist yet
    root = s.add(-1, "C:", attrs=DIR)
    parent = s.add(root, "dir", attrs=DIR)
    assert (child, root, parent) == (0, 1, 2)
    s.build_child_lists()
    assert list(s.children(parent)) == [child]
    assert list(s.children(root)) == [parent]
    assert list(s.roots()) == [root]


def test_children_are_in_ascending_index_order():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    a = s.add(root, "a")
    b = s.add(root, "b")
    c = s.add(root, "c")
    s.build_child_lists()
    assert list(s.children(root)) == [a, b, c]
