"""Applying is not believing.

TweakEngine reports success when its writer returned. That is not evidence the
machine changed: this project has four separate cmdlets on record that exit 0
while refusing. Every control is therefore re-read after its write, and a
writer that "succeeded" against a reader that disagrees is its own state --
APPLIED_UNVERIFIED -- which is the state that today does not exist and is
reported as success.
"""

from modules.security_dashboard.applier import apply_batch
from modules.security_dashboard.catalog.model import (
    Category, ControlState, Risk, SecurityControl)
from modules.security_dashboard.staging import ChangeSet


class _Backup:
    def __init__(self):
        self.points = []

    def create_restore_point(self, label, module):
        self.points.append((label, module))
        return "rp-1"

    def record_steps(self, *a, **k):
        pass

    def backup_registry_key(self, *a, **k):
        pass


class _Engine:
    def __init__(self, ok=True):
        self.ok, self.applied = ok, []

    def apply_tweak(self, tweak, rp_id, on_error=None):
        self.applied.append(tweak["id"])
        if not self.ok and on_error:
            on_error("Access is denied.")
        return self.ok


def _control(cid, readings, **over):
    """readings: a list popped one per read, so before/after can differ."""
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": readings.pop(0)},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_a_write_the_reader_confirms_is_verified():
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)     # reads True, then False
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_VERIFIED


def test_a_write_the_reader_contradicts_is_not_reported_as_success():
    cs = ChangeSet()
    cs.add(_control("a", [True, True]), False)      # asked for False, still True
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_UNVERIFIED
    assert result.results[0].observed is True
    assert result.results[0].requested is False


def test_a_refused_write_carries_the_reason():
    cs = ChangeSet()
    cs.add(_control("a", [True, True]), False)
    result = apply_batch(cs, _Engine(ok=False), _Backup())
    assert result.results[0].state is ControlState.REFUSED
    assert "Access is denied" in result.results[0].reason


def test_a_reboot_control_is_not_marked_unverified_before_the_reboot():
    cs = ChangeSet()
    cs.add(_control("a", [True, True], requires_reboot=True), False)
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_PENDING_REBOOT


def test_one_refusal_does_not_abandon_the_rest_of_the_batch():
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    cs.add(_control("b", [True, False]), False)
    result = apply_batch(cs, _Engine(), _Backup())
    assert len(result.results) == 2


def test_every_batch_takes_an_app_restore_point():
    backup = _Backup()
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    apply_batch(cs, _Engine(), backup)
    assert backup.points and backup.points[0][1] == "Security Dashboard"


def test_only_a_high_risk_batch_takes_a_windows_restore_point():
    calls = []
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    apply_batch(cs, _Engine(), _Backup(),
                create_windows_restore_point=lambda d: calls.append(d) or (True, ""))
    assert calls == [], "a low-risk batch must not spend 30s on a restore point"

    cs2 = ChangeSet()
    cs2.add(_control("b", [True, False], risk=Risk.HIGH), False)
    apply_batch(cs2, _Engine(), _Backup(),
                create_windows_restore_point=lambda d: calls.append(d) or (True, ""))
    assert len(calls) == 1


def test_a_reader_that_throws_after_the_write_is_unverified_not_a_crash():
    def boom():
        raise OSError("registry unavailable")
    cs = ChangeSet()
    control = _control("a", [True])
    cs.add(control, False)
    object.__setattr__(control, "reader", boom)
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_UNVERIFIED


# --- the two below are not in the plan; both are the snapshot cache ---------
#
# 135 of the 149 readers answer out of snapshots.py, whose cache has no TTL.
# Verifying a write by calling the reader again, without dropping that cache
# first, re-reads the value from BEFORE the write -- so a batch of Defender or
# service changes would report APPLIED_UNVERIFIED for every write that in fact
# landed. Neither of these can be seen by any of the eight tests above,
# because their fake readers do not go through a snapshot.


def test_the_snapshot_caches_are_dropped_before_anything_is_verified():
    dropped = []
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    apply_batch(cs, _Engine(), _Backup(),
                invalidate_reads=lambda: dropped.append("dropped"))
    assert dropped == ["dropped"], (
        "without this the verify pass reads the snapshot taken before the "
        "write and calls a landed change unverified")


def test_every_write_happens_before_the_first_verifying_read():
    """One snapshot refetch has to cover the whole batch.

    The caches are dropped once, between the writes and the reads. If a
    control were verified while later controls still had writes outstanding,
    the snapshot its reader warms would be stale again by the time those ran
    -- so the reads must all come after the last write, not interleave.
    """
    engine = _Engine()
    seen = []

    def _reader(value):
        def read():
            seen.append(tuple(engine.applied))
            return {"available": True, "enabled": value}
        return read

    cs = ChangeSet()
    cs.add(_control("a", [True]), False, from_value=True)
    cs.add(_control("b", [True]), False, from_value=True)
    for change in cs.changes:
        object.__setattr__(change.control, "reader", _reader(False))

    apply_batch(cs, engine, _Backup())
    assert seen == [("a", "b"), ("a", "b")], (
        f"a read saw a partly-applied batch: {seen}")
