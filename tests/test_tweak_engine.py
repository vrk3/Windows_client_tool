# tests/test_tweak_engine.py
import pytest
from unittest.mock import patch, MagicMock, call
from core.backup_service import BackupService, StepRecord


@pytest.fixture
def engine(tmp_path):
    from modules.tweaks.tweak_engine import TweakEngine
    svc = BackupService(data_dir=str(tmp_path))
    eng = TweakEngine(backup_service=svc)
    yield eng
    svc.close()


def _reg_tweak():
    return {
        "id": "test_tweak",
        "name": "Test",
        "requires_admin": True,
        "steps": [
            {"type": "registry", "key": r"HKCU\Software\Test", "value": "Val", "data": 1, "kind": "DWORD"}
        ]
    }


def _svc_tweak():
    return {
        "id": "svc_tweak",
        "name": "Service Test",
        "requires_admin": True,
        "steps": [
            {"type": "service", "name": "TestSvc", "start_type": "disabled"}
        ]
    }


def _cmd_tweak():
    return {
        "id": "cmd_tweak",
        "name": "Cmd",
        "requires_admin": True,
        "steps": [
            {"type": "command", "cmd": "echo test"}
        ]
    }


def test_apply_registry_tweak_succeeds(engine):
    errors = []
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.QueryValueEx", return_value=(0, 4)), \
         patch("winreg.CreateKeyEx", return_value=mock_key), \
         patch("winreg.SetValueEx"):
        result = engine.apply_tweak(_reg_tweak(), rp_id="rp1", on_error=errors.append)
    assert result is True
    assert errors == []


def test_apply_command_tweak_succeeds(engine):
    errors = []
    with patch("subprocess.run"):
        result = engine.apply_tweak(_cmd_tweak(), rp_id="rp1", on_error=errors.append)
    assert result is True


def test_detect_status_applied_registry(engine):
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.QueryValueEx", return_value=(1, 4)):
        status = engine.detect_status(_reg_tweak())
    assert status == "applied"


def test_detect_status_not_applied_registry(engine):
    mock_key = MagicMock()
    mock_key.__enter__ = lambda s: s
    mock_key.__exit__ = MagicMock(return_value=False)
    with patch("winreg.OpenKey", return_value=mock_key), \
         patch("winreg.QueryValueEx", return_value=(0, 4)):
        status = engine.detect_status(_reg_tweak())
    assert status == "not_applied"


def test_detect_status_unknown_on_error(engine):
    with patch("winreg.OpenKey", side_effect=OSError):
        status = engine.detect_status(_reg_tweak())
    assert status == "unknown"


def test_load_definitions_reads_json(tmp_path):
    from modules.tweaks.tweak_engine import TweakEngine
    import json
    data = [{"id": "t1", "name": "T1", "steps": []}]
    f = tmp_path / "test.json"
    f.write_text(json.dumps(data))
    result = TweakEngine.load_definitions(str(f))
    assert result == data
