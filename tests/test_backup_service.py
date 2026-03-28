# tests/test_backup_service.py
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
