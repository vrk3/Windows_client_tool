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


def test_excluded_directory_takes_its_whole_subtree_with_it(tmp_path):
    keep = tmp_path / "keep.bin"
    keep.write_bytes(b"x" * 1000)
    junk = tmp_path / "node_modules"
    junk.mkdir()
    (junk / "big.bin").write_bytes(b"y" * 9000)
    result = Scanner(str(tmp_path),
                     filters=FilterSet(exclude_globs=("node_modules",))).scan()
    assert result.store.size[result.root] == 1000


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


def test_on_batch_receives_progress_ranges(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * 10)
    seen = []
    Scanner(str(tmp_path)).scan(on_batch=seen.append)
    assert seen, "on_batch was never called"
    assert all(lo <= hi for lo, hi in seen)


def test_scan_is_repeatable_on_the_same_scanner(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 700)
    s = Scanner(str(tmp_path), filters=FilterSet(exclude_globs=("*.tmp",)))
    first = s.scan()
    second = s.scan()
    assert first.store is not second.store
    assert second.store.size[second.root] == 700


def test_excluded_count_does_not_leak_between_scans(tmp_path):
    (tmp_path / "drop.tmp").write_bytes(b"y" * 10)
    s = Scanner(str(tmp_path), filters=FilterSet(exclude_globs=("*.tmp",)))
    assert s.scan().excluded == 1
    assert s.scan().excluded == 1


@pytest.mark.skipif(
    not ctypes.windll.shell32.IsUserAnAdmin(),
    reason="MFT engine requires elevation",
)
def test_elevated_drive_target_selects_mft_engine():
    assert Scanner("C:\\").select_engine() == "mft"
