"""Disk and network throughput.

Same discipline as the process rates: two readings, and the first is `None`
rather than zero. An unmeasured rate and an idle device must not look the
same, because one of them means "nothing is happening" and the other means
"ask again in a second".
"""
import time

import pytest

from core.procengine.ioinfo import (
    DiskCounters, InterfaceCounters, disk_counters, disk_rates,
    interface_counters, interface_rates,
)


def _disk(index=0, read=0, written=0, idle=0, at=0.0, query_time=0):
    return DiskCounters(index=index, bytes_read=read, bytes_written=written,
                        read_time=0, write_time=0, idle_time=idle,
                        queue_depth=0, query_time=query_time, at=at)


def _nic(name="Ethernet", sent=0, received=0, at=0.0, speed=1_000_000_000):
    return InterfaceCounters(index=0, name=name, bytes_sent=sent,
                             bytes_received=received, speed_bps=speed,
                             up=True, loopback=False, at=at)


# ---- the real disks -----------------------------------------------------

def test_the_machine_has_at_least_one_physical_disk():
    assert disk_counters(), "no physical disk answered"


def test_disk_counters_are_plausible():
    for counters in disk_counters():
        assert counters.bytes_read >= 0
        assert counters.bytes_written >= 0
        assert counters.idle_time >= 0


def test_disk_counters_only_go_forwards():
    before = disk_counters()
    time.sleep(0.3)
    after = {counters.index: counters for counters in disk_counters()}
    for counters in before:
        later = after.get(counters.index)
        if later is None:
            continue
        assert later.bytes_read >= counters.bytes_read


def test_an_unreadable_disk_is_skipped_rather_than_reported_as_idle():
    """Asking for sixteen drives on a machine with two must not produce
    fourteen zero-traffic disks."""
    assert len(disk_counters(max_disks=16)) < 16


# ---- disk rates ---------------------------------------------------------

def test_the_first_disk_reading_has_no_rate():
    rates = disk_rates([], [_disk(at=1.0)])
    assert rates[0].read_bps is None


def test_disk_throughput_is_bytes_per_second():
    rates = disk_rates([_disk(read=0, at=0.0)], [_disk(read=2048, at=2.0)])
    assert rates[0].read_bps == pytest.approx(1024.0)


def test_a_fully_idle_disk_reads_as_zero_active():
    """Idle moved by the whole interval, so nothing was done."""
    from core.procengine.ioinfo import HUNDRED_NS

    rates = disk_rates([_disk(idle=0, at=0.0)],
                       [_disk(idle=HUNDRED_NS, at=1.0)])
    assert rates[0].active_percent == pytest.approx(0.0)


def test_a_fully_busy_disk_reads_as_one_hundred_active():
    rates = disk_rates([_disk(idle=0, at=0.0)], [_disk(idle=0, at=1.0)])
    assert rates[0].active_percent == pytest.approx(100.0)


def test_active_time_comes_from_idle_not_from_read_plus_write():
    """Read and write time overlap on a queued device, so adding them can
    exceed the interval. Active is the remainder of idle."""
    from core.procengine.ioinfo import HUNDRED_NS

    rates = disk_rates([_disk(idle=0, at=0.0)],
                       [_disk(idle=HUNDRED_NS // 2, at=1.0)])
    assert rates[0].active_percent == pytest.approx(50.0)


def test_active_time_is_never_above_one_hundred():
    rates = disk_rates([_disk(idle=100, at=0.0)], [_disk(idle=0, at=1.0)])
    assert rates[0].active_percent is None or \
        0.0 <= rates[0].active_percent <= 100.0


def test_disks_are_matched_by_index_not_by_position():
    """A disk that stops answering shifts every later entry, and comparing
    across that shift attributes one drive's traffic to another."""
    before = [_disk(index=0, read=1000, at=0.0),
              _disk(index=1, read=5000, at=0.0)]
    after = [_disk(index=1, read=6000, at=1.0)]

    rates = disk_rates(before, after)

    assert len(rates) == 1
    assert rates[0].index == 1
    assert rates[0].read_bps == pytest.approx(1000.0)


def test_a_disk_that_appeared_has_no_rate_yet():
    rates = disk_rates([], [_disk(index=3, at=1.0)])
    assert rates[0].read_bps is None


def test_two_disk_readings_at_the_same_instant_do_not_divide_by_zero():
    rates = disk_rates([_disk(at=5.0)], [_disk(read=100, at=5.0)])
    assert rates[0].read_bps is None


def test_a_counter_that_went_backwards_is_not_a_negative_rate():
    rates = disk_rates([_disk(read=5000, at=0.0)], [_disk(read=100, at=1.0)])
    assert rates[0].read_bps is None


def test_the_real_disks_produce_plausible_rates():
    before = disk_counters()
    time.sleep(0.4)
    rates = disk_rates(before, disk_counters())
    assert rates
    for rate in rates:
        if rate.read_bps is not None:
            assert rate.read_bps >= 0
        if rate.active_percent is not None:
            assert 0.0 <= rate.active_percent <= 100.0


# ---- the real interfaces ------------------------------------------------

def test_the_machine_has_network_interfaces():
    assert interface_counters()


def test_every_interface_is_named():
    for counters in interface_counters():
        assert counters.name


def test_at_least_one_interface_is_up():
    assert any(counters.up for counters in interface_counters())


def test_an_unknown_link_speed_is_none_rather_than_zero():
    """psutil reports 0 for "unknown", which is not a zero-speed link. As 0
    the panel would scale its graph against nothing."""
    for counters in interface_counters():
        assert counters.speed_bps is None or counters.speed_bps > 0


# ---- interface rates ----------------------------------------------------

def test_the_first_interface_reading_has_no_rate():
    rates = interface_rates([], [_nic(at=1.0)])
    assert rates[0].send_bps is None


def test_interface_throughput_is_bytes_per_second():
    rates = interface_rates([_nic(received=0, at=0.0)],
                            [_nic(received=4096, at=2.0)])
    assert rates[0].receive_bps == pytest.approx(2048.0)


def test_interfaces_are_matched_by_name_not_by_index():
    """A VPN connecting or a dock attaching shifts every index."""
    before = [_nic(name="Wi-Fi", sent=1000, at=0.0)]
    after = [_nic(name="VPN", sent=0, at=1.0),
             _nic(name="Wi-Fi", sent=2000, at=1.0)]

    rates = {rate.name: rate for rate in interface_rates(before, after)}

    assert rates["Wi-Fi"].send_bps == pytest.approx(1000.0)
    assert rates["VPN"].send_bps is None, "a new interface has no rate yet"


def test_an_interface_that_vanished_is_dropped():
    rates = interface_rates([_nic(name="Wi-Fi", at=0.0)],
                            [_nic(name="Ethernet", at=1.0)])
    assert [rate.name for rate in rates] == ["Ethernet"]


def test_the_link_speed_is_carried_through_for_the_graphs_scale():
    rates = interface_rates([_nic(at=0.0)], [_nic(at=1.0)])
    assert rates[0].speed_bps == 1_000_000_000


def test_the_real_interfaces_produce_plausible_rates():
    before = interface_counters()
    time.sleep(0.4)
    rates = interface_rates(before, interface_counters())
    assert rates
    for rate in rates:
        if rate.send_bps is not None:
            assert rate.send_bps >= 0


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from core.procengine import ioinfo

    assert "PyQt6" not in inspect.getsource(ioinfo)


def test_the_drivers_own_timestamp_measures_the_interval():
    """A wall clock read once before a loop over seven disks is already
    stale by the time the last one answers, and that skew is the entire
    signal when the true active time is zero -- it put a permanent 2-3%
    ripple on disks doing nothing."""
    from core.procengine.ioinfo import HUNDRED_NS

    # The driver says exactly one second passed; the wall clock disagrees.
    # Both timestamps are non-zero: 0 is the sentinel for "the driver gave
    # us none", which is a different case and has its own test below.
    before = _disk(idle=0, at=0.0, query_time=HUNDRED_NS)
    after = _disk(idle=HUNDRED_NS, at=99.0, query_time=HUNDRED_NS * 2)

    assert disk_rates([before], [after])[0].active_percent == \
        pytest.approx(0.0)


def test_the_wall_clock_is_used_when_the_driver_gives_no_timestamp():
    from core.procengine.ioinfo import HUNDRED_NS

    before = _disk(idle=0, at=0.0, query_time=0)
    after = _disk(idle=HUNDRED_NS // 2, at=1.0, query_time=0)

    assert disk_rates([before], [after])[0].active_percent == \
        pytest.approx(50.0)


def test_a_real_idle_disk_reads_as_near_zero_active(monkeypatch):
    """The symptom this fixed: idle disks drawing a permanent ripple.

    Runs against controlled counters so the machine's actual disk activity
    (some disks are never quiet) cannot make the assertion flaky.
    """
    from core.procengine.ioinfo import HUNDRED_NS
    import core.procengine.ioinfo as ioinfo_mod

    calls = {"n": 0}

    def fake_counters(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [_disk(index=0, read=0, written=0, idle=0, at=0.0)]
        return [_disk(index=0, read=0, written=0, idle=HUNDRED_NS, at=1.0)]

    monkeypatch.setattr(ioinfo_mod, "disk_counters", fake_counters)

    before = ioinfo_mod.disk_counters()
    rates = ioinfo_mod.disk_rates(before, ioinfo_mod.disk_counters())

    quiet = [rate for rate in rates
             if not rate.read_bps and not rate.write_bps
             and rate.active_percent is not None]
    assert quiet, "a fully idle disk must produce a quiet rate"
    assert max(rate.active_percent for rate in quiet) < 2.0


def test_the_loopback_adapter_is_flagged():
    """It carries no real traffic and Task Manager does not list it."""
    found = [counters for counters in interface_counters()
             if counters.loopback]
    assert found, "no loopback interface was identified"


def test_loopback_is_detected_by_address_not_by_name():
    """"Loopback Pseudo-Interface 1" is the English name only; a name match
    would quietly start listing it on a German install."""
    from core.procengine.ioinfo import _is_loopback

    class _Entry:
        def __init__(self, address):
            self.address = address

    assert _is_loopback([_Entry("127.0.0.1")]) is True
    assert _is_loopback([_Entry("::1")]) is True
    assert _is_loopback([_Entry("192.168.1.5")]) is False
    assert _is_loopback([]) is False


def test_a_real_adapter_is_not_flagged_as_loopback():
    real = [counters for counters in interface_counters()
            if counters.up and not counters.loopback]
    assert real, "every interface was called loopback"
