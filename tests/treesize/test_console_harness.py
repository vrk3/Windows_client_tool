import ctypes
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from treesize_scan import (  # noqa: E402
    bytes_per_node, format_size, main, summarize, top_children,
)
from modules.treesize.scan.scanner import Scanner  # noqa: E402


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


def test_main_honours_exclude_on_the_walk_engine(tmp_path, capsys):
    (tmp_path / "keep.bin").write_bytes(b"x" * 1000)
    (tmp_path / "drop.tmp").write_bytes(b"y" * 8000)
    assert main([str(tmp_path), "--exclude", "*.tmp"]) == 0
    out = capsys.readouterr().out
    assert "drop.tmp" not in out
    assert "Excluded:  1" in out


def test_bytes_per_node_counts_real_column_widths(tmp_path):
    """The 52-byte figure in the plan was wrong; columns measure 74 bytes."""
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    result = Scanner(str(tmp_path)).scan()
    store = result.store
    fixed = sum(getattr(store, c).itemsize for c in (
        "parent", "name_off", "name_len", "size", "alloc", "mtime", "ctime",
        "atime", "attrs", "owner_id", "first_child", "next_sibling",
        "file_count", "folder_count"))
    assert fixed == 74
    assert bytes_per_node(store) >= fixed


def test_exclude_is_honoured_whichever_engine_runs(tmp_path, capsys):
    """Both engines filter now -- the walk drops entries, the MFT prunes after."""
    (tmp_path / "keep.bin").write_bytes(b"x" * 1000)
    (tmp_path / "drop.tmp").write_bytes(b"y" * 8000)
    assert main([str(tmp_path), "--exclude", "*.tmp"]) == 0
    out = capsys.readouterr().out
    assert "drop.tmp" not in out
    assert "keep.bin" in out


def test_summarize_of_an_empty_directory_does_not_divide_by_zero(tmp_path):
    text = summarize(Scanner(str(tmp_path)).scan())
    assert "Nodes:     1" in text


def _fake_result(complete, errors=(), error_count=0):
    """A one-node ScanResult, built directly so formatting is tested in isolation."""
    from modules.treesize.store.node_store import NodeStore, DIR
    from modules.treesize.scan.scanner import ScanResult
    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    store.build_child_lists()
    return ScanResult(store=store, root=root, engine="walk", node_count=1,
                      excluded=0, volume_info=None, elapsed=0.1,
                      complete=complete, errors=errors, error_count=error_count)


def test_summarize_shouts_when_the_scan_was_incomplete():
    text = summarize(_fake_result(False, (("C:\\locked", "Access is denied."),), 1))
    assert "INCOMPLETE SCAN" in text
    assert "LOWER BOUND" in text
    assert "C:\\locked" in text
    assert "Access is denied." in text


def test_summarize_says_nothing_extra_when_the_scan_was_complete():
    text = summarize(_fake_result(True))
    assert "INCOMPLETE" not in text
    assert "Unread" not in text


def test_summarize_caps_the_listed_errors_but_reports_the_full_count():
    errs = tuple((f"C:\\d{i}", "Access is denied.") for i in range(40))
    text = summarize(_fake_result(False, errs, 40))
    assert "40 location(s) could not be read" in text
    assert "and 35 more" in text


@pytest.mark.skipif(
    ctypes.windll.shell32.IsUserAnAdmin(),
    reason="System Volume Information is readable when elevated",
)
def test_main_exits_nonzero_on_a_genuinely_unreadable_target(capsys):
    """C:\\System Volume Information exists but is denied to a normal user.

    Exercises the whole chain for real: FindFirstFileExW failure -> on_error ->
    WalkScanner.errors -> ScanResult.complete -> exit code.
    """
    assert main(["C:\\System Volume Information"]) == 2
    out = capsys.readouterr().out
    assert "INCOMPLETE SCAN" in out
    assert "Access is denied." in out


def test_mft_record_slots_reported_when_geometry_is_known():
    """The elevated run must be able to answer 'did we read the whole MFT?'."""
    from modules.treesize.scan.volume_info import VolumeInfo
    info = VolumeInfo(bytes_per_sector=512, bytes_per_cluster=4096,
                      bytes_per_record=1024, mft_start_lcn=100,
                      mft_valid_length=1024 * 500, total_clusters=1000)
    r = _fake_result(True)
    r.engine = "mft"
    r.volume_info = info
    text = summarize(r)
    assert "500" in text
    assert "record slots" in text


def test_record_slots_not_reported_for_a_walk_scan():
    text = summarize(_fake_result(True))
    assert "record slots" not in text
