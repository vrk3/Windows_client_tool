"""MFT record interpretation and volume streaming."""
import struct
from dataclasses import dataclass, field

from ..store.node_store import DIR, REPARSE, HARDLINK_DUP, COMPRESSED, SPARSE, ADS
from .ntfs_structs import (
    FILE_RECORD_MAGIC, FixupError, apply_fixup, attr_value, iter_attributes,
    parse_attr_header, parse_file_name, parse_record_header,
    parse_standard_information,
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_INDEX_ROOT,
    ATTR_REPARSE_POINT, NS_DOS, NS_POSIX, NS_WIN32, NS_WIN32_DOS,
    decode_data_runs,
    FLAG_COMPRESSED, FLAG_SPARSE,
)


@dataclass(frozen=True)
class NameRef:
    name: str
    parent_ref: int
    parent_seq: int


@dataclass
class ParsedRecord:
    record_no: int
    sequence: int
    base_ref: int
    name: str = ""
    parent_ref: int = -1
    parent_seq: int = 0
    size: int = 0
    alloc: int = 0
    ctime: int = 0
    mtime: int = 0
    atime: int = 0
    security_id: int = 0
    flags: int = 0
    extra_names: list[NameRef] = field(default_factory=list)


def _read_attributes(record: bytearray, header, out: "ParsedRecord",
                     names: list[tuple[int, NameRef]]) -> None:
    """Fold every attribute in one record into `out` and `names`.

    Split out of parse_mft_record purely so a torn record can be caught as a
    unit: any struct/index/decode failure anywhere in here means the record is
    untrustworthy in full, and the caller drops it.
    """
    for type_id, attr in iter_attributes(record, header.attrs_offset):
        h = parse_attr_header(attr)
        if type_id == ATTR_STANDARD_INFORMATION:
            si = parse_standard_information(attr_value(attr, h))
            out.ctime, out.mtime, out.atime = si.ctime, si.mtime, si.atime
            out.security_id = si.security_id
        elif type_id == ATTR_FILE_NAME:
            fn = parse_file_name(attr_value(attr, h))
            names.append((fn.namespace, NameRef(fn.name, fn.parent_ref, fn.parent_seq)))
        elif type_id == ATTR_DATA:
            if h.name:
                out.flags |= ADS
            if h.non_resident:
                out.size += h.data_size
                out.alloc += h.compressed_size if (h.flags & FLAG_COMPRESSED) else h.alloc_size
                if h.flags & FLAG_COMPRESSED:
                    out.flags |= COMPRESSED
                if h.flags & FLAG_SPARSE:
                    out.flags |= SPARSE
            else:
                out.size += h.value_length
        elif type_id == ATTR_INDEX_ROOT:
            out.flags |= DIR
        elif type_id == ATTR_REPARSE_POINT:
            out.flags |= REPARSE


def parse_mft_record(record: bytearray, record_no: int,
                     bytes_per_sector: int) -> ParsedRecord | None:
    """Interpret one MFT file record. Returns None if it is not a live file record."""
    if len(record) < 0x30 or bytes(record[0:4]) != FILE_RECORD_MAGIC:
        return None
    try:
        apply_fixup(record, bytes_per_sector)
    except FixupError:
        return None
    try:
        header = parse_record_header(record)
    except (struct.error, IndexError):
        return None
    if not header.in_use:
        return None

    out = ParsedRecord(record_no=record_no, sequence=header.sequence,
                       base_ref=header.base_ref)
    if header.is_directory:
        out.flags |= DIR

    names: list[tuple[int, NameRef]] = []
    try:
        _read_attributes(record, header, out, names)
    except (struct.error, IndexError, UnicodeDecodeError):
        # The volume is read live, with FILE_SHARE_WRITE and no snapshot, so a
        # record can be torn mid-update: an attribute header may claim a length
        # its bytes do not cover. Skipping the one record is right; letting the
        # exception escape would abort a whole-volume scan on a single blip.
        return None

    if names:
        # Win32 and Win32&DOS beat POSIX; the DOS 8.3 alias is a last resort.
        preference = {NS_WIN32: 0, NS_WIN32_DOS: 1, NS_POSIX: 2, NS_DOS: 3}
        names.sort(key=lambda pair: preference.get(pair[0], 4))
        primary = names[0][1]
        out.name = primary.name
        out.parent_ref = primary.parent_ref
        out.parent_seq = primary.parent_seq
        seen = {(primary.name, primary.parent_ref)}
        for namespace, ref in names[1:]:
            if namespace == NS_DOS:
                continue
            key = (ref.name, ref.parent_ref)
            if key not in seen:
                seen.add(key)
                out.extra_names.append(ref)
    return out


ROOT_RECORD_NO = 5
FIRST_USER_RECORD = 16      # 0-15 are $MFT, $LogFile, $Bitmap and friends


class MftTreeBuilder:
    """Assembles ParsedRecords into a NodeStore.

    Records arrive in MFT order, which says nothing about parent/child
    ordering, so nodes are created first and linked in finish().
    """

    def __init__(self, store, volume_label: str = "C:",
                 charge_all_hardlinks: bool = False) -> None:
        self.store = store
        self.volume_label = volume_label
        self.charge_all_hardlinks = charge_all_hardlinks
        self.root = -1
        self.orphan_root: int | None = None
        self._index_of: dict[int, int] = {}      # record_no -> node index
        self._sequence: dict[int, int] = {}      # record_no -> sequence
        self._pending: list[tuple[int, int, int]] = []   # node, parent_ref, parent_seq

    def feed(self, rec: ParsedRecord) -> None:
        if rec.base_ref:
            return                              # $ATTRIBUTE_LIST extension record
        if rec.record_no == ROOT_RECORD_NO:
            self.root = self.store.add(-1, self.volume_label, attrs=rec.flags | DIR)
            self._index_of[rec.record_no] = self.root
            self._sequence[rec.record_no] = rec.sequence
            return
        if rec.record_no < FIRST_USER_RECORD or not rec.name:
            return
        idx = self.store.add(-1, rec.name, size=rec.size, alloc=rec.alloc,
                             mtime=rec.mtime, ctime=rec.ctime, atime=rec.atime,
                             attrs=rec.flags, owner_id=rec.security_id)
        self._index_of[rec.record_no] = idx
        self._sequence[rec.record_no] = rec.sequence
        self._pending.append((idx, rec.parent_ref, rec.parent_seq))
        for extra in rec.extra_names:
            flags = rec.flags if self.charge_all_hardlinks else rec.flags | HARDLINK_DUP
            size = rec.size if self.charge_all_hardlinks else 0
            alloc = rec.alloc if self.charge_all_hardlinks else 0
            dup = self.store.add(-1, extra.name, size=size, alloc=alloc,
                                 mtime=rec.mtime, ctime=rec.ctime, atime=rec.atime,
                                 attrs=flags, owner_id=rec.security_id)
            self._pending.append((dup, extra.parent_ref, extra.parent_seq))

    def _ensure_orphan_root(self) -> int:
        if self.orphan_root is None:
            parent = self.root if self.root >= 0 else -1
            self.orphan_root = self.store.add(parent, "[Orphaned files]", attrs=DIR)
        return self.orphan_root

    def finish(self) -> None:
        if self.root < 0:
            self.root = self.store.add(-1, self.volume_label, attrs=DIR)
            self._index_of[ROOT_RECORD_NO] = self.root
            self._sequence[ROOT_RECORD_NO] = 1
        for node, parent_ref, parent_seq in self._pending:
            parent_idx = self._index_of.get(parent_ref)
            known_seq = self._sequence.get(parent_ref)
            if parent_idx is None or (known_seq is not None and known_seq != parent_seq):
                parent_idx = self._ensure_orphan_root()
            self.store.parent[node] = parent_idx
        self.store.build_child_lists()


CHUNK_BYTES = 4 * 1024 * 1024


class MftScanner:
    """Streams the MFT and feeds records to an MftTreeBuilder.

    ``reader`` is injectable so the whole class is testable against a byte
    image with no volume handle and no elevation.
    """

    def __init__(self, volume_letter: str, info, reader=None,
                 charge_all_hardlinks: bool = False) -> None:
        self.letter = volume_letter.rstrip(":")
        self.info = info
        self.charge_all_hardlinks = charge_all_hardlinks
        self._reader = reader or self._read_from_volume
        self.builder: MftTreeBuilder | None = None
        # Byte extents of the $MFT itself, filled in by scan(). One entry means
        # either a contiguous table or a fallback to the old linear assumption.
        self.extents: list[tuple[int, int]] = []
        # True when the MFT could not be read to the end. The tree is then a
        # PREFIX of the volume, not the volume, and its totals must not be
        # presented as authoritative.
        self.truncated = False

    def _read_from_volume(self, offset: int, length: int) -> bytes | None:
        """None means the read failed, distinct from b"" meaning end of data."""
        from .volume_info import open_volume, read_at, _kernel32
        handle = open_volume(self.letter)
        if not handle:
            return None
        try:
            return read_at(handle, offset, length)
        finally:
            _kernel32.CloseHandle(handle)

    def _read_extents(self) -> list[tuple[int, int]]:
        """Byte extents of the $MFT, decoded from record 0's own DATA run list.

        The $MFT is a file like any other and is routinely fragmented on an aged
        volume. Treating mft_offset..mft_offset+mft_valid_length as one span
        reads other files' clusters as if they were records -- they fail the
        FILE magic check and are skipped, so every record past the first extent
        is silently lost and the volume simply looks smaller.

        Falls back to the single linear span when record 0 cannot be read or
        carries no usable run list. That is the previous behaviour, and it is
        the right answer for a genuinely contiguous table.
        """
        info = self.info
        linear = [(info.mft_offset, info.mft_valid_length)]
        raw = self._reader(info.mft_offset, info.bytes_per_record)
        if not raw or len(raw) < info.bytes_per_record:
            return linear
        rec = bytearray(raw)
        if bytes(rec[0:4]) != FILE_RECORD_MAGIC:
            return linear
        try:
            apply_fixup(rec, info.bytes_per_sector)
            header = parse_record_header(rec)
            for type_id, attr in iter_attributes(rec, header.attrs_offset):
                if type_id != ATTR_DATA:
                    continue
                h = parse_attr_header(attr)
                if not h.non_resident or h.name:
                    continue          # named stream, not $MFT's own data
                runs = decode_data_runs(bytes(attr), h.runs_offset)
                extents = [(lcn * info.bytes_per_cluster,
                            count * info.bytes_per_cluster)
                           for lcn, count in runs if lcn is not None and count > 0]
                return extents or linear
        except (struct.error, IndexError, FixupError, UnicodeDecodeError):
            return linear
        return linear

    def scan(self, store, on_batch=None, should_cancel=None,
             wait_if_paused=None, batch_size: int = 500) -> int:
        rec_size = self.info.bytes_per_record
        total = self.info.mft_valid_length
        self.builder = MftTreeBuilder(store, f"{self.letter}:",
                                      self.charge_all_hardlinks)
        parsed = 0
        batch_start = len(store)
        cancelled = False
        seen = 0
        # `consumed` counts bytes of the $MFT DATA STREAM, not bytes of the
        # volume. Record numbers are logical positions in that stream and are
        # what parent references point at, so they must be derived from
        # `consumed` -- never from a physical volume offset, which jumps
        # arbitrarily at every extent boundary.
        consumed = 0
        self.extents = self._read_extents()
        for ext_offset, ext_length in self.extents:
            if cancelled or consumed >= total:
                break
            offset = ext_offset
            end = ext_offset + min(ext_length, total - consumed)
            while offset < end and not cancelled:
                chunk = self._reader(offset, min(CHUNK_BYTES, end - offset))
                if chunk is None:
                    # A failed read, not end of data. Without this distinction
                    # the scan stops here and reports a smaller volume rather
                    # than a broken one.
                    self.truncated = True
                    break
                if not chunk:
                    break
                # A chunk length is not guaranteed to be a multiple of rec_size
                # (a short read, or a non-record-aligned extent tail). Only the
                # whole-record prefix is consumed here; leftover tail bytes are
                # re-read at the start of the next iteration by advancing by
                # `usable`, not len(chunk), so the stream stays record-aligned.
                usable = (len(chunk) // rec_size) * rec_size
                if usable == 0:
                    # Fewer than one whole record available, so no progress is
                    # possible. If the MFT has not been consumed, this is a
                    # stall, not a clean finish.
                    self.truncated = True
                    break
                base = consumed
                for pos in range(0, usable, rec_size):
                    # Checked inside the record loop, not per chunk: a 4 MB
                    # chunk is ~4000 records, and Stop must not wait for them.
                    if seen % batch_size == 0:
                        if wait_if_paused:
                            wait_if_paused()
                        if should_cancel and should_cancel():
                            cancelled = True
                            break
                    seen += 1
                    record_no = (base + pos) // rec_size
                    rec = bytearray(chunk[pos:pos + rec_size])
                    parsed_rec = parse_mft_record(rec, record_no,
                                                  self.info.bytes_per_sector)
                    if parsed_rec is None:
                        continue
                    before = len(store)
                    self.builder.feed(parsed_rec)
                    if len(store) > before:
                        parsed += len(store) - before
                    if on_batch and len(store) - batch_start >= batch_size:
                        on_batch((batch_start, len(store)))
                        batch_start = len(store)
                offset += usable
                consumed += usable
        if not cancelled and consumed < total:
            # The run list did not account for the whole valid MFT length.
            self.truncated = True
        self.builder.finish()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return parsed
