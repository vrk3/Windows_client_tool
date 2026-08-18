import struct

from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore
from modules.treesize.store.rollup import rollup
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
)
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024
INFO = VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=4096,
                  bytes_per_record=RECORD_SIZE, mft_start_lcn=0,
                  mft_valid_length=0, total_clusters=1000)


def _record(name, parent, size=0, is_dir=False, record_no=0):
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name(name, parent)))
    if not is_dir:
        attrs += nonresident_attr(ATTR_DATA, data_size=size, alloc_size=4096)
    return build_record(attrs + struct.pack("<I", ATTR_END),
                        is_dir=is_dir, size=RECORD_SIZE)


def _fake_mft(records: dict[int, bytearray]) -> bytes:
    """Lay records out at record_no * RECORD_SIZE, zero-filling the gaps."""
    highest = max(records) if records else 0
    buf = bytearray(RECORD_SIZE * (highest + 1))
    for no, rec in records.items():
        buf[no * RECORD_SIZE:(no + 1) * RECORD_SIZE] = rec
    return bytes(buf)


def _scan(records, **kw):
    image = _fake_mft(records)

    def reader(offset, length):
        return image[offset:offset + length]

    info = VolumeInfo(SECTOR, 4096, RECORD_SIZE, 0, len(image), 1000)
    store = NodeStore()
    scanner = MftScanner("C", info, reader=reader)
    count = scanner.scan(store, **kw)
    return store, scanner, count


def test_scans_records_into_a_tree():
    store, scanner, count = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        20: _record("Windows", ROOT_RECORD_NO, is_dir=True),
        21: _record("notepad.exe", 20, size=1000),
    })
    rollup(store)
    assert count == 3
    assert store.size[scanner.builder.root] == 1000


def test_zeroed_records_are_skipped():
    store, scanner, count = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        30: _record("a.txt", ROOT_RECORD_NO, size=10),
        # records 6..29 are zero-filled by _fake_mft
    })
    assert count == 2


def test_on_batch_receives_index_ranges():
    batches = []
    store, scanner, count = _scan(
        {ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
         20: _record("a.txt", ROOT_RECORD_NO, size=1),
         21: _record("b.txt", ROOT_RECORD_NO, size=2)},
        on_batch=batches.append, batch_size=1)
    assert batches
    assert batches[0][0] == 0
    assert batches[-1][1] == len(store)


def test_cancel_stops_early():
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1

    store, scanner, count = _scan(
        {ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
         20: _record("a.txt", ROOT_RECORD_NO, size=1),
         21: _record("b.txt", ROOT_RECORD_NO, size=2)},
        should_cancel=should_cancel, batch_size=1)
    assert count < 3


def test_wait_if_paused_is_called_between_chunks():
    seen = []
    _scan({ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
           20: _record("a.txt", ROOT_RECORD_NO, size=1)},
          wait_if_paused=lambda: seen.append(1), batch_size=1)
    assert seen
