"""Task Manager's Apps / Background / Windows split.

The grouping is why the Processes tab is readable where the Details tab is
not: twelve `chrome.exe` rows become one "Google Chrome" someone can reason
about.
"""
import os

import pytest

from modules.dashboard.procengine.grouping import (
    APPS, BACKGROUND, GROUP_ORDER, WINDOWS, group_processes,
    is_windows_process, totals, windowed_pids,
)
from modules.dashboard.procengine.snapshot import SnapshotSource


@pytest.fixture(scope="module")
def snapshot():
    source = SnapshotSource()
    source.read()
    return source.read()


def _group(groups, name):
    return next(group for group in groups if group.name == name)


# ---- the window enumeration --------------------------------------------

def test_the_desktop_has_windowed_processes():
    """If this is empty the whole Apps group is empty, so it is worth
    asserting rather than assuming."""
    found = windowed_pids()
    assert found, "no visible top-level windows were found"


def test_every_windowed_pid_has_at_least_one_title():
    for pid, titles in windowed_pids().items():
        assert titles, f"pid {pid} was listed with no window title"


def test_enumerating_windows_twice_agrees_about_most_of_them():
    """Cheap proof it is reading the real window list rather than noise."""
    first = set(windowed_pids())
    second = set(windowed_pids())
    assert len(first & second) >= max(1, len(first) - 3)


# ---- who counts as a Windows process ------------------------------------

def test_a_system_account_process_is_a_windows_process(snapshot):
    class _Fake:
        class details:
            user = "NT AUTHORITY\\SYSTEM"
    assert is_windows_process(_Fake) is True


def test_the_account_is_matched_without_its_domain(snapshot):
    class _Fake:
        class details:
            user = "SYSTEM"
        class raw:
            session = 1
    assert is_windows_process(_Fake) is True


def test_our_own_process_is_not_a_windows_process(snapshot):
    assert is_windows_process(snapshot.by_pid[os.getpid()]) is False


def test_a_refused_process_in_session_zero_is_still_a_windows_process():
    """The signal that carries this unelevated. 135 of 284 processes refuse
    their token here, and every system process is among them -- on the token
    alone the Windows group came out empty and everything piled into
    Background. Session 0 is the non-interactive session and needs no
    permission to read."""
    class _Fake:
        class details:
            user = None
        class raw:
            session = 0
    assert is_windows_process(_Fake) is True


def test_a_refused_process_in_a_user_session_is_not_claimed():
    """Refused plus interactive is not evidence of anything, so it falls to
    Background rather than being guessed into Windows."""
    class _Fake:
        class details:
            user = None
        class raw:
            session = 1
    assert is_windows_process(_Fake) is False


def test_the_split_is_on_the_token_not_the_path():
    """A user program in System32 is not a Windows process, and a
    user-installed service running as SYSTEM is."""
    class _InSystem32:
        class details:
            user = "VRK\\iorda"
        class raw:
            session = 1
    assert is_windows_process(_InSystem32) is False


# ---- the grouping -------------------------------------------------------

def test_the_three_groups_are_in_task_managers_order(snapshot):
    groups = group_processes(snapshot, windows={})
    assert [group.name for group in groups] == list(GROUP_ORDER)


def test_a_windowed_process_becomes_an_app(snapshot):
    pid = os.getpid()
    groups = group_processes(snapshot, windows={pid: ["A window"]})
    assert [entry.pid for entry in _group(groups, APPS).rows] == [pid]


def test_an_app_is_named_by_its_description_where_it_has_one(snapshot):
    """"Google Chrome" beats "chrome.exe" in a list someone reads."""
    windowed = {pid: ["x"] for pid, info in snapshot.by_pid.items()
                if info.details.description}
    if not windowed:
        pytest.skip("no process on this machine has a description")
    groups = group_processes(snapshot, windows=dict(list(windowed.items())[:1]))
    entry = _group(groups, APPS).rows[0]
    assert entry.title != f"{entry.members[0].name}"


def test_an_app_absorbs_child_processes_of_the_same_program(snapshot):
    """A browser is one app and a dozen processes.

    The parent has to have a child of the SAME program: absorbing any child
    at all is the Explorer bug, where everything launched from the shell was
    filed under Windows Explorer.
    """
    parent = next(
        (info for info in snapshot.by_pid.values()
         if any(other.raw.ppid == info.pid
                and other.name.lower() == info.name.lower()
                and other.pid != info.pid
                for other in snapshot.by_pid.values())), None)
    if parent is None:
        pytest.skip("nothing on this machine has a same-program child")

    groups = group_processes(snapshot, windows={parent.pid: ["w"]})
    entry = _group(groups, APPS).rows[0]
    assert len(entry.members) > 1


def test_a_process_absorbed_into_an_app_is_not_listed_again(snapshot):
    """Otherwise the same process is both an app and a background process,
    and the totals double-count it."""
    pid = os.getpid()
    groups = group_processes(snapshot, windows={pid: ["w"]})
    claimed = {info.pid for entry in _group(groups, APPS).rows
               for info in entry.members}
    others = {info.pid for info in _group(groups, BACKGROUND).rows}
    others |= {info.pid for info in _group(groups, WINDOWS).rows}
    assert not (claimed & others)


def test_every_process_lands_in_exactly_one_group(snapshot):
    groups = group_processes(snapshot, windows={})
    seen = []
    for group in groups:
        for row in group.rows:
            seen.append(row.pid)
    assert sorted(seen) == sorted(snapshot.by_pid)


def test_a_window_whose_process_already_ended_is_skipped(snapshot):
    """The window list and the snapshot are two reads; a process can end
    between them."""
    groups = group_processes(snapshot, windows={999_999: ["gone"]})
    assert _group(groups, APPS).rows == []


def test_apps_are_listed_alphabetically(snapshot):
    windowed = {pid: ["w"] for pid in list(snapshot.by_pid)[:8]}
    groups = group_processes(snapshot, windows=windowed)
    titles = [entry.title.lower() for entry in _group(groups, APPS).rows]
    assert titles == sorted(titles)


# ---- totals -------------------------------------------------------------

def test_totals_add_up_across_an_apps_processes(snapshot):
    rows = list(snapshot.by_pid.values())[:5]
    summed = totals(rows)
    assert summed["memory"] == sum(info.raw.working_set_private
                                   for info in rows)


def test_an_unmeasured_rate_contributes_nothing_rather_than_zero(snapshot):
    """Summing None as 0 would understate an app whose processes have just
    started -- which is exactly when someone is watching it."""
    class _NoRate:
        class rates:
            cpu_percent = None
            read_bps = None
            write_bps = None
        class raw:
            working_set_private = 100

    assert totals([_NoRate])["cpu"] == 0.0
    assert totals([_NoRate])["memory"] == 100


def test_totals_of_nothing_are_zero_not_an_error():
    assert totals([])["cpu"] == 0.0


# ---- against the real machine -------------------------------------------

def test_the_real_desktop_produces_all_three_groups(snapshot):
    groups = group_processes(snapshot)
    assert _group(groups, APPS).count > 0, "no apps found on a live desktop"
    assert _group(groups, BACKGROUND).count > 0
    assert _group(groups, WINDOWS).count > 0


def test_grouping_the_real_machine_is_fast_enough_for_a_one_second_tick(
        snapshot):
    import time

    start = time.perf_counter()
    group_processes(snapshot)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"grouping took {elapsed * 1000:.0f} ms"


# ---- Qt-free ------------------------------------------------------------

def test_the_grouping_does_not_import_qt():
    import inspect

    from modules.dashboard.procengine import grouping

    assert "PyQt6" not in inspect.getsource(grouping)


# ---- the rollup rule ----------------------------------------------------

def test_an_app_does_not_absorb_unrelated_children(snapshot):
    """The bug the real machine exposed. Anything launched from the shell
    inherits explorer.exe as its parent, so rolling up plain descendants put
    60 processes and 6.6 GB under "Windows Explorer" -- Steam, WhatsApp and
    Visual Studio among them. A member has to be the same PROGRAM, not just
    a descendant."""
    explorer = next((info for info in snapshot.by_pid.values()
                     if info.name.lower() == "explorer.exe"), None)
    if explorer is None:
        pytest.skip("explorer.exe is not running")

    groups = group_processes(snapshot, windows={explorer.pid: ["Explorer"]})
    entry = _group(groups, APPS).rows[0]

    names = {member.name.lower() for member in entry.members}
    assert names == {"explorer.exe"}, \
        f"Explorer absorbed unrelated processes: {sorted(names)}"


def test_an_app_still_absorbs_its_own_siblings(snapshot):
    """The other half: Chrome's renderers are the same program and must
    roll up, or the tab is as unreadable as the Details tab."""
    chrome = [info for info in snapshot.by_pid.values()
              if info.name.lower() == "chrome.exe"]
    if len(chrome) < 3:
        pytest.skip("Chrome is not running with several processes")

    root = min(chrome, key=lambda info: info.raw.create_time)
    groups = group_processes(snapshot, windows={root.pid: ["Chrome"]})
    entry = _group(groups, APPS).rows[0]
    assert len(entry.members) > 1


def test_two_windows_of_one_program_are_one_app(snapshot):
    """Two Explorer windows are one "Windows Explorer" row, not two rows
    each claiming the name."""
    explorers = [info for info in snapshot.by_pid.values()
                 if info.name.lower() == "explorer.exe"]
    if len(explorers) < 2:
        pytest.skip("only one explorer.exe is running")

    windows = {info.pid: [f"Window {n}"]
               for n, info in enumerate(explorers)}
    groups = group_processes(snapshot, windows=windows)
    titles = [entry.title for entry in _group(groups, APPS).rows]
    assert len(titles) == len(set(titles)), f"duplicate app rows: {titles}"


def test_the_same_program_is_never_counted_under_two_apps(snapshot):
    """Double-counting would overstate the memory of both."""
    groups = group_processes(snapshot)
    seen = []
    for entry in _group(groups, APPS).rows:
        seen.extend(member.pid for member in entry.members)
    assert len(seen) == len(set(seen))
