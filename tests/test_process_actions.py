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


def test_set_affinity_empty_cores():
    ok, err = set_affinity(1234, [])
    assert ok is False
    assert "at least one" in err


def test_kill_tree_success():
    import psutil
    mock_child = MagicMock()
    mock_child.pid = 5678
    mock_proc = MagicMock()
    mock_proc.children.return_value = [mock_child]
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        with patch("modules.process_explorer.process_actions.kill_process", return_value=(True, "")) as mock_kill:
            ok, errors = kill_tree(1234)
    assert ok is True
    assert errors == []


def test_suspend_resume_not_windows_guard():
    """suspend/resume return False with error message when _ntdll is None."""
    with patch("modules.process_explorer.process_actions._ntdll", None):
        ok, err = suspend_process(1234)
        assert ok is False
        assert "Windows" in err
        ok, err = resume_process(1234)
        assert ok is False
        assert "Windows" in err
