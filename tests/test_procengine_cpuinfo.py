"""Per-core CPU load, and what the processor is.

The trap this file exists to pin: **`KernelTime` already includes
`IdleTime`.** Nothing in the API says so. Treat kernel and idle as separate
and a machine sitting at 3% reports as fully loaded -- a graph that is always
pinned at 100% is worse than no graph.
"""
import time

import pytest

from core.procengine.cpuinfo import (
    CoreTimes, core_loads, cpu_static, processor_times, uptime_seconds,
)


# ---- the live reading ---------------------------------------------------

def test_there_is_one_reading_per_logical_processor():
    import os

    assert len(processor_times()) == (os.cpu_count() or 1)


def test_every_core_reports_counters():
    for core in processor_times():
        assert core.idle >= 0
        assert core.kernel >= 0
        assert core.user >= 0


def test_kernel_time_includes_idle_time():
    """The whole point. If this ever stops being true the load maths has to
    change, and this test is what would say so."""
    for core in processor_times():
        assert core.kernel >= core.idle, \
            "kernel time is below idle time; the API changed shape"


def test_counters_only_go_forwards():
    before = processor_times()
    time.sleep(0.2)
    after = processor_times()
    for one, two in zip(before, after):
        assert two.idle >= one.idle
        assert two.kernel >= one.kernel
        assert two.user >= one.user


# ---- turning it into a load ---------------------------------------------

def _core(idle, kernel, user, dpc=0, interrupt=0):
    return CoreTimes(idle=idle, kernel=kernel, user=user, dpc=dpc,
                     interrupt=interrupt, interrupt_count=0)


def test_a_fully_idle_core_reads_as_zero():
    """Kernel moved by exactly as much as idle did, so nothing was done."""
    before = [_core(idle=0, kernel=0, user=0)]
    after = [_core(idle=100, kernel=100, user=0)]
    assert core_loads(before, after)[0].total == pytest.approx(0.0)


def test_a_fully_busy_core_reads_as_one_hundred():
    before = [_core(idle=0, kernel=0, user=0)]
    after = [_core(idle=0, kernel=0, user=100)]
    assert core_loads(before, after)[0].total == pytest.approx(100.0)


def test_a_half_busy_core_reads_as_fifty():
    before = [_core(idle=0, kernel=0, user=0)]
    after = [_core(idle=50, kernel=50, user=50)]
    assert core_loads(before, after)[0].total == pytest.approx(50.0)


def test_kernel_load_excludes_idle():
    """The bug this pins. Kernel moved 100 of which 80 was idle, so 20 was
    real kernel work -- not 100."""
    before = [_core(idle=0, kernel=0, user=0)]
    after = [_core(idle=80, kernel=100, user=0)]
    load = core_loads(before, after)[0]
    assert load.kernel == pytest.approx(20.0)
    assert load.total == pytest.approx(20.0)


def test_user_and_kernel_add_up_to_the_total():
    before = [_core(idle=0, kernel=0, user=0)]
    after = [_core(idle=40, kernel=60, user=40)]
    load = core_loads(before, after)[0]
    assert load.kernel + load.user == pytest.approx(load.total)


def test_two_readings_at_the_same_instant_are_not_a_division_by_zero():
    before = [_core(idle=10, kernel=10, user=10)]
    assert core_loads(before, before)[0].total == 0.0


def test_a_load_is_never_above_one_hundred_or_below_zero():
    before = [_core(idle=0, kernel=0, user=0)]
    after = [_core(idle=0, kernel=0, user=10_000)]
    load = core_loads(before, after)[0]
    assert 0.0 <= load.total <= 100.0


def test_mismatched_reading_lengths_do_not_raise():
    """A core can be parked or hot-added between two readings."""
    assert core_loads([_core(0, 0, 0)], []) == []


# ---- against the real machine -------------------------------------------

def test_the_real_machine_is_not_pinned_at_one_hundred_percent():
    """The symptom of getting the idle arithmetic wrong: an idle machine
    reading as fully loaded on every core."""
    before = processor_times()
    time.sleep(0.4)
    loads = core_loads(before, processor_times())

    assert loads, "no cores were measured"
    average = sum(load.total for load in loads) / len(loads)
    assert average < 95.0, \
        f"every core reads as {average:.0f}% busy; idle is being counted"


def test_the_real_machine_reports_a_plausible_load():
    before = processor_times()
    time.sleep(0.4)
    loads = core_loads(before, processor_times())
    for load in loads:
        assert 0.0 <= load.total <= 100.0


def test_a_busy_loop_moves_at_least_one_core():
    """Proof it measures anything at all, rather than returning zeros."""
    before = processor_times()
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        pass
    loads = core_loads(before, processor_times())
    assert max(load.total for load in loads) > 10.0


# ---- what the processor is ----------------------------------------------

@pytest.fixture(scope="module")
def static():
    return cpu_static()


def test_the_processor_has_a_name(static):
    assert static.name
    assert len(static.name) > 3


def test_the_base_speed_is_plausible(static):
    assert static.base_speed_mhz
    assert 300 < static.base_speed_mhz < 10_000


def test_the_core_counts_are_consistent(static):
    """Logical processors cannot be fewer than physical cores."""
    assert static.cores
    assert static.logical
    assert static.logical >= static.cores


def test_there_is_at_least_one_socket(static):
    assert static.sockets and static.sockets >= 1


def test_the_cache_sizes_are_reported(static):
    """All three levels on any modern desktop part."""
    assert static.l1_cache and static.l2_cache and static.l3_cache
    assert static.l1_cache < static.l3_cache


def test_virtualisation_is_a_definite_answer(static):
    assert static.virtualisation in (True, False)


def test_nothing_static_is_an_empty_string(static):
    """Unknown is None, so a renderer can tell it from a real value."""
    for field in ("name",):
        assert getattr(static, field) != ""


# ---- uptime -------------------------------------------------------------

def test_uptime_is_positive():
    assert uptime_seconds() > 0


def test_uptime_moves_forwards():
    first = uptime_seconds()
    time.sleep(0.2)
    assert uptime_seconds() > first


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from core.procengine import cpuinfo

    assert "PyQt6" not in inspect.getsource(cpuinfo)
