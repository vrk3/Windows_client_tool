# tests/test_process_actions.py
from unittest.mock import patch, MagicMock
from modules.process_explorer.process_actions import (
    kill_process, kill_tree, suspend_process, resume_process,
    set_priority, set_affinity, PRIORITY_LEVELS,
)


def test_kill_process_success():
    mock_proc = MagicMock()
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        ok, err = kill_process(1234)
    mock_proc.kill.assert_called_once()
    assert ok is True
    assert err == ""


def test_kill_process_no_such_process():
    import psutil
    with patch("modules.process_explorer.process_actions.psutil.Process",
               side_effect=psutil.NoSuchProcess(1234)):
        ok, err = kill_process(1234)
    assert ok is False
    assert "no longer running" in err


def test_set_priority_valid():
    mock_proc = MagicMock()
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        ok, err = set_priority(1234, "normal")
    mock_proc.nice.assert_called_once()
    assert ok is True


def test_set_priority_invalid_level():
    ok, err = set_priority(1234, "turbo_boost")
    assert ok is False
    assert "Unknown priority" in err


def test_set_affinity_success():
    mock_proc = MagicMock()
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        ok, err = set_affinity(1234, [0, 1])
    mock_proc.cpu_affinity.assert_called_once_with([0, 1])
    assert ok is True


def test_priority_levels_complete():
    assert "idle" in PRIORITY_LEVELS
    assert "realtime" in PRIORITY_LEVELS
