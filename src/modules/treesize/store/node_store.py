"""Columnar store for scanned filesystem nodes.

A node is an ``int`` index into parallel arrays, not an object; an object per
node would cost five to ten times this. The fixed columns measure 74 bytes,
and the name blob adds the rest.

Names are stored UTF-8, not UTF-16-LE. Windows filenames are near-universally
ASCII, so UTF-16 spent two bytes a character to encode one byte of
information: measured across a real 571,674-node C: scan, the blob was ~63 of
137 bytes/node, and UTF-8 roughly halves that. ``name_len`` counts BYTES, not
characters, which is what keeps a 4-byte astral-plane character correct.
"""
import array
from typing import Iterator

DIR = 0x01
REPARSE = 0x02
HARDLINK_DUP = 0x04
ADS = 0x08
COMPRESSED = 0x10
SPARSE = 0x20
HIDDEN = 0x40
EXCLUDED = 0x80


class NodeStore:
    def __init__(self) -> None:
        self.parent = array.array("i")
        self.name_off = array.array("L")
        self.name_len = array.array("H")
        self.size = array.array("q")
        self.alloc = array.array("q")
        self.mtime = array.array("q")
        self.ctime = array.array("q")
        self.atime = array.array("q")
        self.attrs = array.array("L")
        self.owner_id = array.array("i")
        self.first_child = array.array("i")
        self.next_sibling = array.array("i")
        self.file_count = array.array("L")
        self.folder_count = array.array("L")
        self.names = bytearray()
        self._owner_ids: dict[str, int] = {}
        self._owners: list[str] = []

    def __len__(self) -> int:
        return len(self.parent)

    def add(self, parent: int, name: str, *, size: int = 0, alloc: int = 0,
            mtime: int = 0, ctime: int = 0, atime: int = 0,
            attrs: int = 0, owner_id: int = -1) -> int:
        idx = len(self.parent)
        encoded = name.encode("utf-8")
        self.name_off.append(len(self.names))
        self.name_len.append(len(encoded))
        self.names += encoded
        self.parent.append(parent)
        self.size.append(size)
        self.alloc.append(alloc)
        self.mtime.append(mtime)
        self.ctime.append(ctime)
        self.atime.append(atime)
        self.attrs.append(attrs)
        self.owner_id.append(owner_id)
        self.first_child.append(-1)
        self.next_sibling.append(-1)
        self.file_count.append(0)
        self.folder_count.append(0)
        return idx

    def name(self, idx: int) -> str:
        off = self.name_off[idx]
        return bytes(self.names[off:off + self.name_len[idx]]).decode("utf-8")

    def path(self, idx: int) -> str:
        """Full path for a node, walking parents to a root.

        Guards against a corrupt parent cycle the same way compute_depths does.
        A cycle should cost a truncated-looking path, never a hung caller --
        this runs on a UI thread in phase 2.
        """
        parts = []
        seen = set()
        n = len(self.parent)
        while 0 <= idx < n and idx not in seen:
            seen.add(idx)
            parts.append(self.name(idx))
            nxt = self.parent[idx]
            if nxt == idx:
                break
            idx = nxt
        return "\\".join(reversed(parts))

    def intern_owner(self, sid: str) -> int:
        existing = self._owner_ids.get(sid)
        if existing is not None:
            return existing
        new_id = len(self._owners)
        self._owners.append(sid)
        self._owner_ids[sid] = new_id
        return new_id

    def owner(self, owner_id: int) -> str:
        return self._owners[owner_id] if 0 <= owner_id < len(self._owners) else ""

    def build_child_lists(self) -> None:
        """Link children to parents. Safe to call once, after all nodes are added.

        Iterating in reverse leaves each parent's child list in ascending
        index order, which keeps sibling ordering stable and predictable.
        """
        n = len(self.parent)
        for i in range(n):
            self.first_child[i] = -1
            self.next_sibling[i] = -1
        for i in range(n - 1, -1, -1):
            p = self.parent[i]
            if 0 <= p < n and p != i:
                self.next_sibling[i] = self.first_child[p]
                self.first_child[p] = i

    def children(self, idx: int) -> Iterator[int]:
        c = self.first_child[idx]
        while c >= 0:
            yield c
            c = self.next_sibling[c]

    def roots(self) -> Iterator[int]:
        n = len(self.parent)
        for i in range(n):
            p = self.parent[i]
            if p < 0 or p >= n or p == i:
                yield i
