"""MFT record interpretation and volume streaming."""
from dataclasses import dataclass, field

from ..store.node_store import DIR, REPARSE, HARDLINK_DUP, COMPRESSED, SPARSE, ADS
from .ntfs_structs import (
    FILE_RECORD_MAGIC, FixupError, apply_fixup, attr_value, iter_attributes,
    parse_attr_header, parse_file_name, parse_record_header,
    parse_standard_information,
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_INDEX_ROOT,
    ATTR_REPARSE_POINT, NS_DOS, FLAG_COMPRESSED, FLAG_SPARSE,
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


def parse_mft_record(record: bytearray, record_no: int,
                     bytes_per_sector: int) -> ParsedRecord | None:
    """Interpret one MFT file record. Returns None if it is not a live file record."""
    if len(record) < 0x30 or bytes(record[0:4]) != FILE_RECORD_MAGIC:
        return None
    try:
        apply_fixup(record, bytes_per_sector)
    except FixupError:
        return None
    header = parse_record_header(record)
    if not header.in_use:
        return None

    out = ParsedRecord(record_no=record_no, sequence=header.sequence,
                       base_ref=header.base_ref)
    if header.is_directory:
        out.flags |= DIR

    names: list[tuple[int, NameRef]] = []
    for type_id, attr in iter_attributes(record, header.attrs_offset):
        h = parse_attr_header(attr)
        if type_id == ATTR_STANDARD_INFORMATION:
            si = parse_standard_information(attr_value(attr))
            out.ctime, out.mtime, out.atime = si.ctime, si.mtime, si.atime
            out.security_id = si.security_id
        elif type_id == ATTR_FILE_NAME:
            fn = parse_file_name(attr_value(attr))
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

    if names:
        # Win32 (1) and Win32&DOS (3) beat POSIX (0); DOS 8.3 (2) is last resort.
        preference = {1: 0, 3: 1, 0: 2, NS_DOS: 3}
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
