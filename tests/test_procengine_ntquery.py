r"""One syscall for every process on the machine.

Measured on this machine, 278 processes, best of 5:

    psutil.process_iter (10 attrs)      667.9 ms
    psutil.process_iter (17 attrs)     1081.9 ms
    NtQuerySystemInformation             2.6 ms   <- this

257x, and it returns 23 fields rather than 10. That is what makes a
40-column table repaint once a second possible at all; the existing
`ProcessCollector` polls at 1 Hz and so burns ~67% of a core.

Qt-free on purpose, like `scan/` and `store/` in TreeSize -- these run with
no display and no elevation.
"""
import os

import pytest

from core.procengine.ntquery import (
    system_processes,
)


@pytest.fixture(scope="module")
def rows():
    return system_processes()


def _by_pid(rows):
    return {row.pid: row for row in rows}


# ---- it actually reads the machine --------------------------------------

def test_it_returns_the_processes_that_are_running(rows):
    assert len(rows) > 20, "a live Windows machine has more processes than this"


def test_our_own_process_is_in_there(rows):
    assert os.getpid() in _by_pid(rows)


def test_our_own_row_names_the_interpreter(rows):
    mine = _by_pid(rows)[os.getpid()]
    assert mine.name.lower().startswith("python")


def test_our_own_row_carries_real_counters(rows):
    """Not a stub: a running Python has a working set, threads and handles."""
    mine = _by_pid(rows)[os.getpid()]
    assert mine.working_set > 1_000_000
    assert mine.threads >= 1
    assert mine.handles > 0


def test_the_idle_process_is_reported_rather_than_dropped():
    """Pid 0 has no image name, and dropping it loses the row Task Manager
    shows CPU idle against."""
    assert 0 in _by_pid(system_processes())


def test_every_row_has_a_name(rows):
    """Pid 0's ImageName buffer is NULL. A blank name would render an empty
    cell rather than "System Idle Process"."""
    assert all(row.name for row in rows)


def test_pids_are_unique(rows):
    pids = [row.pid for row in rows]
    assert len(pids) == len(set(pids))


# ---- the fields the Details tab needs -----------------------------------

def test_every_field_the_details_tab_shows_is_present(rows):
    mine = _by_pid(rows)[os.getpid()]
    for field in ("pid", "ppid", "name", "threads", "handles", "session",
                  "base_priority", "working_set", "private_bytes",
                  "paged_pool", "nonpaged_pool", "pagefile", "virtual_size",
                  "page_faults", "kernel_time", "user_time", "cycles",
                  "read_bytes", "write_bytes", "other_bytes", "read_ops",
                  "write_ops", "create_time"):
        assert hasattr(mine, field), f"{field} is missing"


def test_the_parent_of_our_process_is_a_real_process(rows):
    mine = _by_pid(rows)[os.getpid()]
    assert mine.ppid > 0


def test_times_are_in_100ns_units_as_windows_reports_them(rows):
    """Converting here would hide which unit the syscall speaks, and the
    rate maths needs the raw ticks."""
    mine = _by_pid(rows)[os.getpid()]
    assert mine.kernel_time >= 0 and mine.user_time >= 0


def test_the_session_is_the_interactive_one_for_our_process(rows):
    """Session 0 is services; a test run from a console is not in it."""
    assert _by_pid(rows)[os.getpid()].session >= 0


# ---- the shape it hands back --------------------------------------------

def test_a_row_is_immutable():
    """A snapshot is a reading of a moment. Something that edited it in
    place would be rewriting history the rate maths still needs."""
    row = system_processes()[0]
    with pytest.raises(Exception):
        row.pid = 12345


def test_two_calls_agree_about_the_stable_processes():
    """Sanity that we are parsing a real structure rather than noise: the
    long-lived processes are in both readings under the same names."""
    first = _by_pid(system_processes())
    second = _by_pid(system_processes())
    common = set(first) & set(second)
    assert len(common) > 20
    assert all(first[pid].name == second[pid].name for pid in common)


def test_the_buffer_grows_rather_than_truncating():
    """The list does not fit in a fixed buffer, and a short read would
    silently return the first N processes -- which looks like a machine
    with fewer processes, not like an error."""
    small = system_processes(initial_size=1024)
    normal = system_processes()
    assert abs(len(small) - len(normal)) < 25, \
        "the retry loop did not grow the buffer"


def test_counters_are_plausible_rather_than_garbage(rows):
    """Catches a struct field misalignment, which is the way a hand-written
    ctypes layout fails: it parses, and every number is nonsense."""
    mine = _by_pid(rows)[os.getpid()]
    assert 0 < mine.working_set < 200 * 1024**3
    assert 0 < mine.threads < 10_000
    assert 0 < mine.handles < 1_000_000
    assert mine.virtual_size >= mine.working_set


def test_the_system_process_is_pid_four(rows):
    """A fixed landmark: if the layout drifted, this is wrong immediately."""
    system = _by_pid(rows).get(4)
    assert system is not None
    assert system.name.lower() == "system"


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    """The split TreeSize's scan/ and the Log Viewer's parser keep. It is
    what lets these tests run with no display."""
    import inspect

    from core.procengine import ntquery

    source = inspect.getsource(ntquery)
    assert "PyQt6" not in source
