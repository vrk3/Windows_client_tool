"""Saved scans and snapshots (spec 4.4).

The arrays and the name blob are written as raw little-endian blocks under
zlib, with a JSON header carrying target, timestamp, engine, cluster size and
options. Loading reconstructs the store directly -- no per-node parsing, which
is what keeps a five-million-node scan loadable at all.

Byte order is forced little-endian on write and on read. `array.tofile` writes
NATIVE order, so a file written here and read on a big-endian machine would
load silently transposed numbers rather than failing. Nobody is going to run
this on a big-endian machine, but "silently wrong" is not a failure mode worth
leaving in a format that outlives the process that wrote it.
"""
import json
import struct
import sys
import time
import zlib
from dataclasses import dataclass, field

from .node_store import NodeStore

MAGIC = b"TSSCAN\x00"
FORMAT_VERSION = 1

#: (attribute, typecode). Order is part of the format; changing it needs a
#: version bump, not a quiet edit.
COLUMNS = (
    ("parent", "i"), ("name_off", "L"), ("name_len", "H"),
    ("size", "q"), ("alloc", "q"),
    ("mtime", "q"), ("ctime", "q"), ("atime", "q"),
    ("attrs", "L"), ("owner_id", "i"),
    ("first_child", "i"), ("next_sibling", "i"),
    ("file_count", "L"), ("folder_count", "L"),
)


class ScanFileError(Exception):
    """The file is not a scan file, or not one this build can read."""


@dataclass
class ScanHeader:
    target: str = ""
    timestamp: float = field(default_factory=time.time)
    engine: str = ""
    bytes_per_cluster: int = 0
    node_count: int = 0
    root: int = 0
    kind: str = "scan"              # "scan" or "snapshot"
    options: dict = field(default_factory=dict)

    def to_json(self) -> bytes:
        return json.dumps(self.__dict__, separators=(",", ":")).encode("utf-8")

    @classmethod
    def from_json(cls, raw: bytes) -> "ScanHeader":
        data = json.loads(raw.decode("utf-8"))
        header = cls()
        for key, value in data.items():
            if hasattr(header, key):
                setattr(header, key, value)
        return header


def _swap_if_needed(arr) -> None:
    if sys.byteorder != "little":
        arr.byteswap()


def save(path: str, store: NodeStore, root: int, header: ScanHeader) -> None:
    header.node_count = len(store)
    header.root = root
    header_bytes = header.to_json()

    blocks = [struct.pack("<I", len(store.names)), bytes(store.names)]
    for name, _typecode in COLUMNS:
        column = getattr(store, name)
        copy = column[:]                 # never byteswap the live store
        _swap_if_needed(copy)
        blocks.append(copy.tobytes())
    owners = json.dumps(store._owners, separators=(",", ":")).encode("utf-8")
    blocks.append(struct.pack("<I", len(owners)))
    blocks.append(owners)

    body = zlib.compress(b"".join(blocks), 6)
    with open(path, "wb") as handle:
        handle.write(MAGIC)
        handle.write(struct.pack("<H", FORMAT_VERSION))
        handle.write(struct.pack("<I", len(header_bytes)))
        handle.write(header_bytes)
        handle.write(body)


def load(path: str) -> tuple[NodeStore, int, ScanHeader]:
    import array

    with open(path, "rb") as handle:
        raw = handle.read()

    if len(raw) < len(MAGIC) + 6 or raw[:len(MAGIC)] != MAGIC:
        raise ScanFileError(f"{path} is not a TreeSize scan file.")
    offset = len(MAGIC)
    version = struct.unpack_from("<H", raw, offset)[0]
    offset += 2
    if version > FORMAT_VERSION:
        raise ScanFileError(
            f"{path} was written by a newer version (format {version}); "
            f"this build reads up to {FORMAT_VERSION}.")
    header_length = struct.unpack_from("<I", raw, offset)[0]
    offset += 4
    header = ScanHeader.from_json(raw[offset:offset + header_length])
    offset += header_length

    try:
        body = zlib.decompress(raw[offset:])
    except zlib.error as exc:
        raise ScanFileError(f"{path} is corrupt: {exc}") from exc

    store = NodeStore()
    pos = 0
    names_length = struct.unpack_from("<I", body, pos)[0]
    pos += 4
    store.names = bytearray(body[pos:pos + names_length])
    pos += names_length

    count = header.node_count
    for name, typecode in COLUMNS:
        column = array.array(typecode)
        width = column.itemsize * count
        if pos + width > len(body):
            raise ScanFileError(f"{path} is truncated in column {name!r}.")
        column.frombytes(body[pos:pos + width])
        _swap_if_needed(column)
        setattr(store, name, column)
        pos += width

    owners_length = struct.unpack_from("<I", body, pos)[0]
    pos += 4
    store._owners = json.loads(body[pos:pos + owners_length].decode("utf-8"))
    store._owner_ids = {sid: i for i, sid in enumerate(store._owners)}
    return store, header.root, header
