"""Spec 7.1 / 7.2: file operations, preflight, dry run.

Nothing here deletes anything real. The execute path is exercised only in dry
run or against a stubbed shell call — a test suite that recycles files to prove
recycling works is a test suite that will eventually recycle the wrong thing.
"""
import os


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
    ok, _ = execute(pf, recycle=True, prefer_com=False)
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
    execute(plan("Delete", [(str(target), 1)]), recycle=False, prefer_com=False)
    assert not (seen["flags"] & file_ops.FOF_ALLOWUNDO)


def test_a_failing_shell_call_is_reported_not_swallowed(tmp_path, monkeypatch):
    target = tmp_path / "a.bin"
    target.write_bytes(b"x")
    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(lambda *a: 0x75))
    ok, message = execute(plan("Recycle", [(str(target), 1)]), prefer_com=False)
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


#: These fakes stand in for the ctypes FALLBACK. Tests that use them pass
#: prefer_com=False, because spec 7.1 makes IFileOperation primary and
#: without that flag they would route through real COM and really delete --
#: the recycle one putting a temp file in the developer's Recycle Bin.
class _FakeWindll:
    def __init__(self, fn):
        self.shell32 = _FakeShell32(fn)


def ctypes_cast(pointer):
    """Recover the struct a byref() pointer refers to."""
    import ctypes
    return ctypes.cast(pointer,
                       ctypes.POINTER(file_ops.SHFILEOPSTRUCTW)).contents


# ---- Move (spec 7.1) ----------------------------------------------------

def test_move_hands_the_shell_a_destination(tmp_path, monkeypatch):
    source = tmp_path / "a.bin"
    source.write_bytes(b"x" * 10)
    destination = tmp_path / "elsewhere"
    destination.mkdir()
    seen = {}

    def fake_op(pointer):
        struct = ctypes_cast(pointer)
        seen["func"] = struct.wFunc
        seen["to"] = struct.pTo
        return 0

    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(fake_op))
    pf = plan("Move", [(str(source), 10)])
    ok, message = file_ops.move(pf, str(destination), prefer_com=False)
    assert ok, message
    assert seen["func"] == file_ops.FO_MOVE
    assert seen["to"].startswith(str(destination))


def test_move_refuses_a_destination_inside_what_is_being_moved(tmp_path):
    """Moving a folder into its own subtree is a request the shell answers
    with a bare error code; it is worth catching by name."""
    folder = tmp_path / "src"
    (folder / "deep").mkdir(parents=True)
    pf = plan("Move", [(str(folder), 0)])
    ok, message = file_ops.move(pf, str(folder / "deep"))
    assert not ok
    assert "into itself" in message


def test_move_refuses_a_guarded_destination(tmp_path):
    """The guardrails exist because a path-assembly bug could aim an
    operation at something unrecoverable -- and a move INTO %SystemRoot% is
    exactly as bad as a delete of it."""
    source = tmp_path / "a.bin"
    source.write_bytes(b"x")
    pf = plan("Move", [(str(source), 1)])
    ok, message = file_ops.move(pf, os.environ.get("SystemRoot", r"C:\Windows"))
    assert not ok
    assert "Refused" in message or "refuse" in message.lower()


def test_move_dry_run_changes_nothing(tmp_path, monkeypatch):
    source = tmp_path / "a.bin"
    source.write_bytes(b"x" * 5)
    destination = tmp_path / "to"
    destination.mkdir()

    def explode(_pointer):
        raise AssertionError("a dry run must not reach the shell")

    monkeypatch.setattr(file_ops.ctypes, "windll", _FakeWindll(explode))
    pf = plan("Move", [(str(source), 5)])
    ok, message = file_ops.move(pf, str(destination), dry_run=True)
    assert ok
    assert source.exists()
    assert "Dry run" in message


def test_move_needs_somewhere_to_move_to(tmp_path):
    source = tmp_path / "a.bin"
    source.write_bytes(b"x")
    pf = plan("Move", [(str(source), 1)])
    ok, message = file_ops.move(pf, str(tmp_path / "does-not-exist"))
    assert not ok
    assert "destination" in message.lower()


# ---- Secure erase (spec 7.1) -------------------------------------------

def test_overwrite_replaces_the_contents_and_keeps_the_length(tmp_path):
    target = tmp_path / "secret.bin"
    original = b"the quick brown fox" * 100
    target.write_bytes(original)
    written = file_ops.overwrite_file(str(target), passes=1)
    after = target.read_bytes()
    assert len(after) == len(original), "a shorter file leaves the tail behind"
    assert after != original
    assert written == len(original)


def test_more_passes_write_more(tmp_path):
    target = tmp_path / "secret.bin"
    target.write_bytes(b"z" * 1000)
    assert file_ops.overwrite_file(str(target), passes=3) == 3000


def test_a_read_only_file_is_still_erasable(tmp_path):
    """A read-only attribute is not a security boundary, and leaving such
    files behind unerased is the failure this feature exists to prevent."""
    import stat

    target = tmp_path / "locked.bin"
    target.write_bytes(b"secret data")
    os.chmod(target, stat.S_IREAD)
    try:
        assert file_ops.overwrite_file(str(target), passes=1) == 11
    finally:
        os.chmod(target, stat.S_IWRITE)


def test_secure_erase_removes_what_it_overwrote(tmp_path):
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x" * 64)
    pf = plan("Secure erase", [(str(target), 64)])
    ok, message = file_ops.secure_erase(pf, passes=1)
    assert ok, message
    assert not target.exists()


def test_secure_erase_walks_into_folders(tmp_path):
    folder = tmp_path / "box"
    (folder / "inner").mkdir(parents=True)
    (folder / "a.bin").write_bytes(b"a" * 16)
    (folder / "inner" / "b.bin").write_bytes(b"b" * 16)
    pf = plan("Secure erase", [(str(folder), 32)])
    ok, message = file_ops.secure_erase(pf, passes=1)
    assert ok, message
    assert not folder.exists()


def test_secure_erase_dry_run_leaves_the_file_intact(tmp_path):
    target = tmp_path / "secret.bin"
    target.write_bytes(b"still here")
    pf = plan("Secure erase", [(str(target), 10)])
    ok, message = file_ops.secure_erase(pf, passes=1, dry_run=True)
    assert ok
    assert target.read_bytes() == b"still here"
    assert "Dry run" in message


def test_secure_erase_reports_what_it_could_not_erase(tmp_path, monkeypatch):
    """A file that cannot be overwritten must NOT then be deleted: deleting
    it would report success while leaving the contents recoverable."""
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x" * 16)

    def refuse(path, passes=1):
        raise OSError("locked by another process")

    monkeypatch.setattr(file_ops, "overwrite_file", refuse)
    pf = plan("Secure erase", [(str(target), 16)])
    ok, message = file_ops.secure_erase(pf, passes=1)
    assert not ok
    assert target.exists(), "an un-overwritten file must survive, not vanish"
    assert "locked" in message or "1 item" in message


def test_the_erase_manifest_is_logged_before_anything_is_touched(tmp_path, caplog):
    target = tmp_path / "secret.bin"
    target.write_bytes(b"x" * 8)
    pf = plan("Secure erase", [(str(target), 8)])
    with caplog.at_level("INFO"):
        file_ops.secure_erase(pf, passes=1, dry_run=True)
    assert any("manifest" in record.message.lower() for record in caplog.records)
