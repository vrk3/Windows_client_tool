"""Task Manager's Users tab, engine half.

The grouping question: who is costing the machine what. It is answered by
the process token's account -- not guessed from names or paths -- and a
process whose token we cannot read is never filed under somebody else.
"""
import os

import pytest

from core.procengine.rates import Rates
from core.procengine.snapshot import ProcessInfo
from core.procengine.users import (
    UNKNOWN, UserGroup, group_by_user,
)
from core.procengine.ntquery import ProcessRaw


def _raw(pid, name="test.exe", session=1):
    return ProcessRaw(
        pid=pid, ppid=0, name=name, threads=1, handles=1, session=session,
        base_priority=8, working_set=0, working_set_private=1_000_000,
        peak_working_set=0, private_bytes=0, peak_pagefile=0,
        peak_virtual_size=0, paged_pool=0, nonpaged_pool=0, pagefile=0,
        virtual_size=0, page_faults=0, hard_faults=0, kernel_time=0,
        user_time=0, cycles=0, create_time=0, read_bytes=0, write_bytes=0,
        other_bytes=0, read_ops=0, write_ops=0, other_ops=0)


class _Details:
    def __init__(self, user):
        self.user = user
        self.path = None
        self.description = None


class _Snapshot:
    def __init__(self, entries):
        self.by_pid = {pid: info for pid, info in entries.items()}


def _process(pid, user):
    return ProcessInfo(raw=_raw(pid), rates=Rates(),
                       details=_Details(user))


def _snapshot(entries):
    return _Snapshot(entries)


# ---- grouping -----------------------------------------------------------

def test_processes_are_filed_under_their_account():
    snap = _snapshot({
        1: _process(1, "ME"),
        2: _process(2, "ME"),
        3: _process(3, "DOMAIN\\OTHER"),
    })
    groups = group_by_user(snap)
    names = {group.name for group in groups}
    assert "ME" in names and "DOMAIN\\OTHER" in names


def test_each_process_appears_in_exactly_one_group():
    snap = _snapshot({pid: _process(pid, "ME") for pid in range(1, 6)})
    groups = group_by_user(snap)
    total = sum(group.count for group in groups)
    assert total == 5


def test_a_user_row_sums_its_processes():
    snap = _snapshot({1: _process(1, "ME"), 2: _process(2, "ME"),
                      3: _process(3, "OTHER")})
    groups = {group.name: group for group in group_by_user(snap)}
    me = groups["ME"]
    assert me.count == 2
    assert me.totals()["memory"] == 2_000_000


def test_system_accounts_sort_after_people():
    snap = _snapshot({
        1: _process(1, "DOMAIN\\alice"),
        2: _process(2, "NT AUTHORITY\\SYSTEM"),
        3: _process(3, "DOMAIN\\bob"),
    })
    order = [group.name for group in group_by_user(snap)]
    assert order[0].startswith("DOMAIN\\")
    assert order[-1] == "NT AUTHORITY\\SYSTEM"


def test_a_process_without_a_readable_user_is_not_attributed():
    """Unelevated, half the machine refuses its token. Those processes
    must not be charged to the current user -- the row says what it is."""
    snap = _snapshot({
        1: _process(1, "ME"),
        2: ProcessInfo(raw=_raw(2), rates=Rates(),
                       details=_Details(None)),
    })
    groups = group_by_user(snap)
    by_name = {group.name: group for group in groups}
    assert "ME" in by_name and by_name["ME"].count == 1
    assert UNKNOWN in by_name
    assert by_name[UNKNOWN].is_unknown


def test_every_group_is_a_user_group():
    snap = _snapshot({1: _process(1, "ME")})
    groups = group_by_user(snap)
    assert all(isinstance(group, UserGroup) for group in groups)


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from core.procengine import users

    assert "PyQt6" not in inspect.getsource(users)
