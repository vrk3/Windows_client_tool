"""Filters on the MFT engine.

The walk engine drops filtered entries as it meets them, so an excluded
directory is simply never descended into. The MFT engine cannot do that:
records arrive in MFT order with no parent/child ordering guarantee, so
dropping a directory at feed time would leave its children unparented and
they would land under [Orphaned files] -- counted, and now misfiled, which is
worse than not filtering at all.

So filtering happens as a prune pass over the assembled tree, between
MftTreeBuilder.finish() and rollup().
"""
import struct

from modules.treesize.scan.filters import FilterSet
from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
)
from modules.treesize.scan.prune import prune_excluded
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore, DIR, HIDDEN, EXCLUDED
from modules.treesize.store.rollup import rollup
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024


def _record(name, parent, size=0, is_dir=False):
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name(name, parent)))
    if not is_dir:
        attrs += nonresident_attr(ATTR_DATA, data_size=size, alloc_size=size)
    return build_record(attrs + struct.pack("<I", ATTR_END),
                        is_dir=is_dir, size=RECORD_SIZE)


def _scan(records, filters=None):
    highest = max(records)
    image = bytearray(RECORD_SIZE * (highest + 1))
    for no, rec in records.items():
        image[no * RECORD_SIZE:(no + 1) * RECORD_SIZE] = rec
    info = VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=4096,
                      bytes_per_record=RECORD_SIZE, mft_start_lcn=0,
                      mft_valid_length=len(image), total_clusters=1000)
    store = NodeStore()
    scanner = MftScanner("C", info, reader=lambda o, n: bytes(image[o:o + n]))
    scanner.scan(store)
    root = scanner.builder.root
    if filters is not None:
        prune_excluded(store, root, filters)
    rollup(store)
    return store, root


def test_no_filters_leaves_every_node_counted():
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("keep.bin", ROOT_RECORD_NO, size=1000),
    }, filters=FilterSet())
    assert store.size[root] == 1000
    assert store.file_count[root] == 1


def test_glob_excludes_a_file_from_the_totals():
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("keep.bin", ROOT_RECORD_NO, size=1000),
        18: _record("drop.tmp", ROOT_RECORD_NO, size=5000),
    }, filters=FilterSet(exclude_globs=("*.tmp",)))
    assert store.size[root] == 1000
    assert store.file_count[root] == 1


def test_excluding_a_directory_takes_its_whole_subtree():
    """The case the walk engine gets for free and this pass must earn."""
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("keep.bin", ROOT_RECORD_NO, size=1000),
        18: _record("node_modules", ROOT_RECORD_NO, is_dir=True),
        19: _record("huge.bin", 18, size=9000),
        20: _record("nested", 18, is_dir=True),
        21: _record("deeper.bin", 20, size=7000),
    }, filters=FilterSet(exclude_globs=("node_modules",)))
    assert store.size[root] == 1000
    assert store.file_count[root] == 1
    assert store.folder_count[root] == 0


def test_min_size_never_excludes_a_directory():
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("Docs", ROOT_RECORD_NO, is_dir=True),
        18: _record("big.bin", 17, size=5000),
    }, filters=FilterSet(min_size=1000))
    assert store.size[root] == 5000
    assert store.folder_count[root] == 1


def test_the_root_itself_is_never_excluded():
    """Excluding the thing you asked to scan is never what was meant."""
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("keep.bin", ROOT_RECORD_NO, size=1000),
    }, filters=FilterSet(exclude_globs=("C:", "*")))
    assert not (store.attrs[root] & EXCLUDED)
    assert store.size[root] == 0


def test_excluded_count_matches_the_nodes_actually_dropped():
    filters = FilterSet(exclude_globs=("*.tmp",))
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("a.tmp", ROOT_RECORD_NO, size=1),
        18: _record("b.tmp", ROOT_RECORD_NO, size=1),
        19: _record("c.txt", ROOT_RECORD_NO, size=1),
    }, filters=filters)
    assert filters.excluded_count == 2


def test_a_pruned_subtree_counts_once_not_per_node():
    """An excluded folder is one exclusion, not one per descendant."""
    filters = FilterSet(exclude_globs=("junk",))
    _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("junk", ROOT_RECORD_NO, is_dir=True),
        18: _record("x.bin", 17, size=1),
        19: _record("y.bin", 17, size=1),
    }, filters=filters)
    assert filters.excluded_count == 1


def test_prune_marks_nodes_with_the_excluded_flag():
    store, root = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("drop.tmp", ROOT_RECORD_NO, size=5000),
    }, filters=FilterSet(exclude_globs=("*.tmp",)))
    dropped = [i for i in range(len(store)) if store.name(i) == "drop.tmp"]
    assert dropped and all(store.attrs[i] & EXCLUDED for i in dropped)


def test_rollup_ignores_excluded_nodes_even_without_a_prune_pass():
    """The flag is what rollup honours, so it works however it got set."""
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "counted.bin", size=100)
    s.add(root, "ignored.bin", size=900, attrs=EXCLUDED)
    s.build_child_lists()
    rollup(s)
    assert s.size[root] == 100
    assert s.file_count[root] == 1


def test_hidden_exclusion_works_on_the_mft_path():
    """parse_mft_record must carry the hidden bit for this to mean anything."""
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "visible.bin", size=100)
    s.add(root, "secret.bin", size=900, attrs=HIDDEN)
    s.build_child_lists()
    prune_excluded(s, root, FilterSet(exclude_hidden=True))
    rollup(s)
    assert s.size[root] == 100
