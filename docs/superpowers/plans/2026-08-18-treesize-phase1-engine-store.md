# TreeSize Phase 1 — Scan Engine & Node Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the TreeSize scan engine and columnar node store — everything needed to scan a volume and hold the result in memory — verified by tests and a console harness, with no UI.

**Architecture:** A `NodeStore` holds the scan result in parallel `array` columns where a node is an `int` index. Two scanners fill it: `MftReader` parses the NTFS Master File Table directly from a raw volume handle (fast path, needs elevation), and `WalkScanner` uses `FindFirstFileExW` through ctypes (fallback). `Scanner` picks between them, applies filters, and streams index ranges to consumers in batches while supporting pause and cancel. A rollup pass computes folder subtotals bottom-up.

**Tech Stack:** Python 3.12, ctypes (Win32 + NTFS structures), `array` for columnar storage, pytest. No PyQt6 in this phase — the engine must be usable and testable headless.

**Spec:** `docs/superpowers/specs/2026-08-18-treesize-pro-design.md` (§3 Scan engine, §4 Data store)

## Global Constraints

- Python 3.12; virtualenv at `.venv/`. Run everything as `.venv\Scripts\python.exe -m pytest`.
- Tests import from `src/` via the existing `tests/conftest.py` path insertion. Do not add a second conftest.
- **No PyQt6 imports anywhere in `src/modules/treesize/scan/` or `src/modules/treesize/store/`.** The engine is headless; Qt integration arrives in phase 2.
- All MFT parsing must run in CI without elevation or volume access — parse functions take `bytes`, never a file handle.
- Little-endian throughout. NTFS timestamps stay as raw Windows FILETIME `int` (100 ns since 1601); no datetime conversion in the store.
- Sizes are `int` bytes. `size` and `alloc` are independent columns; never derive one from the other.
- Node flags are the module-level constants defined in Task 1. Do not redefine them per file.
- Every task ends green: `.venv\Scripts\python.exe -m pytest -q` passes before commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/modules/treesize/__init__.py` | package marker |
| `src/modules/treesize/store/__init__.py` | package marker |
| `src/modules/treesize/store/node_store.py` | columnar arrays, name blob, owner interning, child lists, path reconstruction |
| `src/modules/treesize/store/rollup.py` | depth assignment + deepest-first subtotal aggregation |
| `src/modules/treesize/scan/__init__.py` | package marker |
| `src/modules/treesize/scan/ntfs_structs.py` | pure byte-level NTFS parsing: fixups, attribute iteration, attribute value parsers, data runs |
| `src/modules/treesize/scan/volume_info.py` | `CreateFileW` + `FSCTL_GET_NTFS_VOLUME_DATA` |
| `src/modules/treesize/scan/mft_reader.py` | MFT streaming, record → store, parentage, hard links |
| `src/modules/treesize/scan/walk_scanner.py` | `FindFirstFileExW` threaded directory walk |
| `src/modules/treesize/scan/filters.py` | include/exclude rule evaluation |
| `src/modules/treesize/scan/scanner.py` | engine selection, batching, pause, cancel |
| `tools/treesize_scan.py` | console verification harness (not shipped in the UI) |

Tests mirror this under `tests/treesize/`.

---

### Task 1: NodeStore

**Files:**
- Create: `src/modules/treesize/__init__.py`, `src/modules/treesize/store/__init__.py`, `src/modules/treesize/store/node_store.py`
- Test: `tests/treesize/__init__.py`, `tests/treesize/test_node_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - Flags `DIR = 0x01`, `REPARSE = 0x02`, `HARDLINK_DUP = 0x04`, `ADS = 0x08`, `COMPRESSED = 0x10`, `SPARSE = 0x20`
  - `NodeStore()` with columns `parent, name_off, name_len, size, alloc, mtime, ctime, atime, attrs, owner_id, first_child, next_sibling, file_count, folder_count` and `names: bytearray`
  - `add(parent: int, name: str, *, size=0, alloc=0, mtime=0, ctime=0, atime=0, attrs=0, owner_id=-1) -> int`
  - `name(idx: int) -> str`, `path(idx: int) -> str`, `intern_owner(sid: str) -> int`, `owner(owner_id: int) -> str`
  - `build_child_lists() -> None`, `children(idx: int) -> Iterator[int]`, `roots() -> Iterator[int]`, `__len__`

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_node_store.py
from modules.treesize.store.node_store import NodeStore, DIR


def test_add_returns_sequential_indices():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    child = s.add(root, "Windows", size=100, attrs=DIR)
    assert (root, child) == (0, 1)
    assert len(s) == 2


def test_name_roundtrips_unicode():
    s = NodeStore()
    i = s.add(-1, "Ünïcödé — 文字")
    assert s.name(i) == "Ünïcödé — 文字"


def test_path_walks_parents():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    f = s.add(win, "notepad.exe", size=1024)
    assert s.path(f) == "C:\\Windows\\notepad.exe"


def test_size_and_alloc_are_independent():
    s = NodeStore()
    i = s.add(-1, "sparse.dat", size=385_000, alloc=4_096)
    assert s.size[i] == 385_000
    assert s.alloc[i] == 4_096


def test_owner_interning_dedupes():
    s = NodeStore()
    a = s.intern_owner("S-1-5-18")
    b = s.intern_owner("S-1-5-18")
    c = s.intern_owner("S-1-5-32-544")
    assert a == b
    assert a != c
    assert s.owner(c) == "S-1-5-32-544"


def test_build_child_lists_handles_out_of_order_parents():
    # MFT order gives no guarantee a parent is added before its child.
    s = NodeStore()
    child = s.add(2, "child.txt", size=5)   # parent index 2 does not exist yet
    root = s.add(-1, "C:", attrs=DIR)
    parent = s.add(root, "dir", attrs=DIR)
    assert (child, root, parent) == (0, 1, 2)
    s.build_child_lists()
    assert list(s.children(parent)) == [child]
    assert list(s.children(root)) == [parent]
    assert list(s.roots()) == [root]


def test_children_are_in_ascending_index_order():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    a = s.add(root, "a")
    b = s.add(root, "b")
    c = s.add(root, "c")
    s.build_child_lists()
    assert list(s.children(root)) == [a, b, c]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_node_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.treesize'`

- [ ] **Step 3: Write minimal implementation**

Create empty `src/modules/treesize/__init__.py`, `src/modules/treesize/store/__init__.py`, and `tests/treesize/__init__.py`.

```python
# src/modules/treesize/store/node_store.py
"""Columnar store for scanned filesystem nodes.

A node is an ``int`` index into parallel arrays, not an object. At 104 bytes
per node all in (74 fixed columns + ~30 of name), a five-million-file volume
stays near 500 MB; an object per node would be five to ten times that.
"""
import array
from typing import Iterator

DIR = 0x01
REPARSE = 0x02
HARDLINK_DUP = 0x04
ADS = 0x08
COMPRESSED = 0x10
SPARSE = 0x20


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
        encoded = name.encode("utf-16-le")
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
        return bytes(self.names[off:off + self.name_len[idx]]).decode("utf-16-le")

    def path(self, idx: int) -> str:
        parts = []
        while idx >= 0:
            parts.append(self.name(idx))
            idx = self.parent[idx]
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_node_store.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize tests/treesize
git commit -m "feat(treesize): add columnar NodeStore"
```

---

### Task 2: Rollup

**Files:**
- Create: `src/modules/treesize/store/rollup.py`
- Test: `tests/treesize/test_rollup.py`

**Interfaces:**
- Consumes: `NodeStore` and flags from Task 1.
- Produces: `compute_depths(store) -> array.array`, `rollup(store) -> None`. After `rollup`, a folder's `size`/`alloc` include its whole subtree, `file_count` is files in subtree, `folder_count` is folders in subtree.

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_rollup.py
import sys
from modules.treesize.store.node_store import NodeStore, DIR, HARDLINK_DUP
from modules.treesize.store.rollup import rollup, compute_depths


def _tree():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    s.add(win, "notepad.exe", size=1000, alloc=4096)
    s.add(win, "regedit.exe", size=2000, alloc=4096)
    users = s.add(root, "Users", attrs=DIR)
    s.add(users, "profile.dat", size=500, alloc=512)
    s.build_child_lists()
    return s, root, win, users


def test_rollup_sums_sizes_bottom_up():
    s, root, win, users = _tree()
    rollup(s)
    assert s.size[win] == 3000
    assert s.size[users] == 500
    assert s.size[root] == 3500


def test_rollup_sums_alloc_independently_of_size():
    s, root, win, users = _tree()
    rollup(s)
    assert s.alloc[win] == 8192
    assert s.alloc[root] == 8704


def test_rollup_counts_files_and_folders_in_subtree():
    s, root, win, users = _tree()
    rollup(s)
    assert (s.file_count[win], s.folder_count[win]) == (2, 0)
    assert (s.file_count[root], s.folder_count[root]) == (3, 2)


def test_rollup_handles_parent_added_after_child():
    s = NodeStore()
    leaf = s.add(1, "leaf.txt", size=7)   # parent not yet added
    folder = s.add(2, "folder", attrs=DIR)
    root = s.add(-1, "C:", attrs=DIR)
    s.build_child_lists()
    rollup(s)
    assert s.size[folder] == 7
    assert s.size[root] == 7
    assert s.file_count[root] == 1
    assert s.folder_count[root] == 1
    assert leaf == 0


def test_hardlink_duplicates_contribute_no_size():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "real.bin", size=1000, alloc=1024)
    s.add(root, "link.bin", size=0, alloc=0, attrs=HARDLINK_DUP)
    s.build_child_lists()
    rollup(s)
    assert s.size[root] == 1000


def test_deep_chain_does_not_recurse():
    # 20k-deep chain would blow a recursive implementation's stack.
    depth = 20_000
    s = NodeStore()
    prev = s.add(-1, "C:", attrs=DIR)
    for i in range(depth):
        prev = s.add(prev, f"d{i}", attrs=DIR)
    s.add(prev, "leaf.txt", size=42)
    s.build_child_lists()
    assert sys.getrecursionlimit() < depth
    rollup(s)
    assert s.size[0] == 42
    assert s.folder_count[0] == depth


def test_compute_depths_assigns_zero_to_roots():
    s, root, win, users = _tree()
    d = compute_depths(s)
    assert d[root] == 0
    assert d[win] == 1
    assert d[users] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_rollup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.treesize.store.rollup'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/modules/treesize/store/rollup.py
"""Bottom-up aggregation of folder subtotals.

Two linear passes, no recursion. An MFT record number carries no ordering
guarantee relative to its parent, so depth is resolved iteratively and
nodes are then processed deepest-first via a counting sort.
"""
import array

from .node_store import NodeStore, DIR


_UNVISITED = -1
_IN_PROGRESS = -2


def compute_depths(store: NodeStore) -> array.array:
    n = len(store)
    depth = array.array("i", [_UNVISITED]) * n if n else array.array("i")
    for i in range(n):
        if depth[i] >= 0:
            continue
        chain = []
        j = i
        # _IN_PROGRESS marks nodes on the CURRENT walk. Without it, a parent
        # cycle of length >= 2 (parent[x]=y, parent[y]=x) walks x,y,x,y...
        # forever, because depth[] is only written after the walk completes.
        # The nxt != j guard below catches only an immediate self-reference.
        while 0 <= j < n and depth[j] == _UNVISITED:
            depth[j] = _IN_PROGRESS
            chain.append(j)
            nxt = store.parent[j]
            j = nxt if (0 <= nxt < n and nxt != j) else -1
        if 0 <= j < n and depth[j] == _IN_PROGRESS:
            base = -1        # cycle: treat the closing node as a root
        else:
            base = depth[j] if (0 <= j < n) else -1
        for k in reversed(chain):
            base += 1
            depth[k] = base
    return depth


def _order_by_depth(depth: array.array, n: int) -> list[int]:
    """Counting sort: indices ascending by depth. O(n), not O(n log n)."""
    if n == 0:
        return []
    max_d = max(depth)
    counts = [0] * (max_d + 2)
    for d in depth:
        counts[d + 1] += 1
    for i in range(1, len(counts)):
        counts[i] += counts[i - 1]
    order = [0] * n
    for i in range(n):
        d = depth[i]
        order[counts[d]] = i
        counts[d] += 1
    return order


def rollup(store: NodeStore) -> None:
    n = len(store)
    if n == 0:
        return
    depth = compute_depths(store)
    order = _order_by_depth(depth, n)
    for i in reversed(order):
        p = store.parent[i]
        if not (0 <= p < n) or p == i:
            continue
        # A well-formed child is exactly one deeper than its parent, so this
        # never fires on legitimate data. On a parent cycle it fires in exactly
        # one direction, so each byte is counted at most once.
        if depth[p] >= depth[i]:
            continue
        store.size[p] += store.size[i]
        store.alloc[p] += store.alloc[i]
        if store.attrs[i] & DIR:
            store.folder_count[p] += 1 + store.folder_count[i]
            store.file_count[p] += store.file_count[i]
        else:
            store.file_count[p] += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_rollup.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/store/rollup.py tests/treesize/test_rollup.py
git commit -m "feat(treesize): add non-recursive subtree rollup"
```

---

### Task 3: NTFS byte-level structures

This is the highest-risk code in the phase and the reason the parsers take `bytes` rather than a handle — every case below is testable in CI without a volume.

**Files:**
- Create: `src/modules/treesize/scan/__init__.py`, `src/modules/treesize/scan/ntfs_structs.py`
- Test: `tests/treesize/test_ntfs_structs.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `apply_fixup(record: bytearray, bytes_per_sector: int) -> None` (mutates in place, raises `FixupError` on mismatch)
  - `RecordHeader(in_use: bool, is_directory: bool, sequence: int, base_ref: int, attrs_offset: int)` and `parse_record_header(record: bytes) -> RecordHeader`
  - `iter_attributes(record: bytes, attrs_offset: int) -> Iterator[tuple[int, memoryview]]`
  - `AttrHeader(type_id, length, non_resident, name, flags, value_offset, value_length, data_size, alloc_size, compressed_size, runs_offset)` and `parse_attr_header(attr: bytes) -> AttrHeader`
  - `parse_standard_information(value: bytes) -> StdInfo(ctime, mtime, atime, dos_attrs, security_id)`
  - `parse_file_name(value: bytes) -> FileNameAttr(parent_ref, parent_seq, namespace, name, alloc_size, real_size)`
  - `decode_data_runs(data: bytes, offset: int) -> list[tuple[int | None, int]]`
  - Constants `ATTR_STANDARD_INFORMATION=0x10`, `ATTR_ATTRIBUTE_LIST=0x20`, `ATTR_FILE_NAME=0x30`, `ATTR_DATA=0x80`, `ATTR_INDEX_ROOT=0x90`, `ATTR_REPARSE_POINT=0xC0`, `ATTR_END=0xFFFFFFFF`; namespaces `NS_POSIX=0, NS_WIN32=1, NS_DOS=2, NS_WIN32_DOS=3`; `FLAG_COMPRESSED=0x0001`, `FLAG_SPARSE=0x8000`

- [ ] **Step 1: Write the failing test**

Fixture builders live in the test file so every case is readable as bytes.

```python
# tests/treesize/test_ntfs_structs.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_ntfs_structs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.treesize.scan'`

- [ ] **Step 3: Write minimal implementation**

Create empty `src/modules/treesize/scan/__init__.py`.

```python
# src/modules/treesize/scan/ntfs_structs.py
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


def parse_attr_header(attr: bytes) -> AttrHeader:
    attr = bytes(attr)
    type_id, length = struct.unpack_from("<II", attr, 0x00)
    non_resident = bool(attr[0x08])
    name_len = attr[0x09]
    name_off = struct.unpack_from("<H", attr, 0x0A)[0]
    flags = struct.unpack_from("<H", attr, 0x0C)[0]
    name = ""
    if name_len and name_off:
        name = attr[name_off:name_off + name_len * 2].decode("utf-16-le")
    if non_resident:
        runs_offset = struct.unpack_from("<H", attr, 0x20)[0]
        alloc_size = struct.unpack_from("<Q", attr, 0x28)[0]
        data_size = struct.unpack_from("<Q", attr, 0x30)[0]
        compressed_size = 0
        if flags & FLAG_COMPRESSED:
            compressed_size = struct.unpack_from("<Q", attr, 0x40)[0]
        return AttrHeader(type_id, length, True, name, flags, 0, 0,
                          data_size, alloc_size, compressed_size, runs_offset)
    value_length = struct.unpack_from("<I", attr, 0x10)[0]
    value_offset = struct.unpack_from("<H", attr, 0x14)[0]
    return AttrHeader(type_id, length, False, name, flags, value_offset,
                      value_length, value_length, 0, 0, 0)


def attr_value(attr: bytes) -> bytes:
    h = parse_attr_header(attr)
    if h.non_resident:
        return b""
    return bytes(attr)[h.value_offset:h.value_offset + h.value_length]


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_ntfs_structs.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan tests/treesize/test_ntfs_structs.py
git commit -m "feat(treesize): add NTFS record and attribute parsing"
```

---

### Task 4: MFT record → node

Turns one parsed record into the values a store row needs, still without touching a volume.

**Files:**
- Create: `src/modules/treesize/scan/mft_reader.py`
- Test: `tests/treesize/test_mft_record.py`

**Interfaces:**
- Consumes: everything from Task 3; flags from Task 1.
- Produces: `ParsedRecord(record_no, in_use, is_directory, sequence, base_ref, name, parent_ref, parent_seq, size, alloc, ctime, mtime, atime, security_id, flags, extra_names)` and `parse_mft_record(record: bytearray, record_no: int, bytes_per_sector: int) -> ParsedRecord | None` (returns `None` for non-`FILE` or deleted records).

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_mft_record.py
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
    attrs = (resident_attr(ATTR_FILE_NAME, file_name("s.dat", parent=5))
             + nonresident_attr(ATTR_DATA, data_size=385_000, alloc_size=4_096,
                                flags=FLAG_SPARSE))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_mft_record.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_mft_record'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/modules/treesize/scan/mft_reader.py
"""MFT record interpretation and volume streaming."""
from dataclasses import dataclass, field

from ..store.node_store import DIR, REPARSE, COMPRESSED, SPARSE, ADS
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_mft_record.py -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan/mft_reader.py tests/treesize/test_mft_record.py
git commit -m "feat(treesize): interpret MFT records into node values"
```

---

### Task 5: MFT tree assembly

Turns a stream of `ParsedRecord` into a populated store: parentage, orphans, hard links.

**Files:**
- Modify: `src/modules/treesize/scan/mft_reader.py` (append `MftTreeBuilder`)
- Test: `tests/treesize/test_mft_tree.py`

**Interfaces:**
- Consumes: `ParsedRecord`, `NameRef` (Task 4); `NodeStore` (Task 1).
- Produces: `MftTreeBuilder(store, volume_label="C:", charge_all_hardlinks=False)` with `feed(rec: ParsedRecord) -> None`, `finish() -> None`, attribute `root: int`, `orphan_root: int | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_mft_tree.py
from modules.treesize.scan.mft_reader import MftTreeBuilder, ParsedRecord, NameRef
from modules.treesize.store.node_store import NodeStore, DIR, HARDLINK_DUP
from modules.treesize.store.rollup import rollup

ROOT_RECORD = 5   # NTFS always numbers the volume root directory 5


def _dir(no, name, parent, seq=1):
    return ParsedRecord(record_no=no, sequence=seq, base_ref=0, name=name,
                        parent_ref=parent, parent_seq=1, flags=DIR)


def _file(no, name, parent, size, alloc=4096, seq=1, extra=()):
    return ParsedRecord(record_no=no, sequence=seq, base_ref=0, name=name,
                        parent_ref=parent, parent_seq=1, size=size, alloc=alloc,
                        extra_names=list(extra))


def _build(records, **kw):
    store = NodeStore()
    b = MftTreeBuilder(store, **kw)
    for r in records:
        b.feed(r)
    b.finish()
    return store, b


def test_builds_tree_from_out_of_order_records():
    # The child arrives before its parent, as happens in MFT order.
    store, b = _build([
        _file(60, "notepad.exe", parent=40, size=1000),
        _dir(40, "Windows", parent=ROOT_RECORD),
        _dir(ROOT_RECORD, "", parent=ROOT_RECORD),
    ])
    rollup(store)
    assert store.path(b.root) == "C:"
    win = next(store.children(b.root))
    assert store.name(win) == "Windows"
    assert store.size[win] == 1000


def test_root_record_is_the_volume_root():
    store, b = _build([_dir(ROOT_RECORD, "", parent=ROOT_RECORD)],
                      volume_label="E:")
    assert store.name(b.root) == "E:"
    assert store.parent[b.root] == -1


def test_stale_sequence_number_goes_to_orphan_root():
    stale = _file(60, "ghost.txt", parent=40, size=10)
    stale.parent_seq = 99          # parent 40 has sequence 1
    store, b = _build([stale, _dir(40, "Windows", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    assert b.orphan_root is not None
    assert [store.name(c) for c in store.children(b.orphan_root)] == ["ghost.txt"]


def test_missing_parent_goes_to_orphan_root():
    store, b = _build([_file(60, "stray.txt", parent=1234, size=10),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    assert [store.name(c) for c in store.children(b.orphan_root)] == ["stray.txt"]


def test_hardlink_second_path_is_zero_sized_and_flagged():
    rec = _file(60, "first.txt", parent=40, size=1000,
                extra=[NameRef("second.txt", 41, 1)])
    store, b = _build([rec,
                       _dir(40, "A", parent=ROOT_RECORD),
                       _dir(41, "B", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    rollup(store)
    by_name = {store.name(i): i for i in range(len(store))}
    assert store.size[by_name["first.txt"]] == 1000
    assert store.size[by_name["second.txt"]] == 0
    assert store.attrs[by_name["second.txt"]] & HARDLINK_DUP
    assert store.size[b.root] == 1000      # counted once, not twice


def test_charge_all_hardlinks_option_counts_every_path():
    rec = _file(60, "first.txt", parent=40, size=1000,
                extra=[NameRef("second.txt", 41, 1)])
    store, b = _build([rec,
                       _dir(40, "A", parent=ROOT_RECORD),
                       _dir(41, "B", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)],
                      charge_all_hardlinks=True)
    rollup(store)
    assert store.size[b.root] == 2000


def test_system_metafiles_below_record_16_are_skipped():
    # $MFT (0), $LogFile (2) and friends are not user-visible files.
    store, b = _build([_file(0, "$MFT", parent=ROOT_RECORD, size=999_999),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    rollup(store)
    assert store.size[b.root] == 0
    assert "$MFT" not in [store.name(i) for i in range(len(store))]


def test_extension_records_are_ignored():
    # base_ref != 0 marks an $ATTRIBUTE_LIST extension record, not a file.
    ext = _file(61, "spill", parent=40, size=500)
    ext.base_ref = 60
    store, b = _build([ext, _dir(40, "W", parent=ROOT_RECORD),
                       _dir(ROOT_RECORD, "", parent=ROOT_RECORD)])
    rollup(store)
    assert store.size[b.root] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_mft_tree.py -v`
Expected: FAIL — `ImportError: cannot import name 'MftTreeBuilder'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/modules/treesize/scan/mft_reader.py`:

```python
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
```

Add `HARDLINK_DUP` to the existing `from ..store.node_store import ...` line at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_mft_tree.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan/mft_reader.py tests/treesize/test_mft_tree.py
git commit -m "feat(treesize): assemble MFT records into a node tree"
```

---

### Task 6: Volume info

**Files:**
- Create: `src/modules/treesize/scan/volume_info.py`
- Test: `tests/treesize/test_volume_info.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `VolumeInfo(bytes_per_sector, bytes_per_cluster, bytes_per_record, mft_start_lcn, mft_valid_length, total_clusters)`, `parse_volume_data(buf: bytes) -> VolumeInfo`, `open_volume(letter: str) -> int` (raw handle), `get_volume_info(letter: str) -> VolumeInfo | None` (returns `None` when the volume cannot be opened — not elevated, not NTFS, remote).

- [ ] **Step 1: Write the failing test**

`parse_volume_data` is pure, so it is tested from bytes; the handle path is an
elevation-gated integration test.

```python
# tests/treesize/test_volume_info.py
import ctypes
import struct
import pytest

from modules.treesize.scan.volume_info import parse_volume_data, get_volume_info


def _buf(bps=512, spc=8, bpr=1024, mft_lcn=786_432, mft_len=268_435_456,
         total_clusters=488_378_646):
    # Layout is NTFS_VOLUME_DATA_BUFFER exactly; getting these offsets wrong
    # is invisible to a test that shares the mistake, so they are spelled out.
    b = bytearray(0x60)
    struct.pack_into("<Q", b, 0x00, 0)                 # VolumeSerialNumber
    struct.pack_into("<Q", b, 0x08, total_clusters * spc)   # NumberSectors
    struct.pack_into("<Q", b, 0x10, total_clusters)    # TotalClusters
    struct.pack_into("<Q", b, 0x18, 0)                 # FreeClusters
    struct.pack_into("<Q", b, 0x20, 0)                 # TotalReserved
    struct.pack_into("<I", b, 0x28, bps)               # BytesPerSector
    struct.pack_into("<I", b, 0x2C, bps * spc)         # BytesPerCluster
    struct.pack_into("<I", b, 0x30, bpr)               # BytesPerFileRecordSegment
    struct.pack_into("<I", b, 0x34, 1)                 # ClustersPerFileRecordSegment
    struct.pack_into("<Q", b, 0x38, mft_len)           # MftValidDataLength
    struct.pack_into("<Q", b, 0x40, mft_lcn)           # MftStartLcn
    struct.pack_into("<Q", b, 0x48, 0)                 # Mft2StartLcn
    return bytes(b)


def test_parses_cluster_geometry():
    v = parse_volume_data(_buf(bps=512, spc=8))
    assert v.bytes_per_sector == 512
    assert v.bytes_per_cluster == 4096
    assert v.bytes_per_record == 1024


def test_parses_mft_location():
    v = parse_volume_data(_buf(mft_lcn=786_432))
    assert v.mft_start_lcn == 786_432


def test_mft_byte_offset_is_lcn_times_cluster_size():
    v = parse_volume_data(_buf(spc=8, mft_lcn=100))
    assert v.mft_offset == 100 * 4096


def test_get_volume_info_returns_none_for_bogus_drive():
    assert get_volume_info("ZZ") is None


@pytest.mark.skipif(
    not ctypes.windll.shell32.IsUserAnAdmin(),
    reason="raw volume access requires elevation",
)
def test_get_volume_info_reads_c_drive_when_elevated():
    v = get_volume_info("C")
    assert v is not None
    assert v.bytes_per_cluster in (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536)
    assert v.bytes_per_record >= 1024
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_volume_info.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.treesize.scan.volume_info'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/modules/treesize/scan/volume_info.py
"""NTFS volume geometry via FSCTL_GET_NTFS_VOLUME_DATA."""
import ctypes
import struct
from ctypes import wintypes
from dataclasses import dataclass

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FSCTL_GET_NTFS_VOLUME_DATA = 0x00090064

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
_kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]


@dataclass(frozen=True)
class VolumeInfo:
    bytes_per_sector: int
    bytes_per_cluster: int
    bytes_per_record: int
    mft_start_lcn: int
    mft_valid_length: int
    total_clusters: int

    @property
    def mft_offset(self) -> int:
        return self.mft_start_lcn * self.bytes_per_cluster


def parse_volume_data(buf: bytes) -> VolumeInfo:
    """Unpack NTFS_VOLUME_DATA_BUFFER.

    Field offsets, in order: VolumeSerialNumber 0x00, NumberSectors 0x08,
    TotalClusters 0x10, FreeClusters 0x18, TotalReserved 0x20,
    BytesPerSector 0x28, BytesPerCluster 0x2C, BytesPerFileRecordSegment 0x30,
    ClustersPerFileRecordSegment 0x34, MftValidDataLength 0x38,
    MftStartLcn 0x40.
    """
    total_clusters = struct.unpack_from("<Q", buf, 0x10)[0]
    bps, bpc, bpr = struct.unpack_from("<III", buf, 0x28)
    mft_valid_length = struct.unpack_from("<Q", buf, 0x38)[0]
    mft_start_lcn = struct.unpack_from("<Q", buf, 0x40)[0]
    return VolumeInfo(bps, bpc, bpr, mft_start_lcn, mft_valid_length, total_clusters)


def open_volume(letter: str) -> int:
    """Open \\\\.\\<letter>: for raw read. Returns 0 on failure."""
    handle = _kernel32.CreateFileW(
        f"\\\\.\\{letter.rstrip(':')}:", GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return 0
    return handle


def get_volume_info(letter: str) -> VolumeInfo | None:
    """Volume geometry, or None when the raw volume cannot be read.

    Failure is expected and not an error: an unelevated process, a non-NTFS
    volume, or a network path all land here and select the walk scanner.
    """
    handle = open_volume(letter)
    if not handle:
        return None
    try:
        buf = ctypes.create_string_buffer(0x60)
        returned = wintypes.DWORD(0)
        ok = _kernel32.DeviceIoControl(handle, FSCTL_GET_NTFS_VOLUME_DATA, None, 0,
                                       buf, ctypes.sizeof(buf),
                                       ctypes.byref(returned), None)
        if not ok:
            return None
        return parse_volume_data(buf.raw)
    finally:
        _kernel32.CloseHandle(handle)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_volume_info.py -v`
Expected: PASS (the elevation-gated test SKIPs in an unelevated shell)

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan/volume_info.py tests/treesize/test_volume_info.py
git commit -m "feat(treesize): read NTFS volume geometry"
```

---

### Task 7: MFT streaming from a volume

Connects Tasks 3–6: read `$MFT`'s own run list, stream records through the builder.

**Files:**
- Modify: `src/modules/treesize/scan/mft_reader.py` (append `MftScanner`)
- Test: `tests/treesize/test_mft_scanner.py`

**Interfaces:**
- Consumes: `VolumeInfo`, `MftTreeBuilder`, `parse_mft_record`, `decode_data_runs`.
- Produces: `MftScanner(volume_letter, info, reader=None)` with `scan(store, on_batch=None, should_cancel=None, wait_if_paused=None) -> int` returning the node count. `reader` is a callable `(offset: int, length: int) -> bytes`, injectable so tests never touch a volume.

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_mft_scanner.py
import struct

from modules.treesize.scan.mft_reader import MftScanner, ROOT_RECORD_NO
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore
from modules.treesize.store.rollup import rollup
from modules.treesize.scan.ntfs_structs import (
    ATTR_STANDARD_INFORMATION, ATTR_FILE_NAME, ATTR_DATA, ATTR_END,
)
from tests.treesize.test_ntfs_structs import (
    build_record, resident_attr, nonresident_attr, std_info, file_name, SECTOR,
)

RECORD_SIZE = 1024
INFO = VolumeInfo(bytes_per_sector=SECTOR, bytes_per_cluster=4096,
                  bytes_per_record=RECORD_SIZE, mft_start_lcn=0,
                  mft_valid_length=0, total_clusters=1000)


def _record(name, parent, size=0, is_dir=False, record_no=0):
    attrs = (resident_attr(ATTR_STANDARD_INFORMATION, std_info())
             + resident_attr(ATTR_FILE_NAME, file_name(name, parent)))
    if not is_dir:
        attrs += nonresident_attr(ATTR_DATA, data_size=size, alloc_size=4096)
    return build_record(attrs + struct.pack("<I", ATTR_END),
                        is_dir=is_dir, size=RECORD_SIZE)


def _fake_mft(records: dict[int, bytearray]) -> bytes:
    """Lay records out at record_no * RECORD_SIZE, zero-filling the gaps."""
    highest = max(records) if records else 0
    buf = bytearray(RECORD_SIZE * (highest + 1))
    for no, rec in records.items():
        buf[no * RECORD_SIZE:(no + 1) * RECORD_SIZE] = rec
    return bytes(buf)


def _scan(records, **kw):
    image = _fake_mft(records)

    def reader(offset, length):
        return image[offset:offset + length]

    info = VolumeInfo(SECTOR, 4096, RECORD_SIZE, 0, len(image), 1000)
    store = NodeStore()
    scanner = MftScanner("C", info, reader=reader)
    count = scanner.scan(store, **kw)
    return store, scanner, count


def test_scans_records_into_a_tree():
    store, scanner, count = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        20: _record("Windows", ROOT_RECORD_NO, is_dir=True),
        21: _record("notepad.exe", 20, size=1000),
    })
    rollup(store)
    assert count == 3
    assert store.size[scanner.builder.root] == 1000


def test_zeroed_records_are_skipped():
    store, scanner, count = _scan({
        ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
        30: _record("a.txt", ROOT_RECORD_NO, size=10),
        # records 6..29 are zero-filled by _fake_mft
    })
    assert count == 2


def test_on_batch_receives_index_ranges():
    batches = []
    store, scanner, count = _scan(
        {ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
         20: _record("a.txt", ROOT_RECORD_NO, size=1),
         21: _record("b.txt", ROOT_RECORD_NO, size=2)},
        on_batch=batches.append, batch_size=1)
    assert batches
    assert batches[0][0] == 0
    assert batches[-1][1] == len(store)


def test_cancel_stops_early():
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1

    store, scanner, count = _scan(
        {ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
         20: _record("a.txt", ROOT_RECORD_NO, size=1),
         21: _record("b.txt", ROOT_RECORD_NO, size=2)},
        should_cancel=should_cancel, batch_size=1)
    assert count < 3


def test_wait_if_paused_is_called_between_chunks():
    seen = []
    _scan({ROOT_RECORD_NO: _record("", ROOT_RECORD_NO, is_dir=True),
           20: _record("a.txt", ROOT_RECORD_NO, size=1)},
          wait_if_paused=lambda: seen.append(1), batch_size=1)
    assert seen
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_mft_scanner.py -v`
Expected: FAIL — `ImportError: cannot import name 'MftScanner'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/modules/treesize/scan/mft_reader.py`:

```python
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

    def _read_from_volume(self, offset: int, length: int) -> bytes:
        from .volume_info import open_volume, _kernel32
        handle = open_volume(self.letter)
        if not handle:
            return b""
        try:
            import ctypes
            from ctypes import wintypes
            high = wintypes.LONG(offset >> 32)
            _kernel32.SetFilePointer(handle, offset & 0xFFFFFFFF,
                                     ctypes.byref(high), 0)
            buf = ctypes.create_string_buffer(length)
            read = wintypes.DWORD(0)
            _kernel32.ReadFile(handle, buf, length, ctypes.byref(read), None)
            return buf.raw[:read.value]
        finally:
            _kernel32.CloseHandle(handle)

    def scan(self, store, on_batch=None, should_cancel=None,
             wait_if_paused=None, batch_size: int = 500) -> int:
        rec_size = self.info.bytes_per_record
        total = self.info.mft_valid_length
        self.builder = MftTreeBuilder(store, f"{self.letter}:",
                                      self.charge_all_hardlinks)
        parsed = 0
        batch_start = len(store)
        offset = self.info.mft_offset
        end = offset + total
        cancelled = False
        seen = 0
        while offset < end and not cancelled:
            chunk = self._reader(offset, min(CHUNK_BYTES, end - offset))
            if not chunk:
                break
            # Only whole records are consumed, and offset advances by exactly
            # that much. A short or misaligned read therefore leaves its tail to
            # be re-read next iteration instead of being skipped -- advancing by
            # len(chunk) would drop those bytes AND desync record_no for the
            # entire rest of the scan, silently corrupting every parent lookup.
            usable = (len(chunk) // rec_size) * rec_size
            if usable == 0:
                break
            for pos in range(0, usable, rec_size):
                # Checked inside the record loop, not per chunk: a 4 MB chunk
                # is ~4000 records, and Stop must not wait for all of them.
                if seen % batch_size == 0:
                    if wait_if_paused:
                        wait_if_paused()
                    if should_cancel and should_cancel():
                        cancelled = True
                        break
                seen += 1
                record_no = (offset - self.info.mft_offset + pos) // rec_size
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
        self.builder.finish()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return parsed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_mft_scanner.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan/mft_reader.py tests/treesize/test_mft_scanner.py
git commit -m "feat(treesize): stream the MFT into the node store"
```

---

### Task 8: Walk scanner

**Files:**
- Create: `src/modules/treesize/scan/walk_scanner.py`
- Test: `tests/treesize/test_walk_scanner.py`

**Interfaces:**
- Consumes: `NodeStore`, flags (Task 1).
- Produces: `DirEntry(name, is_dir, is_reparse, size, ctime, mtime, atime)`, `list_directory(path: str) -> list[DirEntry]`, `WalkScanner(root_path, bytes_per_cluster=4096, max_workers=None)` with `scan(store, on_batch=None, should_cancel=None, wait_if_paused=None, batch_size=500) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_walk_scanner.py
import os

from modules.treesize.scan.walk_scanner import WalkScanner, list_directory
from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup


def _make_tree(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x" * 1000)
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_bytes(b"y" * 2000)
    (sub / "c.txt").write_bytes(b"z" * 3000)
    deep = sub / "deep"
    deep.mkdir()
    (deep / "d.txt").write_bytes(b"w" * 4000)
    return tmp_path


def test_list_directory_returns_entries_with_sizes(tmp_path):
    _make_tree(tmp_path)
    entries = {e.name: e for e in list_directory(str(tmp_path))}
    assert entries["a.txt"].size == 1000
    assert entries["a.txt"].is_dir is False
    assert entries["sub"].is_dir is True


def test_list_directory_excludes_dot_entries(tmp_path):
    _make_tree(tmp_path)
    names = {e.name for e in list_directory(str(tmp_path))}
    assert "." not in names and ".." not in names


def test_scan_totals_match_real_bytes(tmp_path):
    _make_tree(tmp_path)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path))
    scanner.scan(store)
    rollup(store)
    assert store.size[scanner.root] == 10_000


def test_scan_counts_files_and_folders(tmp_path):
    _make_tree(tmp_path)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path))
    scanner.scan(store)
    rollup(store)
    assert store.file_count[scanner.root] == 4
    assert store.folder_count[scanner.root] == 2


def test_allocated_size_is_cluster_rounded(tmp_path):
    (tmp_path / "small.txt").write_bytes(b"x" * 10)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), bytes_per_cluster=4096)
    scanner.scan(store)
    rollup(store)
    assert store.alloc[scanner.root] == 4096


def test_empty_file_allocates_nothing(tmp_path):
    (tmp_path / "empty.txt").write_bytes(b"")
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), bytes_per_cluster=4096)
    scanner.scan(store)
    rollup(store)
    assert store.alloc[scanner.root] == 0


def test_nested_paths_reconstruct(tmp_path):
    _make_tree(tmp_path)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path))
    scanner.scan(store)
    paths = {store.path(i) for i in range(len(store))}
    assert any(p.endswith("sub\\deep\\d.txt") for p in paths)


def test_cancel_stops_the_walk(tmp_path):
    _make_tree(tmp_path)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path))
    scanner.scan(store, should_cancel=lambda: True)
    assert len(store) <= 1        # root only


def test_on_batch_reports_ranges(tmp_path):
    _make_tree(tmp_path)
    batches = []
    store = NodeStore()
    WalkScanner(str(tmp_path)).scan(store, on_batch=batches.append, batch_size=1)
    assert batches
    assert batches[-1][1] == len(store)


def test_missing_directory_yields_no_entries():
    assert list_directory("C:\\definitely-not-a-real-path-9f3a") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_walk_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.treesize.scan.walk_scanner'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/modules/treesize/scan/walk_scanner.py
"""Directory walk fallback using FindFirstFileExW.

FindExInfoBasic skips 8.3 name resolution and FIND_FIRST_EX_LARGE_FETCH
batches directory entries, together giving far fewer kernel transitions
than os.scandir on deep trees.
"""
import ctypes
import os
from collections import deque
from ctypes import wintypes
from dataclasses import dataclass

from ..store.node_store import NodeStore, DIR, REPARSE

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FindExInfoBasic = 1
FindExSearchNameMatch = 0
FIND_FIRST_EX_LARGE_FETCH = 2
ERROR_NO_MORE_FILES = 18

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class FILETIME(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]

    @property
    def value(self) -> int:
        return (self.high << 32) | self.low


class WIN32_FIND_DATAW(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", FILETIME),
        ("ftLastAccessTime", FILETIME),
        ("ftLastWriteTime", FILETIME),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("dwReserved0", wintypes.DWORD),
        ("dwReserved1", wintypes.DWORD),
        ("cFileName", wintypes.WCHAR * 260),
        ("cAlternateFileName", wintypes.WCHAR * 14),
    ]


_kernel32.FindFirstFileExW.restype = wintypes.HANDLE
_kernel32.FindFirstFileExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.LPVOID,
                                       ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_kernel32.FindNextFileW.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
_kernel32.FindClose.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True)
class DirEntry:
    name: str
    is_dir: bool
    is_reparse: bool
    size: int
    ctime: int
    mtime: int
    atime: int


def _long_path(path: str) -> str:
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def list_directory(path: str) -> list[DirEntry]:
    data = WIN32_FIND_DATAW()
    handle = _kernel32.FindFirstFileExW(
        _long_path(os.path.join(path, "*")), FindExInfoBasic, ctypes.byref(data),
        FindExSearchNameMatch, None, FIND_FIRST_EX_LARGE_FETCH)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return []
    out: list[DirEntry] = []
    try:
        while True:
            name = data.cFileName
            if name not in (".", ".."):
                attrs = data.dwFileAttributes
                out.append(DirEntry(
                    name=name,
                    is_dir=bool(attrs & FILE_ATTRIBUTE_DIRECTORY),
                    is_reparse=bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT),
                    size=(data.nFileSizeHigh << 32) | data.nFileSizeLow,
                    ctime=data.ftCreationTime.value,
                    mtime=data.ftLastWriteTime.value,
                    atime=data.ftLastAccessTime.value,
                ))
            if not _kernel32.FindNextFileW(handle, ctypes.byref(data)):
                break
    finally:
        _kernel32.FindClose(handle)
    return out


class WalkScanner:
    def __init__(self, root_path: str, bytes_per_cluster: int = 4096,
                 max_workers: int | None = None) -> None:
        self.root_path = os.path.abspath(root_path)
        self.bytes_per_cluster = bytes_per_cluster
        self.max_workers = max_workers or min(32, (os.cpu_count() or 4) * 4)
        self.root = -1

    def _alloc_for(self, size: int) -> int:
        if size == 0:
            return 0
        c = self.bytes_per_cluster
        return ((size + c - 1) // c) * c

    def scan(self, store: NodeStore, on_batch=None, should_cancel=None,
             wait_if_paused=None, batch_size: int = 500) -> int:
        self.root = store.add(-1, self.root_path, attrs=DIR)
        queue: deque[tuple[int, str]] = deque([(self.root, self.root_path)])
        batch_start = len(store)
        while queue:
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            node, path = queue.popleft()
            for entry in list_directory(path):
                flags = 0
                if entry.is_dir:
                    flags |= DIR
                if entry.is_reparse:
                    flags |= REPARSE
                size = 0 if entry.is_dir else entry.size
                idx = store.add(node, entry.name, size=size,
                                alloc=self._alloc_for(size),
                                mtime=entry.mtime, ctime=entry.ctime,
                                atime=entry.atime, attrs=flags)
                if entry.is_dir and not entry.is_reparse:
                    queue.append((idx, os.path.join(path, entry.name)))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
        store.build_child_lists()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)
```

Note: the bounded thread pool from the spec is deliberately not wired here. A
single-threaded queue is correct and testable first; parallelism is a measured
optimization in Task 10 once the console harness can time a real scan.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_walk_scanner.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan/walk_scanner.py tests/treesize/test_walk_scanner.py
git commit -m "feat(treesize): add FindFirstFileExW walk scanner"
```

---

### Task 9: Filters and scan orchestration

**Files:**
- Create: `src/modules/treesize/scan/filters.py`, `src/modules/treesize/scan/scanner.py`
- Test: `tests/treesize/test_filters.py`, `tests/treesize/test_scanner.py`

**Interfaces:**
- Consumes: `MftScanner`, `WalkScanner`, `get_volume_info`, `NodeStore`, `rollup`.
- Produces:
  - `FilterSet(exclude_globs=(), min_size=0, max_size=None, exclude_hidden=False)` with `excludes(name, size, attrs) -> bool` and `excluded_count`
  - `ScanResult(store, root, engine, node_count, excluded, volume_info, elapsed)`
  - `Scanner(target: str, filters=None, charge_all_hardlinks=False)` with `scan(on_batch=None, should_cancel=None) -> ScanResult`, `pause()`, `resume()`, and `select_engine() -> str` returning `"mft"` or `"walk"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_filters.py
from modules.treesize.scan.filters import FilterSet
from modules.treesize.store.node_store import DIR


def test_no_rules_excludes_nothing():
    f = FilterSet()
    assert f.excludes("anything.txt", 100, 0) is False


def test_glob_exclusion_matches_name():
    f = FilterSet(exclude_globs=("*.tmp",))
    assert f.excludes("cache.tmp", 100, 0) is True
    assert f.excludes("cache.txt", 100, 0) is False


def test_glob_matching_is_case_insensitive():
    f = FilterSet(exclude_globs=("*.TMP",))
    assert f.excludes("cache.tmp", 100, 0) is True


def test_min_size_excludes_smaller_files():
    f = FilterSet(min_size=1000)
    assert f.excludes("small.bin", 999, 0) is True
    assert f.excludes("big.bin", 1000, 0) is False


def test_max_size_excludes_larger_files():
    f = FilterSet(max_size=1000)
    assert f.excludes("big.bin", 1001, 0) is True


def test_size_rules_never_exclude_directories():
    f = FilterSet(min_size=1000)
    assert f.excludes("emptydir", 0, DIR) is False


def test_excluded_count_accumulates():
    f = FilterSet(exclude_globs=("*.tmp",))
    f.excludes("a.tmp", 1, 0)
    f.excludes("b.tmp", 1, 0)
    f.excludes("c.txt", 1, 0)
    assert f.excluded_count == 2
```

```python
# tests/treesize/test_scanner.py
import ctypes
import pytest

from modules.treesize.scan.scanner import Scanner
from modules.treesize.scan.filters import FilterSet


def test_directory_target_selects_walk_engine(tmp_path):
    assert Scanner(str(tmp_path)).select_engine() == "walk"


def test_bogus_drive_falls_back_to_walk():
    assert Scanner("ZZ:\\").select_engine() == "walk"


def test_scan_directory_produces_totals(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 1500)
    sub = tmp_path / "s"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"y" * 2500)
    result = Scanner(str(tmp_path)).scan()
    assert result.engine == "walk"
    assert result.store.size[result.root] == 4000
    assert result.node_count == len(result.store)
    assert result.elapsed >= 0


def test_filters_exclude_matching_files(tmp_path):
    (tmp_path / "keep.bin").write_bytes(b"x" * 1000)
    (tmp_path / "drop.tmp").write_bytes(b"y" * 5000)
    result = Scanner(str(tmp_path), filters=FilterSet(exclude_globs=("*.tmp",))).scan()
    assert result.store.size[result.root] == 1000
    assert result.excluded == 1


def test_cancel_is_honoured(tmp_path):
    for i in range(20):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * 100)
    result = Scanner(str(tmp_path)).scan(should_cancel=lambda: True)
    assert result.store.size[result.root] == 0


def test_pause_and_resume_do_not_deadlock(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    s = Scanner(str(tmp_path))
    s.pause()
    s.resume()
    result = s.scan()
    assert result.store.size[result.root] == 100


@pytest.mark.skipif(
    not ctypes.windll.shell32.IsUserAnAdmin(),
    reason="MFT engine requires elevation",
)
def test_elevated_drive_target_selects_mft_engine():
    assert Scanner("C:\\").select_engine() == "mft"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_filters.py tests/treesize/test_scanner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'modules.treesize.scan.filters'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/modules/treesize/scan/filters.py
"""Include/exclude rules applied during the scan pass.

Excluded nodes are never added to the store, so an exclusion costs nothing
downstream -- no view, aggregate, or export has to know about it.
"""
import fnmatch
from dataclasses import dataclass, field

from ..store.node_store import DIR

FILE_ATTRIBUTE_HIDDEN = 0x2


@dataclass
class FilterSet:
    exclude_globs: tuple[str, ...] = ()
    min_size: int = 0
    max_size: int | None = None
    exclude_hidden: bool = False
    excluded_count: int = field(default=0, init=False)

    def excludes(self, name: str, size: int, attrs: int) -> bool:
        lowered = name.lower()
        hit = False
        for pattern in self.exclude_globs:
            if fnmatch.fnmatch(lowered, pattern.lower()):
                hit = True
                break
        if not hit and self.exclude_hidden and (attrs & FILE_ATTRIBUTE_HIDDEN):
            hit = True
        # Size rules apply to files only: a folder's size is unknown until
        # its subtree is rolled up, so filtering on it here would be wrong.
        if not hit and not (attrs & DIR):
            if size < self.min_size:
                hit = True
            elif self.max_size is not None and size > self.max_size:
                hit = True
        if hit:
            self.excluded_count += 1
        return hit
```

```python
# src/modules/treesize/scan/scanner.py
"""Engine selection and scan orchestration."""
import ctypes
import os
import threading
import time
from dataclasses import dataclass

from ..store.node_store import NodeStore
from ..store.rollup import rollup
from .filters import FilterSet
from .mft_reader import MftScanner
from .volume_info import VolumeInfo, get_volume_info
from .walk_scanner import WalkScanner


@dataclass
class ScanResult:
    store: NodeStore
    root: int
    engine: str
    node_count: int
    excluded: int
    volume_info: VolumeInfo | None
    elapsed: float


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _drive_letter(target: str) -> str | None:
    """Return the drive letter if target names a whole drive, else None."""
    stripped = target.rstrip("\\/")
    if len(stripped) == 2 and stripped[1] == ":" and stripped[0].isalpha():
        return stripped[0]
    return None


class Scanner:
    def __init__(self, target: str, filters: FilterSet | None = None,
                 charge_all_hardlinks: bool = False) -> None:
        self.target = target
        self.filters = filters or FilterSet()
        self.charge_all_hardlinks = charge_all_hardlinks
        self._resume = threading.Event()
        self._resume.set()

    def pause(self) -> None:
        self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def _wait_if_paused(self) -> None:
        self._resume.wait()

    def select_engine(self) -> str:
        letter = _drive_letter(self.target)
        if letter and _is_admin() and get_volume_info(letter) is not None:
            return "mft"
        return "walk"

    def scan(self, on_batch=None, should_cancel=None) -> ScanResult:
        started = time.monotonic()
        store = NodeStore()
        engine = self.select_engine()
        info = None
        if engine == "mft":
            letter = _drive_letter(self.target)
            info = get_volume_info(letter)
            scanner = MftScanner(letter, info,
                                 charge_all_hardlinks=self.charge_all_hardlinks)
            scanner.scan(store, on_batch=on_batch, should_cancel=should_cancel,
                         wait_if_paused=self._wait_if_paused)
            root = scanner.builder.root
        else:
            cluster = 4096
            letter = _drive_letter(self.target) or os.path.splitdrive(self.target)[0][:1]
            if letter:
                probe = get_volume_info(letter)
                if probe:
                    cluster = probe.bytes_per_cluster
                    info = probe
            scanner = _FilteringWalkScanner(self.target, self.filters, cluster)
            scanner.scan(store, on_batch=on_batch, should_cancel=should_cancel,
                         wait_if_paused=self._wait_if_paused)
            root = scanner.root
        rollup(store)
        return ScanResult(store=store, root=root, engine=engine,
                          node_count=len(store), excluded=self.filters.excluded_count,
                          volume_info=info, elapsed=time.monotonic() - started)


class _FilteringWalkScanner(WalkScanner):
    """WalkScanner that drops filtered entries before they reach the store."""

    def __init__(self, root_path: str, filters: FilterSet, bytes_per_cluster: int) -> None:
        super().__init__(root_path, bytes_per_cluster)
        self.filters = filters

    def scan(self, store, on_batch=None, should_cancel=None,
             wait_if_paused=None, batch_size: int = 500) -> int:
        from collections import deque
        from ..store.node_store import DIR, REPARSE
        from .walk_scanner import list_directory

        self.root = store.add(-1, self.root_path, attrs=DIR)
        queue: deque[tuple[int, str]] = deque([(self.root, self.root_path)])
        batch_start = len(store)
        while queue:
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            node, path = queue.popleft()
            for entry in list_directory(path):
                flags = (DIR if entry.is_dir else 0) | (REPARSE if entry.is_reparse else 0)
                size = 0 if entry.is_dir else entry.size
                if self.filters.excludes(entry.name, size, flags):
                    continue
                idx = store.add(node, entry.name, size=size,
                                alloc=self._alloc_for(size), mtime=entry.mtime,
                                ctime=entry.ctime, atime=entry.atime, attrs=flags)
                if entry.is_dir and not entry.is_reparse:
                    queue.append((idx, os.path.join(path, entry.name)))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
        store.build_child_lists()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_filters.py tests/treesize/test_scanner.py -v`
Expected: PASS, 14 tests (one SKIP when unelevated)

- [ ] **Step 5: Commit**

```bash
git add src/modules/treesize/scan/filters.py src/modules/treesize/scan/scanner.py tests/treesize/test_filters.py tests/treesize/test_scanner.py
git commit -m "feat(treesize): add scan filters and engine orchestration"
```

---

### Task 10: Console verification harness

Proves the engine on a real volume and produces the memory and speed numbers §13 of the spec says to measure before any UI work.

**Files:**
- Create: `tools/treesize_scan.py`
- Test: `tests/treesize/test_console_harness.py`

**Interfaces:**
- Consumes: `Scanner`, `ScanResult`, `NodeStore`.
- Produces: `format_size(n: int) -> str`, `top_children(result, limit) -> list[tuple[str, int, int]]`, `summarize(result) -> str`, `main(argv) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# tests/treesize/test_console_harness.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from treesize_scan import format_size, top_children, summarize, main
from modules.treesize.scan.scanner import Scanner


def test_format_size_picks_a_unit():
    assert format_size(999) == "999 B"
    assert format_size(1536) == "1.5 KB"
    assert format_size(5 * 1024 ** 3) == "5.0 GB"


def test_format_size_handles_zero():
    assert format_size(0) == "0 B"


def test_top_children_sorted_by_size_descending(tmp_path):
    (tmp_path / "small.bin").write_bytes(b"x" * 100)
    (tmp_path / "big.bin").write_bytes(b"x" * 9000)
    result = Scanner(str(tmp_path)).scan()
    rows = top_children(result, limit=5)
    assert [r[0] for r in rows][:2] == ["big.bin", "small.bin"]


def test_top_children_respects_limit(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * (i + 1) * 100)
    result = Scanner(str(tmp_path)).scan()
    assert len(top_children(result, limit=3)) == 3


def test_summarize_reports_engine_and_totals(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 2048)
    text = summarize(Scanner(str(tmp_path)).scan())
    assert "walk" in text
    assert "2.0 KB" in text
    assert "Nodes" in text


def test_main_returns_zero_on_success(tmp_path, capsys):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    assert main([str(tmp_path)]) == 0
    assert "Nodes" in capsys.readouterr().out


def test_main_returns_error_for_missing_target(capsys):
    assert main(["C:\\definitely-not-real-8271"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_console_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'treesize_scan'`

- [ ] **Step 3: Write minimal implementation**

```python
# tools/treesize_scan.py
"""Console harness for the TreeSize scan engine.

Usage:  .venv\\Scripts\\python.exe tools/treesize_scan.py C:\\ [--top 20]

Not part of the shipped UI. It exists to verify the engine against real
volumes and to produce the speed and memory numbers the design calls for.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from modules.treesize.scan.scanner import Scanner, ScanResult   # noqa: E402

UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = float(n)
    for unit in UNITS[1:]:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def top_children(result: ScanResult, limit: int = 20) -> list[tuple[str, int, int]]:
    store = result.store
    rows = [(store.name(c), store.size[c], store.alloc[c])
            for c in store.children(result.root)]
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:limit]


def summarize(result: ScanResult, limit: int = 20) -> str:
    store = result.store
    root = result.root
    names_mb = len(store.names) / (1024 * 1024)
    per_node = (len(store.names) + len(store) * 52) / max(len(store), 1)
    lines = [
        f"Engine:    {result.engine}",
        f"Elapsed:   {result.elapsed:.2f}s",
        f"Nodes:     {result.node_count:,}",
        f"Size:      {format_size(store.size[root])}",
        f"Allocated: {format_size(store.alloc[root])}",
        f"Files:     {store.file_count[root]:,}",
        f"Folders:   {store.folder_count[root]:,}",
        f"Excluded:  {result.excluded:,}",
        f"Names:     {names_mb:.1f} MB blob, ~{per_node:.0f} bytes/node",
    ]
    if result.volume_info:
        lines.append(f"Cluster:   {result.volume_info.bytes_per_cluster:,} bytes")
    if result.node_count and result.elapsed > 0:
        lines.append(f"Rate:      {result.node_count / result.elapsed:,.0f} nodes/s")
    lines.append("")
    lines.append(f"Top {limit} under {store.name(root)}:")
    for name, size, alloc in top_children(result, limit):
        lines.append(f"  {format_size(size):>10}  {format_size(alloc):>10}  {name}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TreeSize engine console harness")
    parser.add_argument("target", help="drive (C:\\) or directory path")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--exclude", action="append", default=[],
                        help="glob to exclude, repeatable")
    args = parser.parse_args(argv)

    if not os.path.exists(args.target):
        print(f"error: target does not exist: {args.target}", file=sys.stderr)
        return 1

    from modules.treesize.scan.filters import FilterSet
    filters = FilterSet(exclude_globs=tuple(args.exclude))
    result = Scanner(args.target, filters=filters).scan()
    print(summarize(result, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python.exe -m pytest tests/treesize/test_console_harness.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Run the full suite and a real scan**

```bash
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe tools/treesize_scan.py C:\Windows\System32 --top 10
```

Expected: all tests pass; the harness prints a summary with a plausible size for
System32 and a bytes/node figure near the 104-byte measured budget in spec §4.1.

Then, in an **elevated** shell, confirm the fast path:

```bash
.venv\Scripts\python.exe tools/treesize_scan.py C:\ --top 10
```

Expected: `Engine: mft`, a node count near the 460,840 files / 111,283 folders in
spec §1.1, and `Size` well above `Allocated` because of sparse and compressed files.
Record the elapsed time and bytes/node — these are the phase-1 acceptance numbers.

- [ ] **Step 6: Commit**

```bash
git add tools/treesize_scan.py tests/treesize/test_console_harness.py
git commit -m "feat(treesize): add console verification harness for the scan engine"
```

---

## Phase 1 Acceptance

- `.venv\Scripts\python.exe -m pytest -q` green, including the 160 pre-existing tests.
- Unelevated scan of a directory tree produces correct totals via the walk engine.
- Elevated scan of `C:\` selects the MFT engine and reports a total near the values in spec §1.1.
- Measured bytes/node within range of the 104-byte measured budget (74 fixed + ~30 name); if materially above, that is a finding to resolve before phase 2 builds four consumers on the store.

## Deferred to later phases, deliberately

- Threading the walk scanner (Task 8 note) — optimize once the harness can measure it.
- `$ATTRIBUTE_LIST` spill following: Task 5 ignores extension records rather than merging them. Correct for size totals in the common case; revisit if the elevated scan's totals diverge from Pro's.
- Owner SID resolution: `security_id` is stored raw; mapping it through `$Secure` to a readable name belongs with the Users view in phase 3.
- `ReadDirectoryChangesW` watcher, `$MFT` fragmentation across a non-contiguous run list beyond the first extent, and remote targets.
