"""Turning counters into rates.

The kernel reports totals since the process started. Task Manager shows a
rate, and a rate needs two readings and the time between them.

This is where the existing collector is wrong: `ProcessNode` is fed
`disk_read_bps=float(io_counters.read_bytes)` -- a cumulative total under a
per-second name. A process that read a gigabyte an hour ago and nothing since
shows a permanent gigabyte per second.

Time is injected rather than read from the clock, so the arithmetic is
pinned instead of raced.
"""
import os

import pytest

from modules.dashboard.procengine.ntquery import ProcessRaw, system_processes
from modules.dashboard.procengine.rates import HUNDRED_NS, RateTracker

#: One second, in the 100-nanosecond ticks the kernel counts CPU time in.
ONE_SECOND = HUNDRED_NS


def _raw(pid=100, create_time=1, kernel=0, user=0, read=0, write=0, other=0):
    return ProcessRaw(
        pid=pid, ppid=1, name="test.exe", threads=1, handles=1, session=1,
        base_priority=8, working_set=0, working_set_private=0,
        peak_working_set=0, private_bytes=0, peak_pagefile=0,
        peak_virtual_size=0, paged_pool=0,
        nonpaged_pool=0, pagefile=0, virtual_size=0, page_faults=0,
        hard_faults=0, kernel_time=kernel, user_time=user, cycles=0,
        create_time=create_time, read_bytes=read, write_bytes=write,
        other_bytes=other, read_ops=0, write_ops=0, other_ops=0)


# ---- the first reading is not a rate ------------------------------------

def test_the_first_sample_reports_no_rate():
    """`None`, not `0.0`. There is no rate yet, and zero is a claim -- it
    would render "0%" for every process for the first second, which reads
    as an idle machine rather than as "not measured yet"."""
    tracker = RateTracker(cores=1)
    rates = tracker.update([_raw()], now=0.0)
    assert rates[100].cpu_percent is None
    assert rates[100].read_bps is None


def test_a_process_first_seen_later_also_reports_no_rate():
    """A process that starts between two ticks has one reading, like any
    other first reading."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(pid=100)], now=0.0)
    rates = tracker.update([_raw(pid=100), _raw(pid=200)], now=1.0)
    assert rates[200].cpu_percent is None


# ---- cpu ----------------------------------------------------------------

def test_a_process_using_a_whole_core_reads_as_one_core():
    """One core-second of CPU across one wall second, on a one-core
    machine, is 100%."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(kernel=0, user=0)], now=0.0)
    rates = tracker.update([_raw(kernel=0, user=ONE_SECOND)], now=1.0)
    assert rates[100].cpu_percent == pytest.approx(100.0)


def test_cpu_is_scaled_by_the_core_count():
    """Task Manager's percentage is of the whole machine, so a saturated
    single core on a four-core box is 25%."""
    tracker = RateTracker(cores=4)
    tracker.update([_raw(user=0)], now=0.0)
    rates = tracker.update([_raw(user=ONE_SECOND)], now=1.0)
    assert rates[100].cpu_percent == pytest.approx(25.0)


def test_kernel_and_user_time_are_added():
    tracker = RateTracker(cores=1)
    tracker.update([_raw(kernel=0, user=0)], now=0.0)
    rates = tracker.update(
        [_raw(kernel=ONE_SECOND // 2, user=ONE_SECOND // 2)], now=1.0)
    assert rates[100].cpu_percent == pytest.approx(100.0)


def test_a_half_second_gap_doubles_the_rate():
    """The divisor is the real elapsed time, not the intended tick. A tick
    that ran late must not report a process as busier than it was."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(user=0)], now=0.0)
    rates = tracker.update([_raw(user=ONE_SECOND // 2)], now=0.5)
    assert rates[100].cpu_percent == pytest.approx(100.0)


def test_an_idle_process_reads_as_zero_once_it_has_been_measured():
    """Zero IS the answer here, unlike the first sample."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(user=ONE_SECOND)], now=0.0)
    rates = tracker.update([_raw(user=ONE_SECOND)], now=1.0)
    assert rates[100].cpu_percent == 0.0


def test_cpu_is_capped_at_the_whole_machine():
    """Timer granularity can hand back a delta slightly wider than the wall
    clock. 104% in the column reads as a bug in the tool."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(user=0)], now=0.0)
    rates = tracker.update([_raw(user=ONE_SECOND * 2)], now=1.0)
    assert rates[100].cpu_percent == pytest.approx(100.0)


# ---- disk ---------------------------------------------------------------

def test_disk_rates_are_bytes_per_second():
    tracker = RateTracker(cores=1)
    tracker.update([_raw(read=0, write=0)], now=0.0)
    rates = tracker.update([_raw(read=2048, write=1024)], now=2.0)
    assert rates[100].read_bps == pytest.approx(1024.0)
    assert rates[100].write_bps == pytest.approx(512.0)


def test_the_other_io_counter_is_kept_separate():
    """Process Explorer shows it as its own column; folding it into reads
    would overstate disk traffic, since most of it is device control."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(other=0)], now=0.0)
    rates = tracker.update([_raw(other=100)], now=1.0)
    assert rates[100].other_bps == pytest.approx(100.0)


# ---- the things that make this hard -------------------------------------

def test_a_reused_pid_starts_over_rather_than_reporting_a_spike():
    """Windows reuses pids freely. Subtracting the new process's counters
    from the dead one's gives a wild number, usually negative -- and the
    create time is what tells the two apart."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(pid=100, create_time=1, user=ONE_SECOND * 50)],
                   now=0.0)
    rates = tracker.update([_raw(pid=100, create_time=999, user=0)], now=1.0)
    assert rates[100].cpu_percent is None, "it compared two different processes"


def test_a_counter_going_backwards_is_not_a_negative_rate():
    """Belt and braces with the create-time check: a rate is never below
    zero, whatever the counters did."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(read=5000)], now=0.0)
    rates = tracker.update([_raw(read=1000)], now=1.0)
    assert rates[100].read_bps is None or rates[100].read_bps >= 0


def test_a_process_that_vanished_is_dropped():
    tracker = RateTracker(cores=1)
    tracker.update([_raw(pid=100), _raw(pid=200)], now=0.0)
    rates = tracker.update([_raw(pid=100)], now=1.0)
    assert 200 not in rates


def test_the_memory_of_a_vanished_process_is_released():
    """A machine that churns processes -- a build, a script loop -- would
    otherwise grow this dict forever."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(pid=n) for n in range(100, 200)], now=0.0)
    tracker.update([_raw(pid=100)], now=1.0)
    assert tracker.tracked() == 1


def test_two_samples_at_the_same_instant_do_not_divide_by_zero():
    """Two ticks inside the clock's resolution is a real thing on Windows,
    where the default timer granularity is ~15.6 ms."""
    tracker = RateTracker(cores=1)
    tracker.update([_raw(user=0)], now=5.0)
    rates = tracker.update([_raw(user=ONE_SECOND)], now=5.0)
    assert rates[100].cpu_percent is None


def test_time_going_backwards_does_not_produce_a_negative_rate():
    tracker = RateTracker(cores=1)
    tracker.update([_raw(user=0)], now=10.0)
    rates = tracker.update([_raw(user=ONE_SECOND)], now=9.0)
    assert rates[100].cpu_percent is None


# ---- against the real machine -------------------------------------------

def test_the_real_machine_totals_something_sane():
    """Every process's CPU added up cannot exceed the machine, and on an
    idle-ish box is well under it. This is the check that would catch the
    core-count divisor being wrong."""
    import time

    tracker = RateTracker()
    tracker.update(system_processes(), now=time.monotonic())
    time.sleep(0.3)
    rates = tracker.update(system_processes(), now=time.monotonic())

    measured = [r.cpu_percent for r in rates.values()
                if r.cpu_percent is not None]
    assert measured, "nothing was measured over a 300 ms gap"
    assert sum(measured) <= 100.0 * 1.5, \
        f"the machine reported {sum(measured):.0f}% busy in total"


def test_our_own_process_is_measured_against_the_real_machine():
    import time

    tracker = RateTracker()
    tracker.update(system_processes(), now=time.monotonic())
    # Something to actually measure.
    deadline = time.monotonic() + 0.3
    while time.monotonic() < deadline:
        pass
    rates = tracker.update(system_processes(), now=time.monotonic())

    mine = rates[os.getpid()]
    assert mine.cpu_percent is not None
    assert mine.cpu_percent > 0, "a spin loop measured as zero CPU"
