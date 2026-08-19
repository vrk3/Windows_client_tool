"""Spec 3.4: "Batching: 500 nodes or 100 ms elapsed, whichever comes first.
A purely count-based batch stalls the UI on slow network scans."

Both scanners were count-only. On a slow target -- a network share, a spun-down
disk -- a directory can take longer than the UI's patience to yield 500 nodes,
and the tree would sit frozen with no rows even though the scan was progressing
normally. The time bound is what keeps the UI fed when the count bound cannot.
"""
import itertools
import struct

from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO, BATCH_INTERVAL
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
)
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.scan.walk_scanner import WalkScanner
from modules.treesize.store.node_store import NodeStore
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024


def test_batch_interval_is_the_spec_value():
    assert BATCH_INTERVAL == 0.1


def test_walk_emits_a_batch_on_time_even_below_the_count(tmp_path):
    """A few directories and a batch_size of 500: the count bound can never be
    reached, so every batch here is time-driven. Several directories, because
    the walk evaluates the bound once per directory -- a single-directory tree
    has only one iteration and nothing to emit early."""
    for d in range(3):
        sub = tmp_path / f"d{d}"
        sub.mkdir()
        (sub / "f.bin").write_bytes(b"x" * 10)

    # An ALWAYS-ADVANCING clock: a constant one reads as zero elapsed, since
    # the scanner measures now-minus-batch-open rather than an absolute time.
    ticks = itertools.count(0, 10)
    seen = []
    scanner = WalkScanner(str(tmp_path), clock=lambda: next(ticks))
    scanner.scan(NodeStore(), on_batch=seen.append, batch_size=500)
    assert len(seen) >= 2, "expected a time-driven batch before the final flush"


def test_walk_does_not_emit_early_when_the_clock_has_not_moved(tmp_path):
    for d in range(3):
        sub = tmp_path / f"d{d}"
        sub.mkdir()
        (sub / "f.bin").write_bytes(b"x" * 10)
    seen = []
    scanner = WalkScanner(str(tmp_path), clock=lambda: 0.0)
    scanner.scan(NodeStore(), on_batch=seen.append, batch_size=500)
    assert len(seen) == 1, "only the final flush should fire"


def _mft_image(count):
    records = {ROOT_RECORD_NO: build_record(
        resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
        + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE)}
    for i in range(count):
        attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
                 + resident_attr(ATTR_FILE_NAME, file_name(f"f{i}.bin", ROOT_RECORD_NO))
                 + nonresident_attr(ATTR_DATA, data_size=10, alloc_size=10))
        records[16 + i + 1] = build_record(attrs + struct.pack("<I", ATTR_END),
                                           size=RECORD_SIZE)
    highest = max(records)
    image = bytearray(RECORD_SIZE * (highest + 1))
    for no, rec in records.items():
        image[no * RECORD_SIZE:(no + 1) * RECORD_SIZE] = rec
    return bytes(image)


def _info(image):
    return VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=4096,
                      bytes_per_record=RECORD_SIZE, mft_start_lcn=0,
                      mft_valid_length=len(image), total_clusters=1000)


def test_mft_emits_a_batch_on_time_even_below_the_count():
    image = _mft_image(5)
    ticks = iter([0.0] + [99.0] * 40)
    seen = []
    scanner = MftScanner("C", _info(image), reader=lambda o, n: image[o:o + n],
                         clock=lambda: next(ticks, 99.0))
    scanner.scan(NodeStore(), on_batch=seen.append, batch_size=500)
    assert len(seen) >= 2


def test_mft_does_not_emit_early_when_the_clock_has_not_moved():
    image = _mft_image(5)
    seen = []
    scanner = MftScanner("C", _info(image), reader=lambda o, n: image[o:o + n],
                         clock=lambda: 0.0)
    scanner.scan(NodeStore(), on_batch=seen.append, batch_size=500)
    assert len(seen) == 1


def test_batches_never_overlap_or_leave_a_gap(tmp_path):
    """Whatever triggers a batch, the ranges must tile the store exactly --
    the main thread turns each one into beginInsertRows/endInsertRows."""
    for i in range(25):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * 10)
    ticks = iter([0.0, 99.0, 0.0, 99.0, 0.0, 99.0])
    seen = []
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), clock=lambda: next(ticks, 99.0))
    scanner.scan(store, on_batch=seen.append, batch_size=4)
    assert seen[0][0] == 1, "the root is added before batching starts"
    for (_, end), (start, _) in zip(seen, seen[1:]):
        assert end == start
    assert seen[-1][1] == len(store)
