"""Deleting Windows System Restore points — the pure logic and the pane wiring.

Nothing here touches a real restore point: SRRemoveRestorePoint is faked, so
the tests pin the *decisions* (which points get deleted, how failures are
reported) rather than the OS call. What they cannot prove is that
srclient.dll accepts our sequence numbers — that needs an elevated run.
"""
import ctypes

import pytest

from core import system_restore


def _pt(seq, when, desc="Restore point"):
    return {
        "SequenceNumber": seq,
        "Description": desc,
        "RestorePointType": 0,
        "CreationTime": when,
    }


# ── parse_restore_point_time ────────────────────────────────────────────────

def test_parses_wmi_dmtf_datetime():
    dt = system_restore.parse_restore_point_time("20260824153000.000000-000")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 8, 24, 15, 30)


@pytest.mark.parametrize("value", ["", None, "not-a-date", "2026", 12345])
def test_unparseable_times_return_none_rather_than_raising(value):
    assert system_restore.parse_restore_point_time(value) is None


# ── sequence_numbers_to_prune ───────────────────────────────────────────────

def test_prune_keeps_only_the_newest_of_four():
    points = [
        _pt(11, "20260820100000.000000-000"),
        _pt(12, "20260821100000.000000-000"),
        _pt(13, "20260822100000.000000-000"),
        _pt(14, "20260823100000.000000-000"),
    ]
    assert sorted(system_restore.sequence_numbers_to_prune(points)) == [11, 12, 13]


def test_prune_uses_creation_time_not_list_order():
    """The newest point is not necessarily last in what PowerShell hands back."""
    points = [
        _pt(30, "20260825090000.000000-000"),   # newest, listed first
        _pt(10, "20260820090000.000000-000"),
        _pt(20, "20260822090000.000000-000"),
    ]
    assert sorted(system_restore.sequence_numbers_to_prune(points)) == [10, 20]


def test_prune_falls_back_to_sequence_number_when_times_tie():
    points = [
        _pt(5, "20260824120000.000000-000"),
        _pt(9, "20260824120000.000000-000"),
    ]
    assert system_restore.sequence_numbers_to_prune(points) == [5]


@pytest.mark.parametrize("points", [[], [_pt(1, "20260824120000.000000-000")]])
def test_prune_of_zero_or_one_point_deletes_nothing(points):
    assert system_restore.sequence_numbers_to_prune(points) == []


def test_prune_skips_points_with_no_usable_sequence_number():
    """A missing sequence number must not be guessed at — a wrong number
    would delete a different, real restore point."""
    points = [
        _pt(None, "20260820100000.000000-000"),
        _pt(7, "20260821100000.000000-000"),
        _pt(8, "20260822100000.000000-000"),
    ]
    assert system_restore.sequence_numbers_to_prune(points) == [7]


def test_prune_of_one_usable_point_plus_junk_deletes_nothing():
    points = [_pt("x", "20260820100000.000000-000"), _pt(7, "20260821100000.000000-000")]
    assert system_restore.sequence_numbers_to_prune(points) == []


# ── delete_restore_point ────────────────────────────────────────────────────

class _FakeSrClient:
    def __init__(self, code):
        self._code = code
        self.calls = []

    class _Fn:
        def __init__(self, outer):
            self._outer = outer
            self.argtypes = None
            self.restype = None

        def __call__(self, arg):
            self._outer.calls.append(int(arg.value if hasattr(arg, "value") else arg))
            return self._outer._code

    @property
    def SRRemoveRestorePoint(self):
        if not hasattr(self, "_fn"):
            self._fn = _FakeSrClient._Fn(self)
        return self._fn


@pytest.fixture
def fake_srclient(monkeypatch):
    holder = {}

    def install(code):
        fake = _FakeSrClient(code)
        holder["fake"] = fake
        monkeypatch.setattr(ctypes, "WinDLL", lambda name: fake)
        return fake

    return install


def test_successful_delete_reports_success(fake_srclient):
    fake = fake_srclient(0)
    ok, message = system_restore.delete_restore_point(42)
    assert (ok, message) == (True, "")
    assert fake.calls == [42]


def test_access_denied_says_run_as_administrator(fake_srclient):
    fake_srclient(5)
    ok, message = system_restore.delete_restore_point(42)
    assert ok is False
    assert "Administrator" in message


def test_other_error_codes_are_reported_not_swallowed(fake_srclient):
    fake_srclient(2)
    ok, message = system_restore.delete_restore_point(42)
    assert ok is False
    assert "2" in message and message.strip()


def test_dll_load_failure_is_reported(monkeypatch):
    def boom(_name):
        raise OSError("srclient.dll not found")

    monkeypatch.setattr(ctypes, "WinDLL", boom)
    ok, message = system_restore.delete_restore_point(1)
    assert ok is False
    assert "srclient.dll" in message


# ── delete_restore_points ───────────────────────────────────────────────────

def test_batch_delete_keeps_going_after_a_failure(monkeypatch):
    def fake_delete(seq):
        return (False, "locked") if seq == 2 else (True, "")

    monkeypatch.setattr(system_restore, "delete_restore_point", fake_delete)
    deleted, failures = system_restore.delete_restore_points([1, 2, 3])
    assert deleted == 2
    assert failures == [(2, "locked")]


def test_batch_delete_of_nothing_is_a_no_op(monkeypatch):
    monkeypatch.setattr(
        system_restore, "delete_restore_point",
        lambda seq: pytest.fail("should not be called"),
    )
    assert system_restore.delete_restore_points([]) == (0, [])
