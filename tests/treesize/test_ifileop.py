"""Spec 7.1's PRIMARY implementation: IFileOperation through pywin32.

Only the `SHFileOperationW` fallback was ever built, so the clone had no
per-item progress and no per-item errors -- that call returns ONE code for a
whole batch, so "delete these 4,000 files" either worked or did not, with no
way to say which ones failed.

These tests drive REAL COM against REAL files, because an injected seam is
exactly what hid two fatal watcher bugs in this module. They only ever delete
inside pytest's tmp_path, and they never pass recycle=True: recycling a temp
file would put it in the developer's actual Recycle Bin, and a test suite has
no business leaving things there.
"""
import os

import pytest

from modules.treesize.actions import ifileop


requires_com = pytest.mark.skipif(not ifileop.available(),
                                  reason="pywin32 COM shell is unavailable")


# ---- the HRESULT sign trap ---------------------------------------------

def test_a_nonzero_hresult_is_not_a_failure():
    """The copy engine reports SUCCESS as COPYENGINE_S_DONT_PROCESS_CHILDREN,
    0x00270008 -- which is what an ordinary delete actually returns. Testing
    `hr != 0` marks every successful item as failed."""
    assert ifileop._failed(0x00270008) is False
    assert ifileop._failed(0) is False
    assert ifileop._failed(None) is False


def test_the_sign_bit_is_a_failure():
    assert ifileop._failed(0x80070005) is True      # E_ACCESSDENIED
    assert ifileop._failed(-2147024891) is True     # the same, signed


# ---- long paths ---------------------------------------------------------

def test_the_long_path_prefix_is_stripped():
    r"""SHCreateItemFromParsingName cannot parse \\?\. The long-path handling
    the spec credits IFileOperation with is internal to it."""
    assert ifileop._normalise(r"\\?\C:\x\y.txt") == r"C:\x\y.txt"
    assert ifileop._normalise(r"\\?\UNC\server\share\f") == r"\\server\share\f"
    assert ifileop._normalise(r"C:\plain\path") == r"C:\plain\path"


# ---- real COM, real files ----------------------------------------------

@requires_com
def test_it_really_deletes(tmp_path):
    target = tmp_path / "gone.txt"
    target.write_bytes(b"x" * 100)
    outcome = ifileop.run([str(target)])
    assert outcome.ok, outcome.error
    assert not target.exists()


@requires_com
def test_every_item_is_reported_individually(tmp_path):
    """The whole point. SHFileOperationW cannot produce this list."""
    paths = []
    for i in range(4):
        p = tmp_path / f"f{i}.txt"
        p.write_bytes(b"y" * 10)
        paths.append(str(p))

    outcome = ifileop.run(paths)
    assert outcome.ok, outcome.error
    assert len(outcome.items) == 4
    assert {os.path.basename(i.path) for i in outcome.items} == {
        "f0.txt", "f1.txt", "f2.txt", "f3.txt"}
    assert all(i.ok for i in outcome.items)
    assert outcome.failures == []


@requires_com
def test_progress_is_reported(tmp_path):
    """The other thing the spec names and the fallback cannot do."""
    for i in range(3):
        (tmp_path / f"p{i}.txt").write_bytes(b"z" * 10)
    seen = []
    outcome = ifileop.run([str(tmp_path / f"p{i}.txt") for i in range(3)],
                          on_progress=lambda done, total: seen.append((done, total)))
    assert outcome.ok, outcome.error
    assert seen, "no progress callbacks arrived"
    assert seen[-1][0] == seen[-1][1], "progress did not finish at 100%"


@requires_com
def test_a_broken_progress_callback_does_not_abort_the_delete(tmp_path):
    """A consumer bug must cost a progress bar, never the operation."""
    target = tmp_path / "still-goes.txt"
    target.write_bytes(b"x" * 10)

    def explode(done, total):
        raise ValueError("consumer bug")

    outcome = ifileop.run([str(target)], on_progress=explode)
    assert outcome.ok, outcome.error
    assert not target.exists()


@requires_com
def test_it_really_moves(tmp_path):
    source = tmp_path / "movable.txt"
    source.write_bytes(b"m" * 40)
    destination = tmp_path / "dest"
    destination.mkdir()

    outcome = ifileop.run([str(source)], operation="move",
                          destination=str(destination))
    assert outcome.ok, outcome.error
    assert not source.exists()
    assert (destination / "movable.txt").read_bytes() == b"m" * 40


@requires_com
def test_a_move_with_no_destination_is_refused(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_bytes(b"k")
    outcome = ifileop.run([str(target)], operation="move")
    assert outcome.ok is False
    assert target.exists(), "a refused move must not have deleted anything"


@requires_com
def test_a_directory_goes_with_its_contents(tmp_path):
    folder = tmp_path / "tree"
    (folder / "inner").mkdir(parents=True)
    (folder / "inner" / "deep.txt").write_bytes(b"d" * 20)
    outcome = ifileop.run([str(folder)])
    assert outcome.ok, outcome.error
    assert not folder.exists()


@requires_com
def test_a_missing_path_is_reported_rather_than_raising(tmp_path):
    """The scan is a snapshot; the disk moves on. This must come back as a
    result, not an exception."""
    outcome = ifileop.run([str(tmp_path / "never-existed.txt")])
    assert outcome.ok is False


# ---- graceful degradation ----------------------------------------------

def test_without_pywin32_it_reports_unavailable_rather_than_raising(monkeypatch):
    """file_ops falls back to ctypes on this. It must be a clean False."""
    monkeypatch.setattr(ifileop, "_com", lambda: None)
    assert ifileop.available() is False
    outcome = ifileop.run(["C:\\anything"])
    assert outcome.ok is False and "unavailable" in outcome.error


# ---- file_ops routes through it as PRIMARY -----------------------------

class _FakeOutcome:
    def __init__(self, ok=True, aborted=False, items=(), error=""):
        self.ok, self.aborted, self.items, self.error = ok, aborted, list(items), error

    @property
    def failures(self):
        return [i for i in self.items if not i.ok]


def _plan(tmp_path, name="t.bin"):
    from modules.treesize.actions.file_ops import plan
    target = tmp_path / name
    target.write_bytes(b"x" * 8)
    return plan("Recycle", [(str(target), 8)]), target


def test_file_ops_prefers_ifileoperation(tmp_path, monkeypatch):
    """Spec 7.1 calls it the primary implementation. It was never called."""
    from modules.treesize.actions import file_ops
    seen = {}

    def fake_run(paths, **kwargs):
        seen["paths"] = list(paths)
        seen.update(kwargs)
        return _FakeOutcome(ok=True, items=[ifileop.ItemResult(paths[0], 0, True)])

    monkeypatch.setattr(file_ops.ifileop, "available", lambda: True)
    monkeypatch.setattr(file_ops.ifileop, "run", fake_run)
    monkeypatch.setattr(file_ops.ctypes, "windll",
                        _boom("the ctypes fallback must not be reached"))

    pf, target = _plan(tmp_path)
    ok, message = file_ops.execute(pf, recycle=True)
    assert ok, message
    assert seen["paths"] == [str(target)]
    assert seen["recycle"] is True


def test_recycle_reaches_the_com_layer_as_a_flag(tmp_path, monkeypatch):
    from modules.treesize.actions import file_ops
    seen = {}
    monkeypatch.setattr(file_ops.ifileop, "available", lambda: True)
    monkeypatch.setattr(file_ops.ifileop, "run",
                        lambda paths, **kw: (seen.update(kw),
                                             _FakeOutcome(items=[ifileop.ItemResult(
                                                 paths[0], 0, True)]))[1])
    pf, _ = _plan(tmp_path)
    file_ops.execute(pf, recycle=False)
    assert seen["recycle"] is False


def test_a_partial_failure_is_reported_per_item(tmp_path, monkeypatch):
    """THE reason spec 7.1 prefers this interface. SHFileOperationW returns
    one code for the whole batch, so a run that deleted 3 of 4 could only be
    reported as total failure -- wrong, and useless to the person deciding
    what to do next."""
    from modules.treesize.actions import file_ops
    items = [ifileop.ItemResult(r"C:\worked.bin", 0, True),
             ifileop.ItemResult(r"C:\denied.bin", 0x80070005, False)]
    monkeypatch.setattr(file_ops.ifileop, "available", lambda: True)
    monkeypatch.setattr(file_ops.ifileop, "run",
                        lambda paths, **kw: _FakeOutcome(ok=False, items=items))
    pf, _ = _plan(tmp_path)
    ok, message = file_ops.execute(pf, recycle=True)
    assert ok is False
    assert "1 failed" in message
    assert r"C:\denied.bin" in message
    assert "80070005" in message
    assert "1 item(s)" in message, "the ones that DID succeed must be counted"


def test_an_unavailable_com_layer_falls_back_to_ctypes(tmp_path, monkeypatch):
    """This module is an upgrade to the primary path, never a new way to fail."""
    from modules.treesize.actions import file_ops
    called = {}

    def fake_shell(pointer):
        called["yes"] = True
        return 0

    monkeypatch.setattr(file_ops.ifileop, "available", lambda: False)
    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(fake_shell))
    pf, _ = _plan(tmp_path)
    ok, message = file_ops.execute(pf, recycle=True)
    assert ok, message
    assert called.get("yes"), "the fallback was not used"


def test_a_cancelled_operation_is_reported(tmp_path, monkeypatch):
    from modules.treesize.actions import file_ops
    monkeypatch.setattr(file_ops.ifileop, "available", lambda: True)
    monkeypatch.setattr(file_ops.ifileop, "run",
                        lambda paths, **kw: _FakeOutcome(
                            ok=False, aborted=True,
                            items=[ifileop.ItemResult(paths[0], 0, True)]))
    pf, _ = _plan(tmp_path)
    ok, message = file_ops.execute(pf, recycle=True)
    assert ok is False and "cancelled" in message


class _FakeShell32:
    def __init__(self, fn):
        self.SHFileOperationW = fn


class _FakeWindll:
    def __init__(self, fn):
        self.shell32 = _FakeShell32(fn)


def _boom(why):
    def explode(*_a, **_k):
        raise AssertionError(why)
    return _FakeWindll(explode)


def test_per_item_failures_beat_the_aborted_flag(tmp_path, monkeypatch):
    """The shell sets GetAnyOperationsAborted whenever it stops early, and a
    locked file is the commonest way that happens. Checking aborted FIRST
    replaced "these 3 worked, this 1 is in use" with a bare "cancelled" --
    the precise failure mode per-item reporting exists to remove.

    Found by locking a real file and running it. The faked outcomes above
    could not produce this combination, which is the whole argument for not
    trusting an injected seam.
    """
    from modules.treesize.actions import file_ops
    items = [ifileop.ItemResult(r"C:\worked.bin", 0, True),
             ifileop.ItemResult(r"C:\locked.bin", 0x80270027, False)]
    monkeypatch.setattr(file_ops.ifileop, "available", lambda: True)
    monkeypatch.setattr(file_ops.ifileop, "run",
                        lambda paths, **kw: _FakeOutcome(
                            ok=False, aborted=True, items=items))
    pf, _ = _plan(tmp_path)
    ok, message = file_ops.execute(pf, recycle=False)
    assert ok is False
    assert "cancelled" not in message
    assert "locked.bin" in message and "80270027" in message


def test_a_clean_cancellation_still_says_cancelled(tmp_path, monkeypatch):
    """Aborted with nothing failed is a real cancellation, and must read as
    one rather than as a silent success."""
    from modules.treesize.actions import file_ops
    monkeypatch.setattr(file_ops.ifileop, "available", lambda: True)
    monkeypatch.setattr(file_ops.ifileop, "run",
                        lambda paths, **kw: _FakeOutcome(
                            ok=False, aborted=True,
                            items=[ifileop.ItemResult(paths[0], 0, True)]))
    pf, _ = _plan(tmp_path)
    ok, message = file_ops.execute(pf, recycle=False)
    assert ok is False and "cancelled" in message
