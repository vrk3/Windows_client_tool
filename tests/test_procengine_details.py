"""The per-process facts that need opening the process.

Path, command line, user, integrity, elevation, architecture, description --
none of them come from the bulk syscall, and each costs a handle open. Doing
that for 278 processes every tick is the 668 ms the engine exists to avoid.

So they are COLD: resolved once and cached for the life of the process. Only
a newly started process pays.

The rule that matters here is this project's standing one: **a refusal is not
an answer.** A protected process whose path we cannot read has `path=None`
and a reason saying why -- never `""`, which renders as a blank cell and
reads as "this process has no path".
"""
import os
import sys

import pytest

from core.procengine.details import (
    DetailCache, ProcessDetails, resolve,
)
from core.procengine.ntquery import system_processes


def _create_time(pid):
    for row in system_processes():
        if row.pid == pid:
            return row.create_time
    raise AssertionError(f"pid {pid} is not running")


MY_PID = os.getpid()


# ---- resolving our own process, which we are allowed to read ------------

@pytest.fixture(scope="module")
def mine():
    return resolve(MY_PID)


def test_our_own_path_is_the_interpreter(mine):
    assert mine.path is not None, mine.path_error
    assert mine.path.lower().endswith(".exe")
    assert os.path.exists(mine.path)


def test_our_own_command_line_mentions_pytest(mine):
    assert mine.cmdline is not None
    assert "pytest" in mine.cmdline.lower() or "python" in mine.cmdline.lower()


def test_our_own_user_is_the_one_running_the_tests(mine):
    assert mine.user is not None
    assert os.environ["USERNAME"].lower() in mine.user.lower()


def test_our_own_integrity_is_reported(mine):
    """Task Manager and Process Explorer both show this, and it is how you
    tell an elevated process from one that merely belongs to an admin."""
    assert mine.integrity in {"Untrusted", "Low", "Medium", "Medium Plus",
                              "High", "System", "Protected"}


def test_whether_we_are_elevated_is_a_definite_answer(mine):
    """True or False -- never None for a process we can open. This is the
    reading the whole pane's admin gating hangs off."""
    assert mine.elevated in (True, False)


def test_our_own_architecture_is_reported(mine):
    assert mine.architecture in {"x64", "x86", "ARM64", "ARM"}


def test_a_signed_system_binary_reports_its_company():
    """Version-info resolution, on a file that definitely carries it."""
    details = resolve(_pid_of("explorer.exe") or MY_PID)
    if details.company is not None:
        assert details.company != ""


def _pid_of(name):
    for row in system_processes():
        if row.name.lower() == name.lower():
            return row.pid
    return None


# ---- a refusal is not an answer -----------------------------------------

def test_a_process_we_cannot_open_says_why_rather_than_going_blank():
    """Pid 4 is System. Unelevated it cannot be opened at all, and even
    elevated its path is not a real file. What must NOT happen is a blank
    cell, which reads as "this process has no path"."""
    details = resolve(4)
    assert details.path is None
    assert details.path_error, "it was refused and said nothing about it"


def test_a_refusal_names_the_reason_in_words():
    details = resolve(4)
    assert len(details.path_error) > 3
    assert not details.path_error.isdigit(), "an error number is not a reason"


def test_a_process_that_is_not_there_is_not_an_exception():
    """A process can end between the snapshot and the resolve; that is the
    normal case, not an error."""
    details = resolve(999_999)
    assert details.path is None
    assert details.path_error


def test_nothing_is_ever_the_empty_string_instead_of_none():
    """The whole rule in one assertion: unknown is None, so a renderer can
    tell "not known" from "known to be empty"."""
    for pid in (4, 999_999, MY_PID):
        details = resolve(pid)
        for field in ("path", "cmdline", "user", "integrity", "description",
                      "company", "architecture"):
            assert getattr(details, field) != "", \
                f"{field} came back as an empty string for pid {pid}"


# ---- the cache ----------------------------------------------------------

def test_the_cache_answers_the_same_thing_twice():
    cache = DetailCache()
    first = cache.get(MY_PID, _create_time(MY_PID))
    second = cache.get(MY_PID, _create_time(MY_PID))
    assert first is second, "it resolved twice; the cache did nothing"


def test_a_reused_pid_is_resolved_again():
    """Windows reuses pids. Serving the old process's path for the new one
    is how a process manager shows you the wrong program's name."""
    cache = DetailCache()
    created = _create_time(MY_PID)
    first = cache.get(MY_PID, created)
    second = cache.get(MY_PID, created + 1)
    assert first is not second


def test_the_cache_forgets_processes_that_ended():
    cache = DetailCache()
    cache.get(MY_PID, _create_time(MY_PID))
    cache.get(999_998, 12345)
    cache.retain({MY_PID})
    assert cache.tracked() == 1


def test_resolving_every_process_is_affordable_once():
    """This is the cold path's whole justification: it is paid once per
    process, not per tick. If a full cold sweep of the machine took longer
    than a few seconds, the design would be wrong."""
    import time

    cache = DetailCache()
    rows = system_processes()
    start = time.perf_counter()
    for row in rows:
        cache.get(row.pid, row.create_time)
    elapsed = time.perf_counter() - start

    assert elapsed < 30.0, \
        f"a cold sweep of {len(rows)} processes took {elapsed:.1f}s"


def test_the_second_sweep_is_effectively_free():
    """The point of the cache, measured rather than assumed."""
    import time

    cache = DetailCache()
    rows = system_processes()
    for row in rows:
        cache.get(row.pid, row.create_time)

    start = time.perf_counter()
    for row in rows:
        cache.get(row.pid, row.create_time)
    elapsed = time.perf_counter() - start

    assert elapsed < 0.05, f"a cached sweep took {elapsed * 1000:.0f} ms"


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from core.procengine import details

    assert "PyQt6" not in inspect.getsource(details)


# ---- the cold budget ----------------------------------------------------

def test_a_budget_caps_how_many_are_resolved_per_sweep():
    """Elevated, a full cold sweep of ~270 processes measures 2,252 ms
    against 8.5 ms warm, so an unbounded first tick leaves a live pane
    blank for over two seconds."""
    from core.procengine.details import DetailCache
    from core.procengine.ntquery import system_processes

    rows = system_processes()
    cache = DetailCache()
    budget = [5]
    for row in rows:
        cache.get(row.pid, row.create_time, budget)
    assert cache.tracked() == 5


def test_what_the_budget_skipped_is_none_not_a_claim():
    from core.procengine.details import DetailCache

    cache = DetailCache()
    skipped = cache.get(os.getpid(), 0, [0])
    assert skipped.path is None and skipped.cmdline is None
    assert skipped.user is None
    # And not recorded as a refusal either -- nothing was attempted.
    assert skipped.path_error is None


def test_a_skipped_process_is_retried_on_the_next_sweep():
    """It must not be cached as unresolved, or it stays blank forever."""
    from core.procengine.details import DetailCache

    cache = DetailCache()
    assert cache.get(os.getpid(), 0, [0]).path is None
    assert cache.tracked() == 0
    assert cache.get(os.getpid(), 0, [1]).path is not None


def test_an_already_cached_process_does_not_spend_budget():
    from core.procengine.details import DetailCache

    cache = DetailCache()
    budget = [1]
    cache.get(os.getpid(), 0, budget)
    assert budget == [0]
    cache.get(os.getpid(), 0, budget)      # cached, costs nothing
    assert budget == [0]


def test_no_budget_resolves_everything():
    from core.procengine.details import DetailCache
    from core.procengine.ntquery import system_processes

    rows = system_processes()[:20]
    cache = DetailCache()
    for row in rows:
        cache.get(row.pid, row.create_time)
    assert cache.tracked() == len(rows)


@pytest.mark.slow
@pytest.mark.real_machine
def test_the_snapshot_source_honours_a_budget():
    from core.procengine.snapshot import SnapshotSource

    source = SnapshotSource()
    first = source.read(cold_budget=10)
    resolved = sum(1 for info in first.by_pid.values()
                   if info.details.path is not None)
    assert resolved <= 10
    # And the rest arrive over later reads rather than never.
    for _ in range(4):
        later = source.read(cold_budget=10)
    grew = sum(1 for info in later.by_pid.values()
               if info.details.path is not None)
    assert grew > resolved
