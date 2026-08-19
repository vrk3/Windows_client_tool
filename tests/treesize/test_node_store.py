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


def test_names_are_stored_utf8_not_utf16():
    """The blob dominates per-node cost, and Windows filenames are near-all ASCII.

    UTF-16-LE spent 2 bytes on every character regardless. Measured volume-wide
    on a real C: scan, the name blob was ~63 of 137 bytes/node.
    """
    s = NodeStore()
    s.add(-1, "notepad.exe")
    assert len(s.names) == len("notepad.exe")


def test_non_ascii_names_round_trip():
    s = NodeStore()
    names = ["Ordner", "Zürich.txt", "файл.bin", "日本語フォルダ", "emoji-🎵.mp3"]
    idx = [s.add(-1, n) for n in names]
    assert [s.name(i) for i in idx] == names


def test_astral_plane_name_round_trips():
    """A 4-byte UTF-8 character is 2 UTF-16 code units; name_len counts BYTES."""
    s = NodeStore()
    i = s.add(-1, "𝔘𝔫𝔦𝔠𝔬𝔡𝔢.txt")
    assert s.name(i) == "𝔘𝔫𝔦𝔠𝔬𝔡𝔢.txt"


def test_path_round_trips_non_ascii_components():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    sub = s.add(root, "Zürich", attrs=DIR)
    leaf = s.add(sub, "файл.bin")
    assert s.path(leaf) == "C:\\Zürich\\файл.bin"


def test_a_long_windows_name_fits_the_length_column():
    """name_len is 'H' (max 65,535). 255 chars of 4-byte UTF-8 is 1,020 bytes."""
    s = NodeStore()
    long_name = "𝔘" * 255
    i = s.add(-1, long_name)
    assert s.name_len[i] == 255 * 4
    assert s.name(i) == long_name
