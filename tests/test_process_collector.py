from unittest.mock import patch, MagicMock
from modules.process_explorer.process_collector import ProcessCollector, build_snapshot, diff_snapshots


def _mock_proc(pid, name, ppid=0, user="testuser", status="running",
               exe="", cmdline="", cpu=0.0, rss=0, vms=0):
    p = MagicMock()
    p.info = {
        "pid": pid, "name": name, "ppid": ppid, "username": user,
        "status": status, "exe": exe, "cmdline": cmdline,
        "cpu_percent": cpu, "memory_info": MagicMock(rss=rss, vms=vms),
        "io_counters": None,
    }
    return p


def test_build_snapshot_returns_dict_keyed_by_pid():
    procs = [_mock_proc(4, "System"), _mock_proc(100, "chrome.exe", ppid=4)]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs):
        snapshot = build_snapshot(set())
    assert 4 in snapshot
    assert 100 in snapshot
    assert snapshot[100].parent_pid == 4


def test_build_snapshot_marks_system_process():
    procs = [_mock_proc(4, "System", user="SYSTEM")]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs):
        snapshot = build_snapshot(set())
    assert snapshot[4].is_system is True


def test_diff_added():
    old = {}
    new_procs = [_mock_proc(100, "chrome.exe")]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=new_procs):
        new = build_snapshot(set())
    added, removed, changed = diff_snapshots(old, new)
    assert 100 in added
    assert removed == []
    assert changed == []


def test_diff_removed():
    old_procs = [_mock_proc(100, "chrome.exe")]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=old_procs):
        old = build_snapshot(set())
    new = {}
    added, removed, changed = diff_snapshots(old, new)
    assert added == []
    assert 100 in removed
    assert changed == []


def test_diff_changed_metrics():
    procs = [_mock_proc(100, "chrome.exe", cpu=1.0)]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs):
        old = build_snapshot(set())
    procs2 = [_mock_proc(100, "chrome.exe", cpu=50.0)]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs2):
        new = build_snapshot(set())
    added, removed, changed = diff_snapshots(old, new)
    assert added == []
    assert removed == []
    assert 100 in changed
