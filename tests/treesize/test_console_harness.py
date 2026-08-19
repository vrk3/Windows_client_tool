import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))

from treesize_scan import (  # noqa: E402
    bytes_per_node, filter_warning, format_size, main, summarize, top_children,
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
    assert main(["C:\definitely-not-real-8271"]) == 1


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


def test_filter_warning_only_fires_when_mft_would_ignore_filters():
    assert filter_warning("mft", ("*.tmp",)) != ""
    assert filter_warning("mft", ()) == ""
    assert filter_warning("walk", ("*.tmp",)) == ""


def test_summarize_of_an_empty_directory_does_not_divide_by_zero(tmp_path):
    text = summarize(Scanner(str(tmp_path)).scan())
    assert "Nodes:     1" in text
