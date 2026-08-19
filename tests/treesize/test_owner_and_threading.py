"""Review findings 8 and 9.

8: `owner_id` must mean ONE thing. It is an index into the store's interned
   owner table. The MFT path used to jam a raw NTFS $Secure security id into
   the same column, so `store.owner(node)` was reading an unrelated integer as
   a list index -- silent only because the table happened to be empty.

9: `FilterSet.excluded_count` is mutated from `excludes()`, which the deferred
   walk-threading work will call from several threads at once.
"""
import struct
import threading

from modules.treesize.scan.filters import FilterSet
from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
)
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024


def _record(name, parent, security_id=7, is_dir=False):
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION,
                           std_info(security_id=security_id))
             + resident_attr(ATTR_FILE_NAME, file_name(name, parent)))
    if not is_dir:
        attrs += nonresident_attr(ATTR_DATA, data_size=10, alloc_size=10)
    return build_record(attrs + struct.pack("<I", ATTR_END),
                        is_dir=is_dir, size=RECORD_SIZE)


def _scan(records):
    highest = max(records)
    image = bytearray(RECORD_SIZE * (highest + 1))
    for no, rec in records.items():
        image[no * RECORD_SIZE:(no + 1) * RECORD_SIZE] = rec
    info = VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=4096,
                      bytes_per_record=RECORD_SIZE, mft_start_lcn=0,
                      mft_valid_length=len(image), total_clusters=1000)
    store = NodeStore()
    MftScanner("C", info, reader=lambda o, n: bytes(image[o:o + n])).scan(store)
    return store


def test_owner_id_is_an_index_into_the_owner_table():
    """The invariant: owner(owner_id[node]) must round-trip, on every path."""
    store = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("a.bin", ROOT_RECORD_NO, security_id=256),
    })
    node = next(i for i in range(len(store)) if store.name(i) == "a.bin")
    owner_id = store.owner_id[node]
    assert 0 <= owner_id < len(store._owners)
    assert store.owner(owner_id) != ""
    assert "256" in store.owner(owner_id)


def test_two_files_sharing_a_security_id_share_one_owner_entry():
    store = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("a.bin", ROOT_RECORD_NO, security_id=256),
        18: _record("b.bin", ROOT_RECORD_NO, security_id=256),
        19: _record("c.bin", ROOT_RECORD_NO, security_id=999),
    })
    ids = {store.name(i): store.owner_id[i] for i in range(len(store))}
    assert ids["a.bin"] == ids["b.bin"]
    assert ids["a.bin"] != ids["c.bin"]


def test_unresolved_owners_are_marked_as_such():
    """Phase 3 replaces these entries with real account names in place, so the
    marker must be obvious and every node's owner_id must stay valid."""
    store = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        17: _record("a.bin", ROOT_RECORD_NO, security_id=42),
    })
    node = next(i for i in range(len(store)) if store.name(i) == "a.bin")
    assert store.owner(store.owner_id[node]).startswith("$SECURE:")


def test_excluded_count_is_exact_under_concurrent_callers():
    """Ten threads, a thousand exclusions each; the total must be 10,000.

    A bare `self.excluded_count += 1` is a read-modify-write and can lose
    updates. This is the shape the deferred walk-threading work will create.
    """
    f = FilterSet(exclude_globs=("*.tmp",))
    errors = []

    def worker():
        try:
            for _ in range(1000):
                f.excludes("x.tmp", 1, 0)
        except Exception as exc:            # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert f.excluded_count == 10_000


def test_reset_is_safe_alongside_the_counter():
    f = FilterSet(exclude_globs=("*.tmp",))
    f.excludes("a.tmp", 1, 0)
    f.reset()
    assert f.excluded_count == 0
