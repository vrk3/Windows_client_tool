"""Regression tests for review findings 7 and 11.

Both are cases where the engine trusts something it should check: that a
volume it probed a moment ago is still probeable, and that a parent chain
terminates.
"""
import pytest

from modules.treesize.scan import scanner as scanner_mod
from modules.treesize.scan.scanner import Scanner
from modules.treesize.store.node_store import NodeStore, DIR


def test_volume_disappearing_between_probe_and_scan_falls_back_to_walk(tmp_path, monkeypatch):
    """select_engine() says mft, then the volume stops answering.

    Previously MftScanner(letter, None) raised AttributeError on
    info.bytes_per_record, taking down a scan that could simply have walked.
    """
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    s = Scanner(str(tmp_path))
    monkeypatch.setattr(s, "select_engine", lambda: "mft")
    monkeypatch.setattr(scanner_mod, "get_volume_info", lambda letter: None)

    result = s.scan()
    assert result.engine == "walk"
    assert result.store.size[result.root] == 100


def test_path_of_a_normal_node_is_the_full_chain():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    sub = s.add(root, "Windows", attrs=DIR)
    leaf = s.add(sub, "notepad.exe")
    assert s.path(leaf) == "C:\\Windows\\notepad.exe"


def test_path_terminates_on_a_corrupt_parent_cycle():
    """A cycle must cost a wrong-looking path, never a hung process.

    compute_depths already defends against cycles; path() did not, so a
    corrupt parent pair would spin forever inside a UI thread.
    """
    s = NodeStore()
    a = s.add(-1, "a", attrs=DIR)
    b = s.add(a, "b", attrs=DIR)
    s.parent[a] = b                      # a -> b -> a
    result = s.path(b)
    assert isinstance(result, str)
    assert "b" in result


def test_path_of_a_self_parented_node_terminates():
    s = NodeStore()
    a = s.add(-1, "a", attrs=DIR)
    s.parent[a] = a
    assert s.path(a) == "a"
