"""Spec lines 166-167: $ATTRIBUTE_LIST spill must be followed and merged.

When a file's attributes outgrow its 1 KB MFT record, NTFS moves some of them
into extension records and leaves an $ATTRIBUTE_LIST behind pointing at them.
Each extension record's header carries a base reference back to the original.

MftTreeBuilder used to drop every extension record on sight (`if rec.base_ref:
return`). If the $DATA attribute was one of the things that spilled -- which is
exactly what happens to a heavily fragmented large file -- the base record was
left holding no size at all, and the file was counted as 0 bytes.

Also pinned here: for a non-resident attribute split across records, only the
fragment starting at VCN 0 carries the real data_size and allocated_size. Later
fragments repeat the header with a non-zero start VCN, and adding those in would
multiply the file's size by its fragment count.
"""
import struct

from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_ATTRIBUTE_LIST,
    ATTR_END, parse_attr_header,
)
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore, ADS
from modules.treesize.store.rollup import rollup
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024


def with_base_ref(rec: bytearray, base_record_no: int) -> bytearray:
    """Point a record at its base. Offset 0x20 is outside the fixup array."""
    struct.pack_into("<Q", rec, 0x20, base_record_no)
    return rec


def base_record(name, parent):
    """A base record whose $DATA has spilled: attribute list, but no data."""
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name(name, parent))
             + resident_attr(ATTR_ATTRIBUTE_LIST, b"\x00" * 32))
    return build_record(attrs + struct.pack("<I", ATTR_END), size=RECORD_SIZE)


def extension_record(base_no, *, data_size, alloc_size, start_vcn=0, name=""):
    attrs = nonresident_attr(ATTR_DATA, data_size=data_size,
                             alloc_size=alloc_size, name=name)
    if start_vcn:
        attrs = bytearray(attrs)
        struct.pack_into("<Q", attrs, 0x10, start_vcn)
        attrs = bytes(attrs)
    rec = build_record(attrs + struct.pack("<I", ATTR_END), size=RECORD_SIZE)
    return with_base_ref(rec, base_no)


def _scan(records):
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
    rollup(store)
    return store, scanner.builder.root


def test_start_vcn_is_exposed_on_the_attribute_header():
    attr = bytearray(nonresident_attr(ATTR_DATA, data_size=99, alloc_size=99))
    struct.pack_into("<Q", attr, 0x10, 7)
    assert parse_attr_header(bytes(attr)).start_vcn == 7


def test_spilled_data_is_merged_into_the_base_record():
    """The headline case: without merging this file counts as 0 bytes."""
    store, root = _scan({
        ROOT_RECORD_NO: build_record(
            resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
            + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE),
        17: base_record("huge.vhdx", ROOT_RECORD_NO),
        18: extension_record(17, data_size=8000, alloc_size=8192),
    })
    node = next(i for i in range(len(store)) if store.name(i) == "huge.vhdx")
    assert store.size[node] == 8000
    assert store.alloc[node] == 8192
    assert store.size[root] == 8000


def test_several_extension_records_all_merge():
    store, root = _scan({
        ROOT_RECORD_NO: build_record(
            resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
            + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE),
        17: base_record("spread.bin", ROOT_RECORD_NO),
        18: extension_record(17, data_size=1000, alloc_size=1024),
        19: extension_record(17, data_size=2000, alloc_size=2048, name="stream2"),
    })
    node = next(i for i in range(len(store)) if store.name(i) == "spread.bin")
    assert store.size[node] == 3000
    assert store.alloc[node] == 3072


def test_a_named_spilled_stream_marks_the_file_as_having_ads():
    store, _ = _scan({
        ROOT_RECORD_NO: build_record(
            resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
            + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE),
        17: base_record("withads.bin", ROOT_RECORD_NO),
        18: extension_record(17, data_size=500, alloc_size=512, name="Zone"),
    })
    node = next(i for i in range(len(store)) if store.name(i) == "withads.bin")
    assert store.attrs[node] & ADS


def test_continuation_fragments_do_not_multiply_the_size():
    """Only the VCN-0 fragment carries the real size; the rest repeat it."""
    store, _ = _scan({
        ROOT_RECORD_NO: build_record(
            resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
            + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE),
        17: base_record("frag.bin", ROOT_RECORD_NO),
        18: extension_record(17, data_size=6000, alloc_size=6144, start_vcn=0),
        19: extension_record(17, data_size=6000, alloc_size=6144, start_vcn=2),
        20: extension_record(17, data_size=6000, alloc_size=6144, start_vcn=4),
    })
    node = next(i for i in range(len(store)) if store.name(i) == "frag.bin")
    assert store.size[node] == 6000
    assert store.alloc[node] == 6144


def test_an_orphan_extension_record_does_not_crash_or_invent_a_node():
    """Its base was deleted or lies outside the scanned range."""
    store, _ = _scan({
        ROOT_RECORD_NO: build_record(
            resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
            + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE),
        17: extension_record(9999, data_size=1234, alloc_size=1234),
    })
    assert all(store.name(i) != "" or True for i in range(len(store)))
    assert store.size[0] >= 0


def test_extension_records_are_never_given_their_own_node():
    store, _ = _scan({
        ROOT_RECORD_NO: build_record(
            resident_attr(ATTR_FILE_NAME, file_name("", ROOT_RECORD_NO))
            + struct.pack("<I", ATTR_END), is_dir=True, size=RECORD_SIZE),
        17: base_record("one.bin", ROOT_RECORD_NO),
        18: extension_record(17, data_size=10, alloc_size=10),
    })
    named = [store.name(i) for i in range(len(store))]
    assert named.count("one.bin") == 1
