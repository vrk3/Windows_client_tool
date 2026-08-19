"""Review finding 5: the $MFT is not always one contiguous run.

MftScanner used to read mft_offset .. mft_offset+mft_valid_length as a single
linear span. On a fragmented $MFT that span holds other files' clusters, whose
bytes fail the FILE magic check and are skipped -- so the scan quietly MISSES
every file recorded past the first extent, and reports a smaller volume with no
error. These tests pin the run-list behaviour that replaces that assumption.
"""
import struct

from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
)
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore
from modules.treesize.store.rollup import rollup
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024
CLUSTER = 4096
# Each extent is 8 clusters = 32 records, so every extent comfortably spans
# FIRST_USER_RECORD (16). Records below that are $MFT, $LogFile and friends and
# are skipped by the builder by design, so a test file placed there would be
# dropped for a reason that has nothing to do with fragmentation.
CLUSTERS_PER_EXTENT = 8
RECORDS_PER_EXTENT = CLUSTERS_PER_EXTENT * (CLUSTER // RECORD_SIZE)


def encode_runs(runs: list[tuple[int, int]]) -> bytes:
    """Encode (lcn, cluster_count) pairs the way NTFS stores a run list.

    Offsets are signed deltas against the previous run's LCN, which is the
    detail that makes a hand-written run list easy to get wrong.
    """
    out = bytearray()
    prev = 0
    for lcn, count in runs:
        delta = lcn - prev
        prev = lcn
        len_b = count.to_bytes((max(count.bit_length(), 1) + 8) // 8, "little")
        size = max((delta.bit_length() + 8) // 8, 1)
        off_b = delta.to_bytes(size, "little", signed=True)
        out.append((len(off_b) << 4) | len(len_b))
        out += len_b
        out += off_b
    out.append(0)
    return bytes(out)


def mft_record_zero(runs: list[tuple[int, int]], data_size: int) -> bytearray:
    """Record 0 is $MFT's own record; its DATA run list locates the whole table."""
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name("$MFT", parent=ROOT_RECORD_NO))
             + nonresident_attr(ATTR_DATA, data_size=data_size, alloc_size=data_size,
                                runs=encode_runs(runs)))
    return build_record(attrs + struct.pack("<I", ATTR_END), size=RECORD_SIZE)


def file_record(name, parent, size=0, is_dir=False):
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name(name, parent)))
    if not is_dir:
        attrs += nonresident_attr(ATTR_DATA, data_size=size, alloc_size=size)
    return build_record(attrs + struct.pack("<I", ATTR_END),
                        is_dir=is_dir, size=RECORD_SIZE)


def build_fragmented_volume(extent_lcns, records):
    """A sparse 'volume' holding an MFT split across the given clusters.

    `records` maps LOGICAL record number -> record bytes. Logical numbering is
    what parent references use, and it runs continuously across extents even
    though the bytes are scattered -- which is precisely what a physical-offset
    calculation gets wrong.
    """
    volume = bytearray((max(extent_lcns) + CLUSTERS_PER_EXTENT + 1) * CLUSTER)
    for logical, rec in records.items():
        extent_index = logical // RECORDS_PER_EXTENT
        within = logical % RECORDS_PER_EXTENT
        base = extent_lcns[extent_index] * CLUSTER + within * RECORD_SIZE
        volume[base:base + RECORD_SIZE] = rec
    return bytes(volume)


def scan_fragmented(extent_lcns, records):
    runs = [(lcn, CLUSTERS_PER_EXTENT) for lcn in extent_lcns]
    total_bytes = len(extent_lcns) * CLUSTERS_PER_EXTENT * CLUSTER
    records = dict(records)
    records[0] = mft_record_zero(runs, total_bytes)
    volume = build_fragmented_volume(extent_lcns, records)

    info = VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=CLUSTER,
                      bytes_per_record=RECORD_SIZE,
                      mft_start_lcn=extent_lcns[0],
                      mft_valid_length=total_bytes,
                      total_clusters=len(volume) // CLUSTER)
    store = NodeStore()
    scanner = MftScanner("C", info, reader=lambda o, n: volume[o:o + n])
    scanner.scan(store)
    return store, scanner


def test_records_in_the_second_extent_are_found():
    """The whole point: a file recorded past the first extent must not vanish."""
    store, scanner = scan_fragmented(
        [10, 100],
        {
            ROOT_RECORD_NO: file_record("", ROOT_RECORD_NO, is_dir=True),
            17: file_record("in-first-extent.bin", ROOT_RECORD_NO, size=1000),
            40: file_record("in-second-extent.bin", ROOT_RECORD_NO, size=2000),
        },
    )
    rollup(store)
    names = {store.name(i) for i in range(len(store))}
    assert "in-first-extent.bin" in names
    assert "in-second-extent.bin" in names
    assert store.size[scanner.builder.root] == 3000


def test_logical_record_numbers_survive_the_extent_gap():
    """Parent refs are logical record numbers, so a directory in extent one
    must still adopt a child recorded in extent two."""
    store, scanner = scan_fragmented(
        [10, 100],
        {
            ROOT_RECORD_NO: file_record("", ROOT_RECORD_NO, is_dir=True),
            20: file_record("Docs", ROOT_RECORD_NO, is_dir=True),
            48: file_record("deep.bin", 20, size=4096),
        },
    )
    rollup(store)
    by_name = {store.name(i): i for i in range(len(store))}
    assert store.parent[by_name["deep.bin"]] == by_name["Docs"]
    assert store.size[by_name["Docs"]] == 4096


def test_a_three_extent_mft_is_followed_to_the_end():
    store, scanner = scan_fragmented(
        [10, 50, 90],
        {
            ROOT_RECORD_NO: file_record("", ROOT_RECORD_NO, is_dir=True),
            17: file_record("a.bin", ROOT_RECORD_NO, size=100),
            40: file_record("b.bin", ROOT_RECORD_NO, size=200),
            70: file_record("c.bin", ROOT_RECORD_NO, size=400),
        },
    )
    rollup(store)
    assert store.size[scanner.builder.root] == 700
    assert scanner.truncated is False


def test_fragmented_scan_reports_the_extents_it_followed():
    _, scanner = scan_fragmented(
        [10, 100],
        {ROOT_RECORD_NO: file_record("", ROOT_RECORD_NO, is_dir=True)},
    )
    assert len(scanner.extents) == 2
    assert scanner.extents[0][0] == 10 * CLUSTER
    assert scanner.extents[1][0] == 100 * CLUSTER


def test_unreadable_record_zero_falls_back_to_one_linear_span():
    """No run list available is not an error -- it is the old behaviour."""
    info = VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=CLUSTER,
                      bytes_per_record=RECORD_SIZE, mft_start_lcn=0,
                      mft_valid_length=RECORD_SIZE * 20, total_clusters=100)
    image = bytearray(RECORD_SIZE * 20)
    image[0:RECORD_SIZE] = bytes(RECORD_SIZE)          # record 0 is not a FILE record
    image[RECORD_SIZE * 5:RECORD_SIZE * 6] = file_record("", ROOT_RECORD_NO, is_dir=True)
    image[RECORD_SIZE * 17:RECORD_SIZE * 18] = file_record("solo.bin", ROOT_RECORD_NO, size=64)
    store = NodeStore()
    scanner = MftScanner("C", info, reader=lambda o, n: bytes(image[o:o + n]))
    scanner.scan(store)
    assert len(scanner.extents) == 1
    assert {store.name(i) for i in range(len(store))} >= {"solo.bin"}
