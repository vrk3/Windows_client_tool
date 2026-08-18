import struct
import pytest

from modules.treesize.scan.ntfs_structs import (
    apply_fixup, FixupError, parse_record_header, iter_attributes,
    parse_attr_header, parse_standard_information, parse_file_name,
    decode_data_runs,
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
    NS_WIN32, NS_DOS, FLAG_COMPRESSED,
)

SECTOR = 512


def build_record(attributes: bytes, *, in_use=True, is_dir=False,
                 sequence=1, size=1024, usn=0xBEEF) -> bytearray:
    """Build a FILE record with a valid fixup array, as NTFS stores it."""
    rec = bytearray(size)
    attrs_off = 0x38
    rec[0:4] = b"FILE"
    struct.pack_into("<H", rec, 0x04, 0x30)          # usa offset
    n_sectors = size // SECTOR
    struct.pack_into("<H", rec, 0x06, n_sectors + 1)  # usa count = sectors + 1
    struct.pack_into("<H", rec, 0x10, sequence)
    struct.pack_into("<H", rec, 0x14, attrs_off)
    flags = (0x0001 if in_use else 0) | (0x0002 if is_dir else 0)
    struct.pack_into("<H", rec, 0x16, flags)
    rec[attrs_off:attrs_off + len(attributes)] = attributes
    # Fixup: stash each sector's real last two bytes into the USA, then
    # overwrite those positions with the USN, exactly as NTFS does on disk.
    struct.pack_into("<H", rec, 0x30, usn)
    for i in range(n_sectors):
        tail = (i + 1) * SECTOR - 2
        struct.pack_into("<H", rec, 0x32 + i * 2, struct.unpack_from("<H", rec, tail)[0])
        struct.pack_into("<H", rec, tail, usn)
    return rec


def resident_attr(type_id: int, value: bytes, *, name: str = "", flags: int = 0) -> bytes:
    name_b = name.encode("utf-16-le")
    header_len = 0x18 + len(name_b)
    pad = (-header_len) % 8
    value_off = header_len + pad
    total = value_off + len(value)
    total += (-total) % 8
    a = bytearray(total)
    struct.pack_into("<I", a, 0x00, type_id)
    struct.pack_into("<I", a, 0x04, total)
    a[0x08] = 0                                      # resident
    a[0x09] = len(name)
    struct.pack_into("<H", a, 0x0A, 0x18 if name else 0)
    struct.pack_into("<H", a, 0x0C, flags)
    struct.pack_into("<I", a, 0x10, len(value))
    struct.pack_into("<H", a, 0x14, value_off)
    a[0x18:0x18 + len(name_b)] = name_b
    a[value_off:value_off + len(value)] = value
    return bytes(a)


def nonresident_attr(type_id: int, *, data_size: int, alloc_size: int,
                     runs: bytes = b"\x00", flags: int = 0,
                     compressed_size: int = 0, name: str = "") -> bytes:
    name_b = name.encode("utf-16-le")
    has_comp = bool(flags & FLAG_COMPRESSED)
    runs_off = 0x48 if has_comp else 0x40
    runs_off += len(name_b)
    total = runs_off + len(runs)
    total += (-total) % 8
    a = bytearray(total)
    struct.pack_into("<I", a, 0x00, type_id)
    struct.pack_into("<I", a, 0x04, total)
    a[0x08] = 1                                      # non-resident
    a[0x09] = len(name)
    struct.pack_into("<H", a, 0x0A, 0x40 if name else 0)
    struct.pack_into("<H", a, 0x0C, flags)
    struct.pack_into("<Q", a, 0x10, 0)               # start VCN
    struct.pack_into("<Q", a, 0x18, 0)               # last VCN
    struct.pack_into("<H", a, 0x20, runs_off)
    struct.pack_into("<Q", a, 0x28, alloc_size)
    struct.pack_into("<Q", a, 0x30, data_size)
    struct.pack_into("<Q", a, 0x38, data_size)       # initialized size
    if has_comp:
        struct.pack_into("<Q", a, 0x40, compressed_size)
    if name_b:
        a[0x40 if not has_comp else 0x48:][:len(name_b)] = name_b
    a[runs_off:runs_off + len(runs)] = runs
    return bytes(a)


def std_info(ctime=1, mtime=2, atime=3, dos_attrs=0x20, security_id=7) -> bytes:
    v = bytearray(0x48)
    struct.pack_into("<Q", v, 0x00, ctime)
    struct.pack_into("<Q", v, 0x08, mtime)
    struct.pack_into("<Q", v, 0x18, atime)
    struct.pack_into("<I", v, 0x20, dos_attrs)
    struct.pack_into("<I", v, 0x34, security_id)
    return bytes(v)


def file_name(name: str, parent: int, *, namespace=NS_WIN32,
              parent_seq=1, real=100, alloc=4096) -> bytes:
    name_b = name.encode("utf-16-le")
    v = bytearray(0x42 + len(name_b))
    struct.pack_into("<Q", v, 0x00, (parent_seq << 48) | parent)
    struct.pack_into("<Q", v, 0x28, alloc)
    struct.pack_into("<Q", v, 0x30, real)
    v[0x40] = len(name)
    v[0x41] = namespace
    v[0x42:] = name_b
    return bytes(v)


# --- fixups ---

def test_apply_fixup_restores_sector_tails():
    attrs = resident_attr(ATTR_STANDARD_INFORMATION, std_info()) + struct.pack("<I", ATTR_END)
    rec = build_record(attrs)
    # Plant a known value at the first sector tail before fixups are applied.
    struct.pack_into("<H", rec, 0x32, 0x1234)
    apply_fixup(rec, SECTOR)
    assert struct.unpack_from("<H", rec, SECTOR - 2)[0] == 0x1234


def test_apply_fixup_rejects_usn_mismatch():
    rec = build_record(struct.pack("<I", ATTR_END))
    struct.pack_into("<H", rec, SECTOR - 2, 0xDEAD)   # corrupt a sector tail
    with pytest.raises(FixupError):
        apply_fixup(rec, SECTOR)


# --- header ---

def test_parse_record_header_reads_flags():
    rec = build_record(struct.pack("<I", ATTR_END), is_dir=True)
    apply_fixup(rec, SECTOR)
    h = parse_record_header(rec)
    assert h.in_use is True
    assert h.is_directory is True
    assert h.attrs_offset == 0x38


def test_parse_record_header_detects_deleted():
    rec = build_record(struct.pack("<I", ATTR_END), in_use=False)
    apply_fixup(rec, SECTOR)
    assert parse_record_header(rec).in_use is False


# --- attribute iteration ---

def test_iter_attributes_yields_each_and_stops_at_end_marker():
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name("a.txt", 5))
             + struct.pack("<I", ATTR_END))
    rec = build_record(attrs)
    apply_fixup(rec, SECTOR)
    types = [t for t, _ in iter_attributes(rec, 0x38)]
    assert types == [ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME]


def test_iter_attributes_stops_on_zero_length():
    # A zero-length attribute would otherwise loop forever.
    attrs = resident_attr(ATTR_DATA, b"x") + b"\x80\x00\x00\x00" + b"\x00" * 4
    rec = build_record(attrs)
    apply_fixup(rec, SECTOR)
    assert len(list(iter_attributes(rec, 0x38))) == 1


# --- attribute values ---

def test_resident_data_size_is_value_length():
    attr = resident_attr(ATTR_DATA, b"hello world")
    h = parse_attr_header(attr)
    assert h.non_resident is False
    assert h.data_size == 11


def test_nonresident_data_reports_real_and_allocated():
    attr = nonresident_attr(ATTR_DATA, data_size=385_000, alloc_size=147_456)
    h = parse_attr_header(attr)
    assert h.non_resident is True
    assert h.data_size == 385_000
    assert h.alloc_size == 147_456


def test_compressed_attr_exposes_compressed_size():
    attr = nonresident_attr(ATTR_DATA, data_size=100_000, alloc_size=65_536,
                            flags=FLAG_COMPRESSED, compressed_size=32_768)
    h = parse_attr_header(attr)
    assert h.flags & FLAG_COMPRESSED
    assert h.compressed_size == 32_768


def test_named_data_attribute_is_an_alternate_stream():
    attr = resident_attr(ATTR_DATA, b"ads", name="Zone.Identifier")
    h = parse_attr_header(attr)
    assert h.name == "Zone.Identifier"


def test_parse_standard_information():
    si = parse_standard_information(std_info(ctime=11, mtime=22, atime=33,
                                             dos_attrs=0x21, security_id=99))
    assert (si.ctime, si.mtime, si.atime) == (11, 22, 33)
    assert si.dos_attrs == 0x21
    assert si.security_id == 99


def test_parse_file_name_extracts_parent_and_namespace():
    fn = parse_file_name(file_name("notepad.exe", parent=5, parent_seq=3))
    assert fn.name == "notepad.exe"
    assert fn.parent_ref == 5
    assert fn.parent_seq == 3
    assert fn.namespace == NS_WIN32


def test_parse_file_name_marks_dos_namespace():
    fn = parse_file_name(file_name("NOTEPA~1.EXE", parent=5, namespace=NS_DOS))
    assert fn.namespace == NS_DOS


# --- data runs ---

def test_decode_single_run():
    # 0x21: 1 length byte, 2 offset bytes. length=0x08, lcn=0x0234
    assert decode_data_runs(bytes([0x21, 0x08, 0x34, 0x02, 0x00]), 0) == [(0x0234, 8)]


def test_decode_runs_are_relative_to_previous_lcn():
    data = bytes([0x21, 0x08, 0x00, 0x01,     # lcn 0x0100, len 8
                  0x21, 0x04, 0x10, 0x00,     # lcn += 0x0010 -> 0x0110, len 4
                  0x00])
    assert decode_data_runs(data, 0) == [(0x0100, 8), (0x0110, 4)]


def test_decode_runs_handles_negative_offset():
    # 0x11 0x08 0xF0 -> length 8, signed delta -16
    data = bytes([0x21, 0x08, 0x00, 0x01, 0x11, 0x08, 0xF0, 0x00])
    assert decode_data_runs(data, 0) == [(0x0100, 8), (0x00F0, 8)]


def test_decode_sparse_run_has_no_lcn():
    # offset size 0 means a sparse run: allocated length, no cluster
    data = bytes([0x01, 0x20, 0x00])
    assert decode_data_runs(data, 0) == [(None, 0x20)]


def test_decode_runs_stops_at_terminator():
    data = bytes([0x21, 0x08, 0x00, 0x01, 0x00, 0x21, 0xFF, 0xFF, 0xFF])
    assert decode_data_runs(data, 0) == [(0x0100, 8)]
