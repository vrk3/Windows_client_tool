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
from modules.security_dashboard import security_reader


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


# ── `unavailable()` semantics ───────────────────────────────────────────────
#
# This is the review finding for Task 3: ~30 readers in security_reader.py
# test `if not snapshots.mp_preference():` to decide whether a read was
# refused. That is wrong -- a successful fetch that legitimately parses to
# `{}` (or to a dict missing the one field a reader wants) is truthy-false
# but was NOT refused, and the reader must not report it as such.


def test_unavailable_is_none_for_a_snapshot_that_fetched_successfully_and_empty(monkeypatch):
    """Get-MpPreference exiting 0 with a genuinely empty/minimal JSON body is
    a successful read, not a refusal -- `unavailable()` must say so."""
    monkeypatch.setattr(snapshots, "_ps", lambda cmd, timeout=30: (0, "{}", ""))
    assert snapshots.mp_preference() == {}
    assert snapshots.unavailable("mp_preference") is None


def test_unavailable_carries_the_reason_for_a_refused_snapshot(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    assert snapshots.mp_preference() == {}
    reason = snapshots.unavailable("mp_preference")
    assert reason is not None
    assert "Access is denied" in reason


def test_unavailable_triggers_a_fetch_when_the_snapshot_was_never_asked_for(monkeypatch):
    """Never-tried is a third state, distinct from both "fine" and "refused".
    Rather than let a caller read silence as "fine", asking `unavailable()`
    forces the fetch so the answer reflects reality."""
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    assert len(calls) == 0
    assert snapshots.unavailable("mp_preference") is None
    assert len(calls) == 1


# ── The finding itself: a reader must not mistake "empty but successful"
#   for "refused". ────────────────────────────────────────────────────────


def test_a_successful_but_empty_mp_preference_read_is_reported_available(monkeypatch):
    """Pins the review finding for Task 3.

    `snapshot_dict` being falsy is not evidence of refusal: Get-MpPreference
    exiting 0 with `{}` on stdout is a real, successful answer (this is
    exactly the shape the next task's SpeculationControl snapshot will take
    on a machine where the module didn't load: a small truthy-but-uninformative
    dict, or here, a directly empty one). A reader must ask
    `snapshots.unavailable(...)`, never `if not prefs:`, to tell that apart
    from an actual refusal.
    """
    monkeypatch.setattr(snapshots, "_ps", lambda cmd, timeout=30: (0, "{}", ""))
    result = security_reader.check_pua_protection()
    assert result["available"] is True, (
        f"an empty-but-successful read was reported unavailable: {result}")


def test_a_refused_mp_preference_read_is_reported_unavailable_with_its_reason(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    result = security_reader.check_pua_protection()
    assert result["available"] is False
    detail_text = " ".join(str(v) for _, v in result.get("details", []))
    assert "Access is denied" in detail_text
