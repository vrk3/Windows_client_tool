# tests/treesize/test_mft_tree.py
from modules.treesize.scan.mft_reader import MftTreeBuilder, ParsedRecord, NameRef
from modules.treesize.store.node_store import NodeStore, DIR, HARDLINK_DUP
from modules.treesize.store.rollup import rollup

ROOT_RECORD = 5   # NTFS always numbers the volume root directory 5


def _dir(no, name, parent, seq=1):
    return ParsedRecord(record_no=no, sequence=seq, base_ref=0, name=name,
                        parent_ref=parent, parent_seq=1, flags=DIR)


def _file(no, name, parent, size, alloc=4096, seq=1, extra=()):
    return ParsedRecord(record_no=no, sequence=seq, base_ref=0, name=name,
                        parent_ref=parent, parent_seq=1, size=size, alloc=alloc,
                        extra_names=list(extra))


def _build(records, **kw):
    store = NodeStore()
    b = MftTreeBuilder(store, **kw)
    for r in records:
        b.feed(r)
    b.finish()
    return store, b


def test_builds_tree_from_out_of_order_records():
    # The child arrives before its parent, as happens in MFT order.
    store, b = _build([
        _file(60, "notepad.exe", parent=40, size=1000),
        _dir(40, "Windows", parent=ROOT_RECORD),
        _dir(ROOT_RECORD, "", parent=ROOT_RECORD),
    ])
    rollup(store)
    assert store.path(b.root) == "C:"
    win = next(store.children(b.root))
    assert store.name(win) == "Windows"
    assert store.size[win] == 1000


def test_root_record_is_the_volume_root():
    store, b = _build([_dir(ROOT_RECORD, "", parent=ROOT_RECORD)],
                      volume_label="E:")
    assert store.name(b.root) == "E:"
    assert store.parent[b.root] == -1


def test_stale_sequence_number_goes_to_orphan_root():
    stale = _file(60, "ghost.txt", parent=40, size=10)
    stale.parent_seq = 99          # parent 40 has sequence 1
    store, b = _build([stale, _dir(40, "Windows", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    assert b.orphan_root is not None
    assert [store.name(c) for c in store.children(b.orphan_root)] == ["ghost.txt"]


def test_missing_parent_goes_to_orphan_root():
    store, b = _build([_file(60, "stray.txt", parent=1234, size=10),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    assert [store.name(c) for c in store.children(b.orphan_root)] == ["stray.txt"]


def test_hardlink_second_path_is_zero_sized_and_flagged():
    rec = _file(60, "first.txt", parent=40, size=1000,
                extra=[NameRef("second.txt", 41, 1)])
    store, b = _build([rec,
                       _dir(40, "A", parent=ROOT_RECORD),
                       _dir(41, "B", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    rollup(store)
    by_name = {store.name(i): i for i in range(len(store))}
    assert store.size[by_name["first.txt"]] == 1000
    assert store.size[by_name["second.txt"]] == 0
    assert store.attrs[by_name["second.txt"]] & HARDLINK_DUP
    assert store.size[b.root] == 1000      # counted once, not twice


def test_charge_all_hardlinks_option_counts_every_path():
    rec = _file(60, "first.txt", parent=40, size=1000,
                extra=[NameRef("second.txt", 41, 1)])
    store, b = _build([rec,
                       _dir(40, "A", parent=ROOT_RECORD),
                       _dir(41, "B", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)],
                      charge_all_hardlinks=True)
    rollup(store)
    assert store.size[b.root] == 2000


def test_system_metafiles_below_record_16_are_skipped():
    # $MFT (0), $LogFile (2) and friends are not user-visible files.
    store, b = _build([_file(0, "$MFT", parent=ROOT_RECORD, size=999_999),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    rollup(store)
    assert store.size[b.root] == 0
    assert "$MFT" not in [store.name(i) for i in range(len(store))]


def test_extension_records_are_ignored():
    # base_ref != 0 marks an $ATTRIBUTE_LIST extension record, not a file.
    ext = _file(61, "spill", parent=40, size=500)
    ext.base_ref = 60
    store, b = _build([ext, _dir(40, "W", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    rollup(store)
    assert store.size[b.root] == 0
