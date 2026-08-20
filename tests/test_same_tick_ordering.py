"""Two intermittent failures, both caused by two clock reads landing in the
same tick.

They flaked roughly one full-suite run in three, which is corrosive in a
project whose whole hard-won lesson is that a green suite proves nothing: a
suite that is red for reasons nobody trusts is no better than one that is
green for reasons nobody checks. Both are reproduced deterministically here by
freezing the clock, which is what the real failure amounts to.
"""
import os
import sqlite3
import tempfile
from datetime import datetime

import pytest

from core.backup_service import BackupService
from modules.perfmon.perfmon_collector import PerfMonStore


class FrozenClock:
    """A datetime stand-in whose now() never advances.

    Not an exaggeration of the real conditions -- it is exactly them. Two
    adjacent datetime.now() calls on Windows land in the same microsecond
    often enough to fail one run in three.
    """

    FIXED = datetime(2026, 8, 20, 12, 0, 0)

    @classmethod
    def now(cls):
        return cls.FIXED

    def __getattr__(self, name):
        return getattr(datetime, name)


# ---- backup service: restore points made in the same tick ---------------

def test_restore_points_made_in_the_same_tick_still_list_newest_first(
        tmp_path, monkeypatch):
    """`ORDER BY created_at DESC` alone has no tiebreaker, so two points
    written in one tick came back in whatever order SQLite scanned them.

    Not only a test problem: a batch tweak apply creates several points in a
    burst, and someone reverting "the most recent" would revert whichever one
    the scan happened to reach first.
    """
    monkeypatch.setattr("core.backup_service.datetime", FrozenClock)
    # The row id is a uuid4 hex and the table's PRIMARY KEY, so on a tie
    # SQLite walks that index and the order comes out of the RANDOM id. That
    # is the actual coin flip behind the intermittent failure; pinning the two
    # ids so the older point sorts first makes it happen every time.
    ids = iter(["0" * 32, "f" * 32])
    monkeypatch.setattr("core.backup_service.uuid",
                        type("_U", (), {"uuid4": staticmethod(
                            lambda: type("_H", (), {"hex": next(ids)})())}))
    service = BackupService(data_dir=str(tmp_path))
    try:
        service.create_restore_point("First", "Tweaks")
        service.create_restore_point("Second", "Cleanup")
        points = service.list_restore_points()
        assert [p.created_at for p in points] == [FrozenClock.FIXED.isoformat()] * 2
        assert [p.label for p in points] == ["Second", "First"]
    finally:
        service.close()


def test_ordering_still_holds_when_the_clock_does_advance(tmp_path):
    service = BackupService(data_dir=str(tmp_path))
    try:
        service.create_restore_point("First", "Tweaks")
        service.create_restore_point("Second", "Cleanup")
        assert [p.label for p in service.list_restore_points()] == ["Second", "First"]
    finally:
        service.close()


# ---- perfmon: a sample written in the cutoff's own tick -----------------

@pytest.fixture
def store():
    """Closes the store even when the assertion fails.

    It did not before, so a failure left the SQLite handle open, the temp dir
    could not be removed on Windows, and the real assertion error was buried
    under a PermissionError about a file nobody was asking about.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        s = PerfMonStore(os.path.join(tmpdir, "test_perfmon.db"))
        try:
            yield s
        finally:
            s.close()


def test_cleanup_removes_a_sample_written_in_the_cutoff_tick(store, monkeypatch):
    """`cleanup_old(days=0)` means "delete everything". With `timestamp <
    cutoff` and both clock reads in one tick, the sample was written AT the
    cutoff and survived."""
    monkeypatch.setattr("modules.perfmon.perfmon_collector.datetime", FrozenClock)
    store.store_snapshot({"cpu_total": 50.0})
    store.cleanup_old(days=0)
    assert store.query("cpu_total", hours_back=24) == []


def test_cleanup_still_spares_anything_newer_than_the_cutoff(store):
    """The fix must not turn "older than 7 days" into "everything"."""
    store.store_snapshot({"cpu_total": 50.0})
    store.cleanup_old(days=7)
    assert len(store.query("cpu_total", hours_back=24)) == 1
