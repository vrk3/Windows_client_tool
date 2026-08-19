"""Spec 7.1 / 7.2: file operations, preflight, dry run.

Nothing here deletes anything real. The execute path is exercised only in dry
run or against a stubbed shell call — a test suite that recycles files to prove
recycling works is a test suite that will eventually recycle the wrong thing.
"""
import os

import pytest

from modules.treesize.actions import file_ops
from modules.treesize.actions.file_ops import Preflight, execute, plan


def test_plan_totals_the_targets(tmp_path):
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"x" * 100)
    b.write_bytes(b"y" * 250)
    pf = plan("Recycle", [(str(a), 100), (str(b), 250)])
    assert pf.count == 2
    assert pf.total_bytes == 350
    assert pf.allowed


def test_plan_refuses_dangerous_targets_and_blocks_the_whole_batch(tmp_path):
    """One bad entry stops everything: a batch that half-runs is worse than
    one that does not run."""
    good = tmp_path / "ok.bin"
    good.write_bytes(b"x")
    pf = plan("Recycle", [(str(good), 1), ("C:\\", 0)])
    assert pf.refusals
    assert not pf.allowed


def test_plan_touches_nothing(tmp_path):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x" * 10)
    plan("Recycle", [(str(target), 10)])
    assert target.exists()


def test_preview_is_capped_but_the_count_is_not(tmp_path):
    targets = [(str(tmp_path / f"f{i}.bin"), 1) for i in range(25)]
    pf = plan("Recycle", targets)
    assert pf.count == 25
    assert len(pf.preview) == file_ops.PREVIEW_LIMIT
    assert "and 15 more" in pf.summary()


def test_summary_names_the_operation_and_size(tmp_path):
    pf = plan("Recycle", [(str(tmp_path / "a.bin"), 2048)])
    text = pf.summary()
    assert "Recycle" in text
    assert "2.0 KB" in text


def test_dry_run_changes_nothing_and_says_so(tmp_path):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x" * 10)
    pf = plan("Recycle", [(str(target), 10)])
    ok, message = execute(pf, dry_run=True)
    assert ok
    assert "Dry run" in message
    assert "Nothing was changed" in message
    assert target.exists(), "dry run must not delete"


def test_execute_refuses_a_refused_plan(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(file_ops.ctypes, "windll",
                        _FakeWindll(lambda *a: called.append(a) or 0))
    pf = plan("Recycle", [("C:\\", 0)])
    ok, message = execute(pf)
    assert not ok
    assert not called, "the shell call must never be reached"


def test_execute_refuses_an_empty_plan():
    ok, message = execute(Preflight("Recycle", [], 0))
    assert not ok
    assert "Nothing to do" in message


def test_execute_stops_when_targets_have_vanished(tmp_path, monkeypatch):
    """The scan is a snapshot; the disk moves on. Better to say so than to hand
    the shell a path that no longer exists."""
    called = []
    monkeypatch.setattr(file_ops.ctypes, "windll",
                        _FakeWindll(lambda *a: called.append(a) or 0))
    pf = plan("Recycle", [(str(tmp_path / "gone.bin"), 10)])
    ok, message = execute(pf)
    assert not ok
    assert "no longer exist" in message
    assert not called


def test_recycle_sets_the_undo_flag(tmp_path, monkeypatch):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x")
    seen = {}

    def fake_op(pointer):
        struct = ctypes_cast(pointer)
        seen["flags"] = struct.fFlags
        return 0

    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(fake_op))
    pf = plan("Recycle", [(str(target), 1)])
    ok, _ = execute(pf, recycle=True)
    assert ok
    assert seen["flags"] & file_ops.FOF_ALLOWUNDO, "recycle must be undoable"


def test_permanent_delete_clears_the_undo_flag(tmp_path, monkeypatch):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x")
    seen = {}

    def fake_op(pointer):
        seen["flags"] = ctypes_cast(pointer).fFlags
        return 0

    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(fake_op))
    execute(plan("Delete", [(str(target), 1)]), recycle=False)
    assert not (seen["flags"] & file_ops.FOF_ALLOWUNDO)


def test_a_failing_shell_call_is_reported_not_swallowed(tmp_path, monkeypatch):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x")
    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(lambda *a: 0x75))
    ok, message = execute(plan("Recycle", [(str(target), 1)]))
    assert not ok
    assert "0x75" in message


def test_paths_are_double_null_terminated():
    """SHFileOperationW reads until a double null; a single one truncates the
    list to its first entry."""
    packed = file_ops._double_null(["a", "b"])
    assert packed == "a\0b\0\0"


def test_the_manifest_is_logged_before_execution(tmp_path, caplog):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x" * 5)
    with caplog.at_level("INFO"):
        execute(plan("Recycle", [(str(target), 5)]), dry_run=True)
    assert any("manifest" in r.message for r in caplog.records)
    assert any(str(target) in r.getMessage() for r in caplog.records)


# --- helpers -------------------------------------------------------------

class _FakeShell32:
    def __init__(self, fn):
        self.SHFileOperationW = fn


class _FakeWindll:
    def __init__(self, fn):
        self.shell32 = _FakeShell32(fn)


def ctypes_cast(pointer):
    """Recover the struct a byref() pointer refers to."""
    import ctypes
    return ctypes.cast(pointer,
                       ctypes.POINTER(file_ops.SHFILEOPSTRUCTW)).contents
