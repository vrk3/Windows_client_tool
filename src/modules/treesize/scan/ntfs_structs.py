"""Byte-level NTFS parsing.

Every function here takes bytes and returns plain data, so the whole module
is testable without a volume handle or elevation.
"""
import struct
from dataclasses import dataclass
from typing import Iterator, NamedTuple

ATTR_STANDARD_INFORMATION = 0x10
ATTR_ATTRIBUTE_LIST = 0x20
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
ATTR_INDEX_ROOT = 0x90
ATTR_REPARSE_POINT = 0xC0
ATTR_END = 0xFFFFFFFF

NS_POSIX = 0
NS_WIN32 = 1
NS_DOS = 2
NS_WIN32_DOS = 3

FLAG_COMPRESSED = 0x0001
FLAG_ENCRYPTED = 0x4000
FLAG_SPARSE = 0x8000

FILE_RECORD_MAGIC = b"FILE"


class FixupError(ValueError):
    """A record's sector tail did not match its update sequence number."""


def apply_fixup(record: bytearray, bytes_per_sector: int) -> None:
    """Restore sector tails clobbered by the update sequence array.

    NTFS overwrites the last two bytes of every sector in a record with the
    USN and stashes the real bytes in the update sequence array. Failing to
    reverse this corrupts any field near a sector boundary -- silently, which
    is why a mismatch raises rather than being ignored.
    """
    usa_off, usa_count = struct.unpack_from("<HH", record, 0x04)
    if usa_count == 0:
        return
    usn = bytes(record[usa_off:usa_off + 2])
    for i in range(1, usa_count):
        tail = i * bytes_per_sector - 2
        if tail + 2 > len(record):
            break
        if bytes(record[tail:tail + 2]) != usn:
            raise FixupError(f"USN mismatch in sector {i}")
        src = usa_off + i * 2
        record[tail:tail + 2] = record[src:src + 2]


@dataclass(frozen=True)
class RecordHeader:
    in_use: bool
    is_directory: bool
    sequence: int
    base_ref: int
    attrs_offset: int


def parse_record_header(record: bytes) -> RecordHeader:
    sequence = struct.unpack_from("<H", record, 0x10)[0]
    attrs_offset = struct.unpack_from("<H", record, 0x14)[0]
    flags = struct.unpack_from("<H", record, 0x16)[0]
    base_ref = struct.unpack_from("<Q", record, 0x20)[0] & 0x0000FFFFFFFFFFFF
    return RecordHeader(
        in_use=bool(flags & 0x0001),
        is_directory=bool(flags & 0x0002),
        sequence=sequence,
        base_ref=base_ref,
        attrs_offset=attrs_offset,
    )


def iter_attributes(record: bytes, attrs_offset: int) -> Iterator[tuple[int, memoryview]]:
    view = memoryview(record)
    off = attrs_offset
    n = len(record)
    while off + 8 <= n:
        type_id = struct.unpack_from("<I", record, off)[0]
        if type_id == ATTR_END:
            return
        length = struct.unpack_from("<I", record, off + 4)[0]
        if length < 8 or off + length > n:
            return
        yield type_id, view[off:off + length]
        off += length


@dataclass(frozen=True)
class AttrHeader:
    type_id: int
    length: int
    non_resident: bool
    name: str
    flags: int
    value_offset: int
    value_length: int
    data_size: int
    alloc_size: int
    compressed_size: int
    runs_offset: int
    start_vcn: int = 0


def parse_attr_header(attr) -> AttrHeader:
    """Parse one attribute header.

    Accepts a memoryview and does NOT copy it. iter_attributes yields views
    precisely to avoid a copy per attribute; materialising the whole attribute
    here would spend that saving several million times over on a full volume.
    Only the name, which is a short slice and needs decoding, is copied.
    """
    type_id, length = struct.unpack_from("<II", attr, 0x00)
    non_resident = bool(attr[0x08])
    name_len = attr[0x09]
    name_off = struct.unpack_from("<H", attr, 0x0A)[0]
    flags = struct.unpack_from("<H", attr, 0x0C)[0]
    name = ""
    if name_len and name_off:
        name = bytes(attr[name_off:name_off + name_len * 2]).decode("utf-16-le")
    if non_resident:
        # A non-resident attribute too large for one record is split across
        # several. ONLY the fragment starting at VCN 0 carries the true
        # data_size and alloc_size; later fragments repeat the header with a
        # non-zero start VCN, so counting them multiplies the file's size by
        # its fragment count.
        start_vcn = struct.unpack_from("<Q", attr, 0x10)[0]
        runs_offset = struct.unpack_from("<H", attr, 0x20)[0]
        alloc_size = struct.unpack_from("<Q", attr, 0x28)[0]
        data_size = struct.unpack_from("<Q", attr, 0x30)[0]
        # TotalAllocated. NTFS emits this field when the attribute is
        # compressed OR SPARSE -- not compressed alone. For a sparse file
        # alloc_size is the full VCN span, which the volume never gave up;
        # this is the real cost.
        compressed_size = 0
        if flags & (FLAG_COMPRESSED | FLAG_SPARSE):
            compressed_size = struct.unpack_from("<Q", attr, 0x40)[0]
        return AttrHeader(type_id, length, True, name, flags, 0, 0,
                          data_size, alloc_size, compressed_size, runs_offset,
                          start_vcn)
    value_length = struct.unpack_from("<I", attr, 0x10)[0]
    value_offset = struct.unpack_from("<H", attr, 0x14)[0]
    return AttrHeader(type_id, length, False, name, flags, value_offset,
                      value_length, value_length, 0, 0, 0)


def attr_value(attr, header: AttrHeader | None = None) -> bytes:
    """The resident value bytes of an attribute, or b"" if non-resident.

    Pass `header` when the caller has already parsed it -- every caller on the
    scan hot path has -- so the header is not parsed twice per attribute. The
    view is sliced before it is copied, so only the value itself is
    materialised, not the whole attribute.
    """
    h = header if header is not None else parse_attr_header(attr)
    if h.non_resident:
        return b""
    return bytes(attr[h.value_offset:h.value_offset + h.value_length])


class StdInfo(NamedTuple):
    ctime: int
    mtime: int
    atime: int
    dos_attrs: int
    security_id: int


def parse_standard_information(value: bytes) -> StdInfo:
    ctime, mtime, _mft_time, atime = struct.unpack_from("<QQQQ", value, 0x00)
    dos_attrs = struct.unpack_from("<I", value, 0x20)[0]
    security_id = struct.unpack_from("<I", value, 0x34)[0] if len(value) >= 0x38 else 0
    return StdInfo(ctime, mtime, atime, dos_attrs, security_id)


class FileNameAttr(NamedTuple):
    parent_ref: int
    parent_seq: int
    namespace: int
    name: str
    alloc_size: int
    real_size: int


def parse_file_name(value: bytes) -> FileNameAttr:
    parent = struct.unpack_from("<Q", value, 0x00)[0]
    parent_ref = parent & 0x0000FFFFFFFFFFFF
    parent_seq = parent >> 48
    alloc_size = struct.unpack_from("<Q", value, 0x28)[0]
    real_size = struct.unpack_from("<Q", value, 0x30)[0]
    name_len = value[0x40]
    namespace = value[0x41]
    name = bytes(value[0x42:0x42 + name_len * 2]).decode("utf-16-le")
    return FileNameAttr(parent_ref, parent_seq, namespace, name, alloc_size, real_size)


def decode_data_runs(data: bytes, offset: int) -> list[tuple[int | None, int]]:
    """Decode a run list into (lcn, cluster_count) pairs; lcn None means sparse.

    Offsets are signed deltas against the previous run's LCN, not absolute.
    """
    runs: list[tuple[int | None, int]] = []
    lcn = 0
    pos = offset
    n = len(data)
    while pos < n:
        header = data[pos]
        pos += 1
        if header == 0:
            break
        len_size = header & 0x0F
        off_size = (header >> 4) & 0x0F
        if len_size == 0 or pos + len_size > n:
            break
        run_len = int.from_bytes(data[pos:pos + len_size], "little")
        pos += len_size
        if off_size == 0:
            runs.append((None, run_len))
            continue
        if pos + off_size > n:
            break
        lcn += int.from_bytes(data[pos:pos + off_size], "little", signed=True)
        pos += off_size
        runs.append((lcn, run_len))
    return runs
