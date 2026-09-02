"""The machine-wide counters behind the System Information window.

The struct these come out of is undocumented and version-sensitive, so the
tests that matter most are the ones that check it against something else
that knows the answer -- `GetPerformanceInfo` at the head of the struct and
PDH at the tail. Agreement at both ends is what makes the middle credible.
"""
import time

import pytest

from core.procengine.sysinfo import (
    SystemCounters, SystemRates, page_size, system_counters, system_rates,
)


def _counters(at=0.0, **fields):
    base = dict(
        io_read_bytes=0, io_write_bytes=0, io_other_bytes=0,
        io_read_ops=0, io_write_ops=0, io_other_ops=0,
        available_pages=0, committed_pages=0, commit_limit_pages=0,
        peak_commit_pages=0, page_faults=0, demand_zero_faults=0,
        page_reads=0, page_read_ios=0, dirty_writes=0, mapped_writes=0,
        paged_pool_pages=0, nonpaged_pool_pages=0, paged_pool_allocs=0,
        paged_pool_frees=0, nonpaged_pool_allocs=0, nonpaged_pool_frees=0,
        free_system_ptes=0, context_switches=0, system_calls=0)
    base.update(fields)
    return SystemCounters(at=at, **base)


# ---- the real machine ---------------------------------------------------

def test_the_counters_can_be_read():
    assert system_counters() is not None


def test_the_page_size_is_a_real_one():
    assert page_size() in (4096, 8192, 16384, 65536)


def test_every_counter_is_plausible():
    counters = system_counters()
    assert counters.committed_pages > 0
    assert counters.commit_limit_pages >= counters.committed_pages
    assert counters.available_pages > 0
    assert counters.context_switches > 0
    assert counters.system_calls > 0
    assert counters.page_faults > 0
    assert counters.paged_pool_pages > 0
    assert counters.nonpaged_pool_pages > 0


def test_the_counters_only_go_forwards():
    before = system_counters()
    time.sleep(0.3)
    after = system_counters()
    assert after.context_switches >= before.context_switches
    assert after.system_calls >= before.system_calls
    assert after.io_read_bytes >= before.io_read_bytes


# ---- the layout, checked against something that knows ------------------

def test_the_head_of_the_struct_agrees_with_getperformanceinfo():
    """The offsets are a guess until an independent source agrees. If a
    future Windows inserts a field near the front, these three stop
    matching and this test is how anyone finds out -- rather than by
    reading a commit figure that is wrong but plausible."""
    from core.procengine.meminfo import memory_status

    counters = system_counters()
    status = memory_status()
    size = page_size()

    # Within 1%: the two calls are not simultaneous and the machine is live.
    assert counters.committed_pages * size == pytest.approx(
        status.committed, rel=0.01)
    assert counters.commit_limit_pages * size == pytest.approx(
        status.commit_limit, rel=0.01)
    assert counters.available_pages * size == pytest.approx(
        status.available, rel=0.01)


def test_the_tail_of_the_struct_agrees_with_pdh():
    """Context switches and system calls sit at the far end of thirty
    undocumented cache-manager counters. If that run is the wrong length
    on some Windows build, these read as garbage that still looks like a
    number -- so they are checked against the counters Windows publishes
    for the same thing."""
    win32pdh = pytest.importorskip("win32pdh")

    query = win32pdh.OpenQuery()
    try:
        switches = win32pdh.AddEnglishCounter(
            query, r"\System\Context Switches/sec")
        calls = win32pdh.AddEnglishCounter(
            query, r"\System\System Calls/sec")
        win32pdh.CollectQueryData(query)
        before = system_counters()
        time.sleep(1.5)
        win32pdh.CollectQueryData(query)
        after = system_counters()

        rates = system_rates(before, after)
        for counter, ours in ((switches, rates.context_switches),
                              (calls, rates.system_calls)):
            _kind, published = win32pdh.GetFormattedCounterValue(
                counter, win32pdh.PDH_FMT_DOUBLE)
            assert published > 0
            # Loose on purpose: the two readings bracket slightly different
            # windows. A wrong offset is out by orders of magnitude, not by
            # a third.
            assert ours == pytest.approx(published, rel=0.35)
    finally:
        win32pdh.CloseQuery(query)


# ---- rates --------------------------------------------------------------

def test_one_reading_is_not_a_rate():
    assert system_rates(None, _counters()).context_switches is None
    assert system_rates(_counters(), None).context_switches is None


def test_two_readings_at_the_same_instant_do_not_divide_by_zero():
    counters = _counters(at=5.0)
    assert system_rates(counters, counters).system_calls is None


def test_a_rate_is_the_difference_over_the_interval():
    rates = system_rates(_counters(at=0.0, context_switches=1000),
                         _counters(at=2.0, context_switches=5000))
    assert rates.context_switches == 2000.0


def test_io_is_reported_in_bytes_per_second():
    rates = system_rates(_counters(at=0.0, io_read_bytes=0),
                         _counters(at=4.0, io_read_bytes=8192))
    assert rates.io_read_bps == 2048.0


def test_a_counter_that_wrapped_is_not_a_negative_rate():
    """These are 32-bit counters and a long-running machine does wrap
    them. A negative rate would draw the graph off the bottom; a
    4-billion spike would draw it off the top."""
    rates = system_rates(_counters(at=0.0, system_calls=4_000_000_000),
                         _counters(at=1.0, system_calls=12))
    assert rates.system_calls is None


def test_the_io_total_is_none_when_any_part_is_unmeasured():
    """Summing with the gaps read as zero would report a total smaller
    than the machine's real traffic, and it would look like a reading."""
    assert SystemRates(io_read_bps=1.0, io_write_bps=2.0).io_total_bps is None
    assert SystemRates(io_read_bps=1.0, io_write_bps=2.0,
                       io_other_bps=3.0).io_total_bps == 6.0


def test_the_real_machine_produces_rates():
    before = system_counters()
    time.sleep(0.4)
    rates = system_rates(before, system_counters())
    assert rates.context_switches is not None and rates.context_switches > 0
    assert rates.system_calls is not None and rates.system_calls > 0


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from core.procengine import sysinfo

    assert "PyQt6" not in inspect.getsource(sysinfo)
