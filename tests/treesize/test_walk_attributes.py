"""The walk engine never set the COMPRESSED or SPARSE node flags.

Found by running a real unelevated `C:` scan and disbelieving the flag census:
458,358 nodes across a whole Windows volume reported `compressed 0, sparse 0`.
WinSxS alone makes that impossible.

Not the same thing as spec 3.3's documented deviation. That one is about
`alloc`: "Allocated size is real size rounded up to BytesPerCluster, not a
per-file GetCompressedFileSize call, which would cost more than the walk
itself." That is a COST argument, and it is correct as written.

The flags cost nothing. They are already sitting in `dwFileAttributes` in the
same `WIN32_FIND_DATAW` record the walk reads anyway, so there is no trade to
make -- and the Details view has an Attributes column that renders C for
compressed and S for sparse, which on this engine could never appear.
"""
import subprocess

import pytest

from modules.treesize.scan import walk_scanner
from modules.treesize.scan.walk_scanner import (
    FILE_ATTRIBUTE_COMPRESSED, FILE_ATTRIBUTE_SPARSE_FILE, WalkScanner,
    list_directory,
)
from modules.treesize.store.node_store import COMPRESSED, DIR, NodeStore, SPARSE
from modules.treesize.ui.views.details import _attribute_letters


def test_the_win32_bits_are_the_real_ones():
    """Win32 and node flag words OVERLAP numerically and mean different
    things -- Win32 HIDDEN is 0x2, which is node REPARSE. Ruling F4. Getting
    these two constants wrong would mislabel entries rather than fail."""
    assert FILE_ATTRIBUTE_COMPRESSED == 0x800
    assert FILE_ATTRIBUTE_SPARSE_FILE == 0x200


def test_compressed_and_sparse_are_translated_not_copied():
    """Node COMPRESSED is 0x10 and node SPARSE is 0x20 -- neither equals its
    Win32 counterpart, so this has to be a mapping."""
    assert COMPRESSED != FILE_ATTRIBUTE_COMPRESSED
    assert SPARSE != FILE_ATTRIBUTE_SPARSE_FILE


def _scan_with(monkeypatch, tmp_path, entry):
    monkeypatch.setattr(walk_scanner, "list_directory",
                        lambda path, on_error=None: [entry]
                        if path == str(tmp_path) else [])
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), bytes_per_cluster=4096)
    scanner.scan(store)
    return store, scanner.root


def _entry(**kwargs):
    base = dict(name="f.bin", is_dir=False, is_reparse=False, is_hidden=False,
                is_compressed=False, is_sparse=False,
                size=1000, ctime=0, mtime=0, atime=0)
    base.update(kwargs)
    return walk_scanner.DirEntry(**base)


def test_a_compressed_entry_gets_the_compressed_node_flag(monkeypatch, tmp_path):
    store, root = _scan_with(monkeypatch, tmp_path, _entry(is_compressed=True))
    node = next(store.children(root))
    assert store.attrs[node] & COMPRESSED


def test_a_sparse_entry_gets_the_sparse_node_flag(monkeypatch, tmp_path):
    store, root = _scan_with(monkeypatch, tmp_path, _entry(is_sparse=True))
    node = next(store.children(root))
    assert store.attrs[node] & SPARSE


def test_a_plain_entry_gets_neither(monkeypatch, tmp_path):
    store, root = _scan_with(monkeypatch, tmp_path, _entry())
    node = next(store.children(root))
    assert not store.attrs[node] & (COMPRESSED | SPARSE)


def test_the_flags_reach_the_details_attributes_column(monkeypatch, tmp_path):
    """The point of the whole fix: a compressed file shows a C."""
    store, root = _scan_with(monkeypatch, tmp_path,
                             _entry(is_compressed=True, is_sparse=True))
    node = next(store.children(root))
    letters = _attribute_letters(store.attrs[node])
    assert "C" in letters and "S" in letters


def test_a_compressed_directory_keeps_being_a_directory(monkeypatch, tmp_path):
    """`compact /c` on a folder sets COMPRESSED on the directory itself."""
    store, root = _scan_with(monkeypatch, tmp_path,
                             _entry(name="sub", is_dir=True, is_compressed=True))
    node = next(store.children(root))
    assert store.attrs[node] & DIR and store.attrs[node] & COMPRESSED


# ---- against the real filesystem ---------------------------------------

def test_a_really_compressed_file_is_flagged(tmp_path):
    """Not a fake entry: `compact /c` a real file and walk it.

    The unit tests above go through an injected list_directory, which is
    exactly the kind of seam that hid two fatal watcher bugs. This one reads
    dwFileAttributes off the real volume.
    """
    target = tmp_path / "big.txt"
    target.write_bytes(b"a" * 200_000)          # compresses well
    result = subprocess.run(
        ["compact", "/c", str(target)], capture_output=True, text=True,
        shell=True, timeout=60)
    entry = next(e for e in list_directory(str(tmp_path)) if e.name == "big.txt")
    if not entry.is_compressed:
        pytest.skip(f"volume did not compress the file: {result.stdout.strip()[-200:]}")
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), bytes_per_cluster=4096)
    scanner.scan(store)
    node = next(n for n in scanner_children(store, scanner.root)
                if store.name(n) == "big.txt")
    assert store.attrs[node] & COMPRESSED


def scanner_children(store, root):
    return list(store.children(root))
