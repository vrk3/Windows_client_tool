import struct

from modules.treesize.scan.mft_reader import parse_mft_record
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_INDEX_ROOT,
    ATTR_REPARSE_POINT, ATTR_END, NS_WIN32, NS_DOS, FLAG_COMPRESSED, FLAG_SPARSE,
)
from modules.treesize.store.node_store import DIR, REPARSE, COMPRESSED, SPARSE, ADS
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)


def _rec(attrs: bytes, **kw):
    return build_record(attrs + struct.pack("<I", ATTR_END), **kw)


def test_parses_name_parent_and_size():
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info(ctime=10, mtime=20, atime=30))
             + resident_attr(ATTR_FILE_NAME, file_name("notepad.exe", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=1000, alloc_size=4096))
    r = parse_mft_record(_rec(attrs), 42, SECTOR)
    assert r.record_no == 42
    assert r.name == "notepad.exe"
    assert r.parent_ref == 5
    assert r.size == 1000
    assert r.alloc == 4096
    assert (r.ctime, r.mtime, r.atime) == (10, 20, 30)


def test_returns_none_for_deleted_record():
    attrs = resident_attr(ATTR_FILE_NAME, file_name("gone.txt", parent=5))
    assert parse_mft_record(_rec(attrs, in_use=False), 1, SECTOR) is None


def test_returns_none_for_non_file_signature():
    rec = _rec(resident_attr(ATTR_FILE_NAME, file_name("x", parent=5)))
    rec[0:4] = b"BAAD"
    assert parse_mft_record(rec, 1, SECTOR) is None


def test_prefers_win32_name_over_dos_alias():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("NOTEPA~1.EXE", parent=5, namespace=NS_DOS))
             + resident_attr(ATTR_FILE_NAME, file_name("notepad.exe", parent=5, namespace=NS_WIN32)))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.name == "notepad.exe"


def test_directory_flag_sets_dir():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("Windows", parent=5))
             + resident_attr(ATTR_INDEX_ROOT, b"\x00" * 16))
    r = parse_mft_record(_rec(attrs, is_dir=True), 1, SECTOR)
    assert r.flags & DIR


def test_resident_data_counts_toward_size():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("tiny.txt", parent=5))
             + resident_attr(ATTR_DATA, b"12345"))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.size == 5


def test_alternate_data_streams_add_to_size_and_set_flag():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("d.exe", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=1000, alloc_size=4096)
             + resident_attr(ATTR_DATA, b"abcdefgh", name="Zone.Identifier"))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.size == 1008
    assert r.flags & ADS


def test_compressed_stream_uses_compressed_size_for_alloc():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("c.dat", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=100_000, alloc_size=65_536,
                                flags=FLAG_COMPRESSED, compressed_size=32_768))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.size == 100_000
    assert r.alloc == 32_768
    assert r.flags & COMPRESSED


def test_sparse_stream_is_flagged():
    # The fixture, not the assertion, changed here. It used to put the real
    # cost in alloc_size, which is not where NTFS keeps it: for a sparse
    # attribute alloc_size is the logical VCN span and TotalAllocated is what
    # the volume actually gave up. The expectation is the same as it ever was.
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("s.dat", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=385_000, alloc_size=385_024,
                                flags=FLAG_SPARSE, compressed_size=4_096))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.size == 385_000
    assert r.alloc == 4_096
    assert r.flags & SPARSE


def test_reparse_point_is_flagged():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("junction", parent=5))
             + resident_attr(ATTR_REPARSE_POINT, b"\x00" * 12))
    r = parse_mft_record(_rec(attrs, is_dir=True), 1, SECTOR)
    assert r.flags & REPARSE


def test_extra_names_capture_hard_links():
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("first.txt", parent=5))
             + resident_attr(ATTR_FILE_NAME, file_name("second.txt", parent=9))
             + nonresident_attr(ATTR_DATA, data_size=64, alloc_size=4096))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.name == "first.txt"
    assert [(e.name, e.parent_ref) for e in r.extra_names] == [("second.txt", 9)]


def test_security_id_is_carried_through():
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info(security_id=256))
             + resident_attr(ATTR_FILE_NAME, file_name("a.txt", parent=5)))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.security_id == 256


def _truncated_nonresident_data() -> bytes:
    """A DATA attribute that claims to be non-resident in only 0x18 bytes."""
    body = bytearray(0x18)
    struct.pack_into("<II", body, 0x00, ATTR_DATA, 0x18)
    body[0x08] = 1
    return bytes(body)


def test_malformed_attribute_skips_the_record_instead_of_aborting_the_scan():
    """A torn record must cost one record, not the whole volume.

    The raw volume is read live with FILE_SHARE_WRITE and no snapshot, so
    records genuinely do change under the reader. Letting struct.error escape
    would abort a 460k-record scan on a single bad one.
    """
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("a.txt", parent=5))
             + _truncated_nonresident_data())
    assert parse_mft_record(_rec(attrs), 1, SECTOR) is None


def test_truncated_file_name_attribute_skips_the_record():
    assert parse_mft_record(_rec(resident_attr(ATTR_FILE_NAME, b"\x00" * 8)), 1, SECTOR) is None


def test_hidden_attribute_becomes_the_hidden_node_flag():
    """Without this, exclude_hidden is inert on the MFT engine."""
    from modules.treesize.store.node_store import HIDDEN
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info(dos_attrs=0x2))
             + resident_attr(ATTR_FILE_NAME, file_name("secret.txt", parent=5)))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.flags & HIDDEN


def test_a_plain_file_is_not_marked_hidden():
    from modules.treesize.store.node_store import HIDDEN
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info(dos_attrs=0x20))
             + resident_attr(ATTR_FILE_NAME, file_name("plain.txt", parent=5)))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert not (r.flags & HIDDEN)


def test_sparse_file_is_charged_its_real_allocation_not_its_span():
    """Spec 1.1: Pro reports C: as Size 385.4 GB against Allocated 147.5 GB.

    Charging a sparse file its full VCN span instead of TotalAllocated is what
    pushed our Allocated above Size, which is backwards for a volume with
    56,235 sparse files on it.
    """
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name("sparse.vhdx", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=1 << 30, alloc_size=1 << 30,
                                flags=FLAG_SPARSE, compressed_size=65536))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.size == 1 << 30
    assert r.alloc == 65536
    assert r.flags & SPARSE


def test_compressed_file_still_uses_its_compressed_size():
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name("packed.bin", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=100000, alloc_size=102400,
                                flags=FLAG_COMPRESSED, compressed_size=20480))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.alloc == 20480


def test_ordinary_file_still_uses_allocated_size():
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name("plain.bin", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=5000, alloc_size=8192))
    r = parse_mft_record(_rec(attrs), 1, SECTOR)
    assert r.alloc == 8192
