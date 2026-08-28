"""One cmdlet call, many readers.

Measured at branch point: one _ps() call costs 0.54s and 57 of the 171 readers
use it -- 19 of them each running Get-MpPreference to pull ONE field out of a
cmdlet that returns all of them. 155 controls read that way is a minute-long
tab, which is the Overview 37.3s defect at ten times the scale.

A refused snapshot must be distinguishable from an empty one. Get-MpPreference
on a machine with Defender replaced by a third-party AV does not fail -- it
answers with fewer fields.
"""
import pytest

from modules.security_dashboard import snapshots


@pytest.fixture(autouse=True)
def _clean():
    snapshots.invalidate()
    yield
    snapshots.invalidate()


def test_the_cmdlet_runs_once_for_many_reads(monkeypatch):
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"DisableRealtimeMonitoring":false,"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    for _ in range(10):
        snapshots.mp_preference()
    assert len(calls) == 1, f"ran the cmdlet {len(calls)} times, not once"


def test_invalidate_forces_a_refetch(monkeypatch):
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    snapshots.mp_preference()
    snapshots.invalidate()
    snapshots.mp_preference()
    assert len(calls) == 2


def test_a_refusal_is_recorded_as_a_reason_not_as_an_empty_answer(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    assert snapshots.mp_preference() == {}
    assert "Access is denied" in snapshots.availability()["mp_preference"]


def test_a_cmdlet_that_exits_zero_with_a_complaint_on_stdout_is_a_refusal(monkeypatch):
    """dism exits 740 with its complaint on STDOUT; netsh exits 0 and says
    'No rules match'. rc alone is not a success signal."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (0, "Elevated permissions are required.", ""))
    assert snapshots.mp_preference() == {}
    assert snapshots.availability()["mp_preference"] is not None
