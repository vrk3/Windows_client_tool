"""Spec 4.4: saved scans, snapshots and diffing."""
import struct

import pytest

from modules.treesize.store import compare, scan_file
from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
from modules.treesize.store.rollup import rollup
from modules.treesize.store.scan_file import ScanFileError, ScanHeader, load, save


def _store(entries=(("Windows", 0, True), ("big.bin", 1000, False))):
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    owner = s.intern_owner("alice")
    for name, size, is_dir in entries:
        s.add(root, name, size=size, alloc=size,
              attrs=DIR if is_dir else 0, owner_id=owner, mtime=1234567)
    s.build_child_lists()
    rollup(s)
    return s, root


# ---- round trip ---------------------------------------------------------

def test_a_saved_scan_reloads_identically(tmp_path):
    store, root = _store()
    path = str(tmp_path / "scan.tss")
    save(path, store, root,
         ScanHeader(target="C:", engine="mft", bytes_per_cluster=4096))
    back, back_root, header = load(path)

    assert back_root == root
    assert len(back) == len(store)
    assert header.target == "C:"
    assert header.engine == "mft"
    assert header.bytes_per_cluster == 4096
    for node in range(len(store)):
        assert back.name(node) == store.name(node)
        assert back.size[node] == store.size[node]
        assert back.alloc[node] == store.alloc[node]
        assert back.attrs[node] == store.attrs[node]
        assert back.mtime[node] == store.mtime[node]


def test_rolled_up_totals_survive_the_round_trip(tmp_path):
    store, root = _store()
    path = str(tmp_path / "scan.tss")
    save(path, store, root, ScanHeader())
    back, back_root, _ = load(path)
    assert back.size[back_root] == store.size[root]
    assert back.file_count[back_root] == store.file_count[root]


def test_owner_table_survives(tmp_path):
    store, root = _store()
    path = str(tmp_path / "scan.tss")
    save(path, store, root, ScanHeader())
    back, _, _ = load(path)
    assert back.owner(back.owner_id[1]) == "alice"


def test_child_navigation_works_after_loading(tmp_path):
    store, root = _store()
    path = str(tmp_path / "scan.tss")
    save(path, store, root, ScanHeader())
    back, back_root, _ = load(path)
    assert ([back.name(c) for c in back.children(back_root)]
            == [store.name(c) for c in store.children(root)])


def test_saving_does_not_mutate_the_live_store(tmp_path):
    """Columns are byteswapped for the file; the store must not be."""
    store, root = _store()
    before = list(store.size)
    save(str(tmp_path / "scan.tss"), store, root, ScanHeader())
    assert list(store.size) == before


def test_non_ascii_names_round_trip(tmp_path):
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    names = ["Zürich.txt", "файл.bin",
             "日本語", "emoji-\U0001f3b5.mp3"]
    for name in names:
        s.add(root, name, size=10)
    s.build_child_lists()
    rollup(s)
    path = str(tmp_path / "u.tss")
    save(path, s, root, ScanHeader())
    back, back_root, _ = load(path)
    assert {back.name(c) for c in back.children(back_root)} == set(names)


# ---- rejecting bad files ------------------------------------------------

def test_a_file_that_is_not_a_scan_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"just some text, definitely not a scan")
    with pytest.raises(ScanFileError, match="not a TreeSize scan file"):
        load(str(path))


def test_an_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.tss"
    path.write_bytes(b"")
    with pytest.raises(ScanFileError):
        load(str(path))


def test_a_newer_format_is_refused_with_a_useful_message(tmp_path):
    store, root = _store()
    path = tmp_path / "future.tss"
    save(str(path), store, root, ScanHeader())
    raw = bytearray(path.read_bytes())
    struct.pack_into("<H", raw, len(scan_file.MAGIC), scan_file.FORMAT_VERSION + 1)
    path.write_bytes(bytes(raw))
    with pytest.raises(ScanFileError, match="newer version"):
        load(str(path))


def test_a_corrupt_body_is_reported_not_crashed(tmp_path):
    store, root = _store()
    path = tmp_path / "bad.tss"
    save(str(path), store, root, ScanHeader())
    raw = bytearray(path.read_bytes())
    raw[-20:] = b"\x00" * 20
    path.write_bytes(bytes(raw))
    with pytest.raises(ScanFileError, match="corrupt"):
        load(str(path))


# ---- diffing ------------------------------------------------------------

def _two_scans():
    old = NodeStore()
    old_root = old.add(-1, "C:", attrs=DIR)
    old.add(old_root, "keep.bin", size=100)
    old.add(old_root, "shrinks.bin", size=900)
    old.add(old_root, "vanishes.bin", size=500)
    old.build_child_lists()
    rollup(old)

    new = NodeStore()
    new_root = new.add(-1, "C:", attrs=DIR)
    new.add(new_root, "keep.bin", size=100)
    new.add(new_root, "shrinks.bin", size=300)
    new.add(new_root, "appears.bin", size=2000)
    new.build_child_lists()
    rollup(new)
    return old, old_root, new, new_root


def test_diff_matches_by_name_not_index():
    """Indices are assigned in scan order and mean nothing across two scans."""
    old, old_root, new, new_root = _two_scans()
    delta = compare.diff(old, old_root, new, new_root)
    by_name = {d.name: d for d in delta.children}
    assert by_name["keep.bin"].change == 0
    assert by_name["shrinks.bin"].change == -600
    assert by_name["appears.bin"].change == 2000
    assert by_name["vanishes.bin"].change == -500


def test_status_classifies_each_change():
    old, old_root, new, new_root = _two_scans()
    by_name = {d.name: d
               for d in compare.diff(old, old_root, new, new_root).children}
    assert by_name["appears.bin"].status == "added"
    assert by_name["vanishes.bin"].status == "removed"
    assert by_name["shrinks.bin"].status == "shrunk"
    assert by_name["keep.bin"].status == "unchanged"


def test_the_root_carries_the_overall_change():
    old, old_root, new, new_root = _two_scans()
    delta = compare.diff(old, old_root, new, new_root)
    assert delta.old_size == 1500
    assert delta.new_size == 2400
    assert delta.change == 900


def test_flatten_orders_by_magnitude_not_by_size():
    """A 40 GB folder that did not budge is not the answer to what moved."""
    old, old_root, new, new_root = _two_scans()
    rows = compare.flatten(compare.diff(old, old_root, new, new_root))
    assert rows[0].name == "appears.bin"
    assert [r.name for r in rows] == ["appears.bin", "shrinks.bin", "vanishes.bin"]
    assert all(r.change != 0 for r in rows)


def test_diff_ignores_excluded_nodes():
    old, old_root, new, new_root = _two_scans()
    new.attrs[3] |= EXCLUDED                      # appears.bin
    names = {d.name for d in compare.diff(old, old_root, new, new_root).children}
    assert "appears.bin" not in names


def test_diff_recurses_into_folders():
    old = NodeStore()
    old_root = old.add(-1, "C:", attrs=DIR)
    old_docs = old.add(old_root, "Docs", attrs=DIR)
    old.add(old_docs, "a.bin", size=100)
    old.build_child_lists()
    rollup(old)

    new = NodeStore()
    new_root = new.add(-1, "C:", attrs=DIR)
    new_docs = new.add(new_root, "Docs", attrs=DIR)
    new.add(new_docs, "a.bin", size=700)
    new.build_child_lists()
    rollup(new)

    delta = compare.diff(old, old_root, new, new_root)
    docs = delta.children[0]
    assert docs.name == "Docs"
    assert docs.change == 600
    assert docs.children[0].name == "a.bin"
    assert docs.children[0].change == 600


def test_summary_counts_each_kind_of_change():
    old, old_root, new, new_root = _two_scans()
    text = compare.summarise(compare.diff(old, old_root, new, new_root))
    assert "1 added" in text
    assert "1 removed" in text
    assert "1 shrunk" in text


def test_comparing_a_scan_with_itself_reports_no_change():
    old, old_root, _, _ = _two_scans()
    delta = compare.diff(old, old_root, old, old_root)
    assert delta.change == 0
    assert compare.flatten(delta) == []


# ---- scale --------------------------------------------------------------

def test_a_large_store_round_trips_intact(tmp_path):
    """Every other test here uses a handful of nodes.

    The format carries hundreds of thousands in real use, with a name blob in
    the tens of megabytes, and it had never been asked to. What breaks at that
    size and not at five nodes: an array typecode that is too narrow, a length
    prefix that overflows, an offset column that quietly transposes. A saved
    scan that reloads WRONG is the worst failure this format has available,
    because nothing about it looks like a failure.

    Deliberately kept to ~40k nodes so the suite stays quick;
    `tools/treesize_scanfile_check.py` does the same thing against a real
    quarter-million-node scan of the Windows directory.
    """
    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    folders = [store.add(root, f"folder-{i:04d}", attrs=DIR) for i in range(200)]
    for index, folder in enumerate(folders):
        for j in range(200):
            store.add(folder, f"file-{index:04d}-{j:04d}-\u00e9\u4e2d.bin",
                      size=index * 1000 + j, alloc=(index * 1000 + j + 4095)
                      // 4096 * 4096, mtime=133_000_000_000_000_000 + j)
    store.build_child_lists()
    rollup(store)
    assert len(store) > 40_000
    # ~960 KB: a blob measured in megabytes, not the handful of bytes
    # every other test in this file uses.
    assert len(store.names) > 900_000

    path = str(tmp_path / "big.tsscan")
    scan_file.save(path, store, root, scan_file.ScanHeader(target="C:"))
    loaded, loaded_root, _header = scan_file.load(path)

    assert len(loaded) == len(store)
    assert loaded_root == root
    for name, _typecode in scan_file.COLUMNS:
        assert list(getattr(loaded, name)) == list(getattr(store, name)), name
    assert bytes(loaded.names) == bytes(store.names)
    # Names as STRINGS, not just bytes: the blob can match while name_off and
    # name_len are transposed against each other.
    assert loaded.name(len(store) - 1) == store.name(len(store) - 1)
    assert loaded.size[loaded_root] == store.size[root]
    assert loaded.file_count[loaded_root] == store.file_count[root]
