"""The Disk Usage card, against the drive letters a real machine actually has.

This box has two card-reader slots, F: and G:, with no card in them. psutil
lists them (they are real volumes) with an EMPTY fstype, and `disk_usage` on
one raises PermissionError [WinError 21] "The device is not ready". The
dashboard refreshes every 3 seconds, so the shipped build wrote two full
tracebacks into the log every 3 seconds for the whole session.
"""
import logging
from collections import namedtuple

import pytest

from modules.dashboard import dashboard_module as dm

_Part = namedtuple("_Part", ["device", "mountpoint", "fstype", "opts"])
_Usage = namedtuple("_Usage", ["total", "used", "free", "percent"])

FIXED_C = _Part("C:\\", "C:\\", "NTFS", "rw,fixed")
FIXED_E = _Part("E:\\", "E:\\", "NTFS", "rw,fixed")
EMPTY_SLOT_F = _Part("F:\\", "F:\\", "", "removable")
CDROM = _Part("D:\\", "D:\\", "", "cdrom")


def _usage(_mountpoint):
    return _Usage(total=1000, used=250, free=750, percent=25.0)


def _not_ready(mountpoint):
    raise PermissionError(21, "The device is not ready", mountpoint)


def test_a_slot_with_no_media_is_skipped_not_probed():
    """psutil's empty fstype is the signal for 'no media'. report_module has
    guarded on it since forever; the dashboard never did."""
    kept = dm._mounted_partitions([FIXED_C, EMPTY_SLOT_F, CDROM, FIXED_E])
    assert [p.device for p in kept] == ["C:\\", "E:\\"]


def test_refresh_does_not_log_for_an_empty_card_reader(monkeypatch, caplog):
    w = dm._DashboardWidget()
    monkeypatch.setattr(dm.psutil, "disk_partitions",
                        lambda all=False: [FIXED_C, EMPTY_SLOT_F])
    monkeypatch.setattr(dm.psutil, "disk_usage",
                        lambda mp: _not_ready(mp) if mp == "F:\\" else _usage(mp))
    with caplog.at_level(logging.WARNING, logger=dm.logger.name):
        w._refresh_disk()
    assert caplog.records == [], [r.getMessage() for r in caplog.records]
    assert [k for k in w._disk_bars if k.startswith("C:")]
    assert not [k for k in w._disk_bars if k.startswith("F:")]


def test_a_drive_that_goes_away_loses_its_bar(monkeypatch):
    """`seen` was built and never read, so an unplugged USB volume kept a bar
    on the card for the rest of the session, frozen at its last reading."""
    w = dm._DashboardWidget()
    monkeypatch.setattr(dm.psutil, "disk_usage", _usage)

    monkeypatch.setattr(dm.psutil, "disk_partitions", lambda all=False: [FIXED_C, FIXED_E])
    w._refresh_disk()
    assert len(w._disk_bars) == 2

    monkeypatch.setattr(dm.psutil, "disk_partitions", lambda all=False: [FIXED_C])
    w._refresh_disk()
    assert list(w._disk_bars) == [FIXED_C.device + "  [NTFS]"], list(w._disk_bars)


def test_a_genuine_disk_usage_failure_is_still_reported(monkeypatch, caplog):
    """Skipping empty slots must not swallow a real failure on a real volume."""
    w = dm._DashboardWidget()
    monkeypatch.setattr(dm.psutil, "disk_partitions", lambda all=False: [FIXED_C])
    monkeypatch.setattr(dm.psutil, "disk_usage", _not_ready)
    with caplog.at_level(logging.WARNING, logger=dm.logger.name):
        w._refresh_disk()
    assert any("C:" in r.getMessage() for r in caplog.records)
