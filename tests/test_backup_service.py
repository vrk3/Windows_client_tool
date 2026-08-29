# tests/test_backup_service.py
import sqlite3
import winreg
from unittest.mock import patch, MagicMock

import pytest
from core.backup_service import BackupService, StepRecord, RestoreResult, RestorePointInfo


@pytest.fixture
def svc(tmp_path):
    s = BackupService(data_dir=str(tmp_path))
    yield s
    s.close()


def test_create_restore_point_returns_32char_hex(svc, tmp_path):
    rp_id = svc.create_restore_point("Test backup", "Tweaks")
    assert isinstance(rp_id, str) and len(rp_id) == 32


def test_create_restore_point_creates_subfolders(svc, tmp_path):
    svc.create_restore_point("My backup", "Cleanup")
    backup_dir = tmp_path / "backups"
    dirs = [d for d in backup_dir.iterdir() if d.is_dir()]
    assert len(dirs) == 1
    assert (dirs[0] / "manifest.json").exists()
    for sub in ("registry", "services", "appx", "files"):
        assert (dirs[0] / sub).is_dir()


def test_record_steps_counted_in_list(svc):
    rp_id = svc.create_restore_point("Test", "Tweaks")
    steps = [
        StepRecord("registry", r"HKLM\SOFTWARE\Test", None, 0),
        StepRecord("service", "DiagTrack", 2, 4),
    ]
    svc.record_steps("tweak_disable_telemetry", steps, rp_id)
    points = svc.list_restore_points()
    assert len(points) == 1
    assert points[0].step_count == 2
    assert points[0].label == "Test"
    assert points[0].module == "Tweaks"


def test_list_restore_points_newest_first(svc):
    svc.create_restore_point("First", "Tweaks")
    svc.create_restore_point("Second", "Cleanup")
    points = svc.list_restore_points()
    assert points[0].label == "Second"
    assert points[1].label == "First"


def test_restore_result_dataclass():
    r = RestoreResult(success=True, partial=False, failed_steps=[], errors=[])
    assert r.success is True
    assert r.partial is False


def test_restore_point_info_dataclass():
    info = RestorePointInfo(id="abc", label="x", created_at="2026-01-01",
                            module="Tweaks", status="active", step_count=3)
    assert info.step_count == 3


def test_command_step_revert_is_noop(svc):
    """command steps are non-revertible but return True (not an error)."""
    import sqlite3
    rp_id = svc.create_restore_point("cmd", "Tweaks")
    steps = [StepRecord("command", "sfc /scannow", None, None)]
    svc.record_steps("fix1", steps, rp_id)
    conn = sqlite3.connect(svc._db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id FROM tweak_steps LIMIT 1").fetchone()
    conn.close()
    result = svc.revert_step(row["id"])
    assert result is True


def test_restore_point_all_succeed(svc):
    """restore_point with only command steps → success=True (command steps are always OK)."""
    rp_id = svc.create_restore_point("cmds", "Tweaks")
    svc.record_steps("t1", [StepRecord("command", "echo hi", None, None)], rp_id)
    result = svc.restore_point(rp_id)
    assert result.success is True
    assert result.partial is False


def _first_step_id(svc):
    conn = sqlite3.connect(svc._db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id FROM tweak_steps LIMIT 1").fetchone()
    conn.close()
    return row["id"]


def test_revert_step_registry_writes_before_value_directly(svc):
    """Registry revert must write the recorded before_value straight back via SetValueEx —
    NOT shell out to `reg import` a whole-key .reg export (see revert_step's docstring
    comment: that path silently no-ops on keys that didn't exist pre-tweak, and only
    unwinds the *last* touch when one key is hit by two tweaks in the same session)."""
    rp_id = svc.create_restore_point("reg test", "Tweaks")
    svc.record_steps(
        "t1",
        [StepRecord("registry", r"HKCU\Software\Test", 0, 1,
                    value_name="Val", reg_kind=winreg.REG_DWORD)],
        rp_id,
    )
    step_id = _first_step_id(svc)

    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.CreateKeyEx", return_value=mock_key) as mock_create, \
         patch("winreg.SetValueEx") as mock_set, \
         patch("subprocess.run") as mock_run:
        result = svc.revert_step(step_id)

    assert result is True
    mock_create.assert_called_once_with(winreg.HKEY_CURRENT_USER, "Software\\Test",
                                        access=winreg.KEY_SET_VALUE)
    mock_set.assert_called_once_with(mock_key, "Val", 0, winreg.REG_DWORD, 0)
    mock_run.assert_not_called()  # no `reg import` subprocess


def test_revert_step_registry_deletes_when_no_prior_value(svc):
    """If before_value is None, the tweak created the value from nothing — revert must
    delete it, not write some other placeholder value."""
    rp_id = svc.create_restore_point("reg test 2", "Tweaks")
    svc.record_steps(
        "t1",
        [StepRecord("registry", r"HKCU\Software\Test", None, 1,
                    value_name="NewVal", reg_kind=winreg.REG_DWORD)],
        rp_id,
    )
    step_id = _first_step_id(svc)

    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.DeleteValue") as mock_delete:
        result = svc.revert_step(step_id)

    assert result is True
    mock_delete.assert_called_once_with(mock_key, "NewVal")


def test_revert_step_registry_missing_key_on_delete_is_not_a_failure(svc):
    """Reverting a delete when the key is already gone shouldn't count as an error."""
    rp_id = svc.create_restore_point("reg test 3", "Tweaks")
    svc.record_steps(
        "t1",
        [StepRecord("registry", r"HKCU\Software\Gone", None, 1, value_name="V")],
        rp_id,
    )
    step_id = _first_step_id(svc)
    with patch("winreg.OpenKey", side_effect=FileNotFoundError):
        result = svc.revert_step(step_id)
    assert result is True


def test_revert_tweak_reverts_latest_applied_steps(svc):
    """revert_tweak() targets one tweak's steps directly, without needing its
    restore_point_id — powers the per-row Disable button in the Tweaks tab."""
    rp_id = svc.create_restore_point("Single tweak: X", "Tweaks")
    svc.record_steps(
        "tweak_a",
        [StepRecord("registry", r"HKCU\Software\Test", 0, 1,
                    value_name="Val", reg_kind=winreg.REG_DWORD)],
        rp_id,
    )
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.CreateKeyEx", return_value=mock_key), patch("winreg.SetValueEx"):
        result = svc.revert_tweak("tweak_a")
    assert result.success is True
    assert result.partial is False


def test_revert_tweak_no_applied_steps_is_a_failure(svc):
    """Disabling a tweak that was never applied (or already reverted) is an
    explicit failure, not a silent no-op."""
    result = svc.revert_tweak("never_applied")
    assert result.success is False
    assert result.errors


def test_revert_tweak_only_touches_most_recent_session(svc):
    """A tweak applied twice (two separate sessions, never reverted in between) —
    revert_tweak() should only unwind the latest apply, leaving the older
    session's steps untouched."""
    rp_old = svc.create_restore_point("Single tweak: X (first)", "Tweaks")
    svc.record_steps(
        "tweak_b",
        [StepRecord("registry", r"HKCU\Software\Test", 0, 1, value_name="Val")],
        rp_old,
    )
    rp_new = svc.create_restore_point("Single tweak: X (second)", "Tweaks")
    svc.record_steps(
        "tweak_b",
        [StepRecord("registry", r"HKCU\Software\Test", 1, 2, value_name="Val")],
        rp_new,
    )

    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.CreateKeyEx", return_value=mock_key), patch("winreg.SetValueEx"):
        result = svc.revert_tweak("tweak_b")
    assert result.success is True

    conn = sqlite3.connect(svc._db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT restore_point_id, reverted_at FROM tweak_steps WHERE tweak_id='tweak_b'"
        " ORDER BY rowid"
    ).fetchall()
    conn.close()
    assert rows[0]["restore_point_id"] == rp_old and rows[0]["reverted_at"] is None
    assert rows[1]["restore_point_id"] == rp_new and rows[1]["reverted_at"] is not None


def test_record_steps_hex_encodes_binary_before_value(svc):
    """REG_BINARY before/after values come back from winreg as bytes, which json.dumps
    can't serialize — record_steps must hex-encode them instead of crashing."""
    rp_id = svc.create_restore_point("bin test", "Tweaks")
    steps = [StepRecord("registry", r"HKLM\SOFTWARE\Test", b"\x01\x02", b"\x03\x04",
                        value_name="Blob", reg_kind=winreg.REG_BINARY)]
    svc.record_steps("t1", steps, rp_id)  # must not raise
    points = svc.list_restore_points()
    assert points[0].step_count == 1


# --- a backup that did not happen must not look like one --------------------
#
# Seen in tools/_roundtrip_elevated.log, from the elevated LLMNR write:
#
#     reg export failed (rc=1) for
#     HKLM\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient
#
# ...and the apply carried straight on. `backup_registry_key` logged a warning
# and returned None, so nothing upstream could tell these two apart:
#
#   * the key does not exist yet -- nothing to export, and the way back is
#     "delete the value again". Perfectly fine.
#   * the export was REFUSED -- there is no way back at all, and we are about
#     to change the machine anyway.
#
# Measured here: `reg export` answers rc=1 with empty stdout for BOTH a
# missing key and HKLM\SECURITY (denied), so the return code cannot tell them
# apart either. Ask the registry whether the key is there.

def test_backing_up_a_key_that_does_not_exist_is_not_a_failure(svc):
    """Nothing to export, and that is a complete answer: the way back from
    creating a value is deleting it again."""
    rp_id = svc.create_restore_point("absent key", "Tweaks")
    outcome = svc.backup_registry_key(
        r"HKLM\SOFTWARE\NoSuchKeyAnywhere\Really", rp_id)
    assert outcome.ok is True
    assert outcome.exported is False
    assert "does not exist" in outcome.reason.lower()


def test_a_refused_export_is_reported_as_a_failure(svc):
    """The key IS there and the export still failed -- so there is no way back
    and it has to say so, not log a warning nobody reads."""
    rp_id = svc.create_restore_point("denied key", "Tweaks")
    with patch("core.backup_service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout=b"", stderr=b"ERROR: Access is denied.")
        outcome = svc.backup_registry_key(
            r"HKCU\Software\Microsoft\Windows\CurrentVersion", rp_id)
    assert outcome.ok is False
    assert outcome.exported is False
    assert "access is denied" in outcome.reason.lower()


def test_a_real_export_reports_the_file_it_wrote(svc):
    """A key that exists and can be read: the .reg lands, and the outcome says
    so. This is the only case that leaves a way back on disk."""
    import os
    rp_id = svc.create_restore_point("real key", "Tweaks")
    outcome = svc.backup_registry_key(
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
        rp_id)
    assert outcome.ok is True
    assert outcome.exported is True
    assert os.path.exists(outcome.path), "it claimed an export with no file"
    assert os.path.getsize(outcome.path) > 0


def test_a_backup_never_raises_at_its_callers(svc):
    """Every existing caller ignores the return value, so the old behaviour --
    never raising, whatever happens -- has to hold."""
    rp_id = svc.create_restore_point("ignored", "Tweaks")
    svc.backup_registry_key(r"HKLM\SOFTWARE\NoSuchKeyAnywhere", rp_id)
    svc.backup_registry_key(r"HKLM\SECURITY", rp_id)
