"""Watching one process over time.

Two things carry most of the weight here: a process can exit while its
properties window is open, and its pid can be REUSED while the window is
open. The second is the dangerous one -- it would report a different
program's figures under the old one's title.
"""
import os
import subprocess
import sys
import time

import pytest

from modules.dashboard.procengine.ntquery import system_processes
from modules.dashboard.procengine.procwatch import (
    HISTORY, ProcessWatch, Series,
)

MY_PID = os.getpid()


# ---- the series ---------------------------------------------------------

def test_a_series_keeps_a_bounded_history():
    series = Series()
    for value in range(HISTORY * 3):
        series.push(float(value))
    assert len(series.as_list()) == HISTORY


def test_a_series_keeps_gaps_as_gaps():
    """A tick with no rate is a break in the graph, not a zero."""
    series = Series()
    series.push(1.0)
    series.push(None)
    series.push(3.0)
    assert series.as_list() == [1.0, None, 3.0]


def test_the_peak_ignores_the_gaps():
    series = Series()
    for value in (1.0, None, 7.0, None, 3.0):
        series.push(value)
    assert series.peak() == 7.0


def test_the_peak_of_nothing_is_none():
    assert Series().peak() is None


# ---- watching ourselves -------------------------------------------------

def test_the_first_sample_has_no_rate():
    """One reading is not a rate, here as everywhere else in the engine."""
    watch = ProcessWatch(MY_PID)
    sample = watch.sample()
    assert sample is not None
    assert sample.cpu_percent is None


def test_the_second_sample_has_rates():
    watch = ProcessWatch(MY_PID)
    watch.sample()
    time.sleep(0.4)
    sample = watch.sample()
    assert sample.cpu_percent is not None
    assert sample.read_bps is not None


def test_the_raw_counters_are_carried_through():
    watch = ProcessWatch(MY_PID)
    sample = watch.sample()
    assert sample.raw.pid == MY_PID
    assert sample.raw.threads > 0
    assert sample.raw.private_bytes > 0


def test_history_accumulates():
    watch = ProcessWatch(MY_PID)
    for _ in range(3):
        watch.sample()
        time.sleep(0.15)
    assert len(watch.cpu.as_list()) == 3
    assert len(watch.private_bytes.as_list()) == 3


def test_the_io_total_needs_every_part():
    watch = ProcessWatch(MY_PID)
    first = watch.sample()
    assert first.io_total_bps is None
    time.sleep(0.3)
    assert watch.sample().io_total_bps is not None


def test_a_caller_can_share_one_reading():
    """Several properties windows open at once should not each pay for
    their own syscall."""
    rows = system_processes()
    watch = ProcessWatch(MY_PID)
    assert watch.sample(rows=rows) is not None


# ---- exiting ------------------------------------------------------------

def test_a_process_that_exits_ends_the_watch():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    time.sleep(0.2)

    watch = ProcessWatch(child.pid)
    assert watch.sample() is None
    assert watch.alive is False
    assert "exited" in watch.exited_because


def test_a_watch_that_ended_stays_ended():
    watch = ProcessWatch(999_999)
    watch.sample()
    assert watch.sample() is None
    assert watch.alive is False


def test_a_live_process_is_watched_until_it_goes():
    child = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(30)"])
    try:
        watch = ProcessWatch(child.pid)
        assert watch.sample() is not None
        assert watch.alive
    finally:
        child.kill()
        child.wait()
    time.sleep(0.3)
    assert watch.sample() is None
    assert watch.alive is False


def test_a_reused_pid_ends_the_watch_rather_than_being_reported(fake_rows):
    """The dangerous case. Windows reuses pids briskly, and a properties
    window that quietly starts reporting a different program under the old
    one's title is worse than one that says the process has gone.
    """
    watch = ProcessWatch(4242)
    assert watch.sample(rows=fake_rows(4242, create_time=1000)) is not None
    assert watch.sample(rows=fake_rows(4242, create_time=9999)) is None
    assert watch.alive is False
    assert "reused" in watch.exited_because


def test_the_same_process_keeps_being_watched(fake_rows):
    watch = ProcessWatch(4242)
    assert watch.sample(rows=fake_rows(4242, create_time=1000)) is not None
    assert watch.sample(rows=fake_rows(4242, create_time=1000)) is not None
    assert watch.alive


@pytest.fixture
def fake_rows():
    from modules.dashboard.procengine.ntquery import ProcessRaw

    def build(pid, create_time):
        return [ProcessRaw(
            pid=pid, ppid=4, name="thing.exe", threads=1, handles=1,
            session=1, base_priority=8, working_set=1024,
            working_set_private=1024, private_bytes=1024, paged_pool=0,
            nonpaged_pool=0, pagefile=0, peak_pagefile=0, virtual_size=2048,
            peak_virtual_size=2048, peak_working_set=1024, page_faults=0,
            hard_faults=0, kernel_time=0, user_time=0, cycles=1,
            read_bytes=0, write_bytes=0, other_bytes=0, read_ops=0,
            write_ops=0, other_ops=0, create_time=create_time)]

    return build


# ---- the GPU half -------------------------------------------------------

def test_gpu_figures_are_none_without_a_sampler():
    sample = ProcessWatch(MY_PID).sample()
    assert sample.gpu_percent is None
    assert sample.gpu_dedicated is None


def test_gpu_figures_arrive_when_a_sampler_is_given():
    from modules.dashboard.procengine.gpuinfo import GpuSampler

    with GpuSampler() as sampler:
        sampler.sample()
        time.sleep(0.8)
        sampler.sample()
        watch = ProcessWatch(MY_PID, gpu=sampler)
        watch.sample()
        memory = sampler.process_memory()

    assert memory, "no process reported any GPU memory"
    for dedicated, shared in memory.values():
        assert dedicated >= 0 and shared >= 0


def test_process_gpu_memory_is_attributed_per_pid():
    from modules.dashboard.procengine.gpuinfo import GpuSampler

    with GpuSampler() as sampler:
        sampler.sample()
        time.sleep(0.8)
        sampler.sample()
        memory = sampler.process_memory()

    live = {row.pid for row in system_processes()}
    known = [pid for pid in memory if pid in live]
    assert known, "no live process was given GPU memory"


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from modules.dashboard.procengine import procwatch

    assert "PyQt6" not in inspect.getsource(procwatch)
