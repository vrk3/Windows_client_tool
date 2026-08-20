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


def test_exclude_predicate_skips_matching_entries(tmp_path):
    (tmp_path / "keep.bin").write_bytes(b"x" * 1000)
    (tmp_path / "drop.tmp").write_bytes(b"y" * 5000)
    store = NodeStore()
    # The predicate gained mtime and path arguments when spec 3.6's age and
    # path-glob rules landed; this lambda ignores them.
    scanner = WalkScanner(
        str(tmp_path),
        exclude=lambda name, size, attrs, mtime=0, path=None: name.endswith(".tmp"))
    scanner.scan(store)
    rollup(store)
    assert store.size[scanner.root] == 1000
    names = {store.name(i) for i in range(len(store))}
    assert "drop.tmp" not in names


def test_exclude_predicate_receives_the_full_path_and_mtime(tmp_path):
    """Spec 3.6's path globs and age rules are unevaluable without these."""
    sub = tmp_path / "node_modules"
    sub.mkdir()
    (sub / "dep.js").write_bytes(b"x" * 100)
    seen = []

    def record(name, size, attrs, mtime=0, path=None):
        seen.append((name, mtime, path))
        return False

    WalkScanner(str(tmp_path), exclude=record).scan(NodeStore())
    by_name = {name: (mtime, path) for name, mtime, path in seen}
    assert "dep.js" in by_name
    mtime, path = by_name["dep.js"]
    assert mtime > 0, "a real FILETIME must reach the predicate"
    assert path.endswith("node_modules\\dep.js")
    assert path.startswith(str(tmp_path))


def test_the_scan_root_carries_its_own_timestamps(tmp_path):
    """Every child gets mtime/ctime/atime from its DirEntry, but the root is
    added before the walk starts and used to get nothing -- so selecting the
    scanned folder showed "Last Modified: —" in the overview and Details."""
    (tmp_path / "a.txt").write_bytes(b"x" * 10)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path))
    scanner.scan(store)
    root = scanner.root
    assert store.mtime[root] > 0
    assert store.ctime[root] > 0
    assert store.atime[root] > 0


def test_a_root_that_cannot_be_stat_ed_still_scans(tmp_path, monkeypatch):
    """A timestamp is decoration; failing the scan over one would not be."""
    import os as os_module

    real_stat = os_module.stat

    def _refuse(path, *args, **kwargs):
        if str(path) == str(tmp_path):
            raise OSError("nope")
        return real_stat(path, *args, **kwargs)

    (tmp_path / "a.txt").write_bytes(b"x")
    monkeypatch.setattr(
        "modules.treesize.scan.walk_scanner.os.stat", _refuse)
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path))
    scanner.scan(store)
    assert store.mtime[scanner.root] == 0
    assert len(store) == 2
