"""Regression tests for review findings 3 and 4: a scan that could not read
everything must say so, instead of returning a plausible smaller number.
"""
import pytest

from modules.treesize.scan.scanner import Scanner
from modules.treesize.scan.volume_info import read_at
from modules.treesize.scan.walk_scanner import WalkScanner, list_directory
from modules.treesize.scan.mft_reader import MftScanner
from modules.treesize.scan.volume_info import VolumeInfo
from modules.treesize.store.node_store import NodeStore

BAD = "C:\\definitely-not-a-real-path-9f3a"


def test_read_at_distinguishes_failure_from_end_of_data():
    """None means the read failed; b'' would mean a legitimate zero-byte read."""
    assert read_at(0, 0, 512) is None


def test_list_directory_reports_why_it_returned_nothing():
    seen = []
    assert list_directory(BAD, on_error=lambda p, why: seen.append((p, why))) == []
    assert len(seen) == 1
    assert seen[0][0] == BAD
    assert seen[0][1]


def test_list_directory_stays_quiet_when_it_succeeds(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x")
    seen = []
    list_directory(str(tmp_path), on_error=lambda p, why: seen.append(p))
    assert seen == []


def test_walk_scanner_records_unreadable_directories():
    store = NodeStore()
    scanner = WalkScanner(BAD)
    scanner.scan(store)
    assert scanner.error_count == 1
    assert scanner.errors[0][0].endswith("9f3a")


def test_clean_walk_reports_complete(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    result = Scanner(str(tmp_path)).scan()
    assert result.complete is True
    assert result.errors == ()
    assert result.error_count == 0


def test_unreadable_target_reports_incomplete():
    result = Scanner(BAD).scan()
    assert result.complete is False
    assert result.error_count == 1


def test_error_list_is_capped_but_the_count_is_not():
    scanner = WalkScanner(BAD)
    for i in range(WalkScanner.MAX_RECORDED_ERRORS + 25):
        scanner._record_error(f"p{i}", "denied")
    assert scanner.error_count == WalkScanner.MAX_RECORDED_ERRORS + 25
    assert len(scanner.errors) == WalkScanner.MAX_RECORDED_ERRORS


def _info():
    return VolumeInfo(bytes_per_sector=512, bytes_per_cluster=4096,
                      bytes_per_record=1024, mft_start_lcn=0,
                      mft_valid_length=8 * 1024 * 1024, total_clusters=1000)


def test_mft_scan_marks_itself_truncated_when_a_read_fails():
    """A failed volume read mid-MFT must not masquerade as end-of-MFT."""
    calls = {"n": 0}

    def reader(offset, length):
        calls["n"] += 1
        return None if calls["n"] > 1 else bytes(length)

    scanner = MftScanner("C", _info(), reader=reader)
    scanner.scan(NodeStore())
    assert scanner.truncated is True


def test_mft_scan_is_not_truncated_when_it_reaches_the_end():
    scanner = MftScanner("C", _info(), reader=lambda offset, length: bytes(length))
    scanner.scan(NodeStore())
    assert scanner.truncated is False
