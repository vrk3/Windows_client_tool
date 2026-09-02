"""App history, engine half.

What this pins: per-program CPU time is real data from the bulk syscall,
summed the way the Processes tab sums an app -- and the network/tile
columns Task Manager shows are NOT invented, because a per-process network
counter needs a kernel driver this tool does not ship.
"""
from modules.dashboard.procengine.ntquery import ProcessRaw
from modules.dashboard.procengine.rates import Rates
from modules.dashboard.procengine.snapshot import ProcessInfo
from modules.dashboard.procengine.usage import AppUsage, app_usage


def _raw(pid, name, kernel_time=0, user_time=0, create_time=100):
    return ProcessRaw(
        pid=pid, ppid=0, name=name, threads=1, handles=1, session=1,
        base_priority=8, working_set=0, working_set_private=0,
        peak_working_set=0, private_bytes=0, peak_pagefile=0,
        peak_virtual_size=0, paged_pool=0, nonpaged_pool=0, pagefile=0,
        virtual_size=0, page_faults=0, hard_faults=0,
        kernel_time=kernel_time, user_time=user_time, cycles=0,
        create_time=create_time, read_bytes=0, write_bytes=0,
        other_bytes=0, read_ops=0, write_ops=0, other_ops=0)


class _Details:
    def __init__(self, description=None, path=None):
        self.description = description
        self.path = path


class _Snapshot:
    def __init__(self, entries):
        self.by_pid = {pid: info for pid, info in entries.items()}


def _process(pid, name, **kw):
    return ProcessInfo(raw=_raw(pid, name, **kw), rates=Rates(),
                       details=_Details())


# ---- the rollup ---------------------------------------------------------

def test_processes_of_one_program_sum_into_one_row():
    snap = _Snapshot({
        1: _process(1, "chrome.exe", kernel_time=100, user_time=50),
        2: _process(2, "chrome.exe", kernel_time=200, user_time=25),
    })
    rows = app_usage(snap)
    assert len(rows) == 1
    assert rows[0].process_count == 2
    assert rows[0].cpu_ticks == 375


def test_two_programs_are_two_rows():
    snap = _Snapshot({
        1: _process(1, "chrome.exe"),
        2: _process(2, "code.exe"),
    })
    assert len(app_usage(snap)) == 2


def test_the_most_expensive_program_comes_first():
    snap = _Snapshot({
        1: _process(1, "cheap.exe", user_time=10),
        2: _process(2, "costly.exe", user_time=900),
    })
    rows = app_usage(snap)
    assert rows[0].name == "costly.exe"


def test_the_name_prefers_the_description():
    snap = _Snapshot({1: _process(1, "chrome.exe")})
    snap.by_pid[1] = ProcessInfo(
        raw=_raw(1, "chrome.exe"), rates=Rates(),
        details=_Details(description="Google Chrome"))
    assert app_usage(snap)[0].name == "Google Chrome"


def test_processes_share_an_app_by_path_not_only_name():
    """Two programs of the same name must not merge, but two paths of the
    same program must -- the Processes tab's identity rule."""
    snap = _Snapshot({
        1: ProcessInfo(raw=_raw(1, "helper.exe"), rates=Rates(),
                       details=_Details(path=r"C:\prog\helper.exe")),
        2: ProcessInfo(raw=_raw(2, "helper.exe"), rates=Rates(),
                       details=_Details(path=r"C:\prog\helper.exe")),
    })
    assert len(app_usage(snap)) == 1


def test_every_row_is_an_app_usage():
    snap = _Snapshot({1: _process(1, "anything.exe")})
    assert all(isinstance(row, AppUsage) for row in app_usage(snap))


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from modules.dashboard.procengine import usage

    assert "PyQt6" not in inspect.getsource(usage)
