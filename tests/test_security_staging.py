"""Toggling stages; nothing touches the machine until Apply."""
import pytest

from modules.security_dashboard.catalog.model import (
    Category, Risk, SecurityControl)
from modules.security_dashboard.staging import ChangeSet, diff_against


def _control(cid, current, **over):
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w", reader=lambda: {"available": True, "enabled": current},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_staging_a_change_records_where_it_came_from():
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)
    change = cs.changes[0]
    assert (change.from_value, change.to_value) == (True, False)


def test_staging_the_value_it_already_has_is_not_a_change():
    cs = ChangeSet()
    cs.add(_control("llmnr", True), True)
    assert cs.changes == ()


def test_staging_the_same_control_twice_keeps_one_entry():
    cs = ChangeSet()
    control = _control("llmnr", True)
    cs.add(control, False)
    cs.add(control, False)
    assert len(cs.changes) == 1


def test_staging_back_to_the_original_value_removes_the_change():
    cs = ChangeSet()
    control = _control("llmnr", True)
    cs.add(control, False)
    cs.add(control, True)
    assert cs.changes == ()


def test_the_batch_reports_its_highest_risk():
    cs = ChangeSet()
    cs.add(_control("a", True), False)
    cs.add(_control("b", True, risk=Risk.HIGH), False)
    assert cs.highest_risk is Risk.HIGH


def test_a_batch_with_a_reboot_control_says_so():
    cs = ChangeSet()
    cs.add(_control("a", True, requires_reboot=True), False)
    assert cs.needs_reboot


def test_a_control_that_could_not_be_read_is_still_stageable():
    """A refused read must not silently make a control unstageable -- the
    user may be staging it precisely because it could not be read."""
    unreadable = _control("x", None, reader=lambda: {"available": False})
    cs = ChangeSet()
    cs.add(unreadable, True)
    assert cs.changes[0].from_value is None


def test_diff_against_a_target_stages_only_what_differs():
    catalog = {"a": _control("a", True), "b": _control("b", False)}
    cs = diff_against(catalog, {"a": True, "b": True})
    assert [c.control_id for c in cs.changes] == ["b"]


def test_diff_ignores_ids_the_catalog_does_not_have():
    catalog = {"a": _control("a", True)}
    cs = diff_against(catalog, {"a": False, "ghost": True})
    assert [c.control_id for c in cs.changes] == ["a"]


# -- Ruling 2: staging must not re-read the machine --------------------------
#
# `add` calling control.read() on every click is the per-field-PowerShell trap
# Task 3 exists to remove, reintroduced in the UI layer. It is not theoretical:
# on this machine `bitlocker_encryption_detail.read()` costs 6.11 seconds, and
# a card that already knows what it displayed must be able to say so.

def _counting_control(cid, value):
    calls = []

    def reader():
        calls.append(1)
        return {"available": True, "enabled": value}

    return _control(cid, value, reader=reader), calls


def test_staging_with_a_known_value_does_not_touch_the_machine():
    control, calls = _counting_control("slow", True)
    cs = ChangeSet()

    cs.add(control, False, from_value=True)

    assert calls == [], "add() read the machine when the caller already knew"
    assert cs.changes[0].from_value is True


def test_staging_without_a_known_value_still_reads():
    control, calls = _counting_control("slow", True)
    cs = ChangeSet()

    cs.add(control, False)

    assert len(calls) == 1


def test_a_passed_value_equal_to_the_target_is_still_a_no_op():
    control, calls = _counting_control("slow", True)
    cs = ChangeSet()

    cs.add(control, True, from_value=True)

    assert cs.changes == ()
    assert calls == []


def test_a_passed_none_means_unreadable_not_unknown_to_the_caller():
    """None is a real from_value -- "we could not read it" -- and must not be
    confused with "the caller did not say", which is what triggers the read."""
    control, calls = _counting_control("slow", True)
    cs = ChangeSet()

    cs.add(control, False, from_value=None)

    assert calls == []
    assert cs.changes[0].from_value is None


# -- the hazard the Task 8 addendum told me to look for ----------------------

def test_a_control_cannot_be_staged_to_no_value():
    """`steps_for(None)` raises on purpose -- under the old behaviour it
    returned off_steps, which would have turned Windows Search OFF on a
    control the catalog explicitly has no opinion about. Staging None as a
    TARGET would walk straight into that at apply time, so it is refused
    here, where the message can still name the control.
    """
    cs = ChangeSet()

    with pytest.raises(ValueError, match="no value"):
        cs.add(_control("wsearch", True, desired=None), None)


def test_a_no_opinion_control_is_still_stageable_to_a_real_value():
    """desired=None means the CATALOG has no opinion. The user may still
    choose, and that choice stages normally."""
    cs = ChangeSet()

    cs.add(_control("wsearch", True, desired=None), False)

    assert cs.changes[0].to_value is False


def test_staging_never_asks_a_control_for_its_desired_steps():
    """Nothing in staging may call steps_for(control.desired): for the 14
    no-opinion controls that raises, and it is the wrong question anyway --
    the steps come from what the USER chose, at apply time."""
    control = _control("wsearch", True, desired=None)

    def explode(_value):
        raise AssertionError("staging asked for steps")

    object.__setattr__(control, "steps_for", explode)
    cs = ChangeSet()
    cs.add(control, False)

    assert len(cs) == 1
    assert cs.needs_admin is True


# -- read-only controls are not stageable ------------------------------------

def test_diff_skips_a_control_with_no_steps():
    read_only = _control("firmware", False, on_steps=(), off_steps=(),
                         read_only_reason="it is a firmware setting")
    cs = diff_against({"firmware": read_only}, {"firmware": True})

    assert cs.changes == ()


def test_adding_a_read_only_control_is_refused():
    read_only = _control("firmware", False, on_steps=(), off_steps=(),
                         read_only_reason="it is a firmware setting")
    cs = ChangeSet()

    with pytest.raises(ValueError, match="read-only"):
        cs.add(read_only, True)


# -- housekeeping ------------------------------------------------------------

def test_remove_and_clear():
    cs = ChangeSet()
    cs.add(_control("a", True), False)
    cs.add(_control("b", True), False)
    cs.remove("a")
    assert [c.control_id for c in cs.changes] == ["b"]
    cs.clear()
    assert len(cs) == 0


def test_an_empty_batch_has_the_lowest_risk_and_needs_nothing():
    cs = ChangeSet()
    assert cs.highest_risk is Risk.LOW
    assert cs.needs_admin is False
    assert cs.needs_reboot is False


def test_the_order_changes_were_staged_in_is_kept():
    cs = ChangeSet()
    for cid in ("c", "a", "b"):
        cs.add(_control(cid, True), False)
    assert [c.control_id for c in cs.changes] == ["c", "a", "b"]


# -- "differs" and "could not be read" are not the same batch ----------------
#
# Against the real catalog, unelevated, diff_against stages 60 controls: 46
# that are known to differ from the target, and 14 whose current value could
# not be read at all. Applying those 14 is defensible -- the target says what
# they should be, and Task 11 verifies after writing -- but the review dialog
# must be able to say which is which, rather than showing one number.

def test_a_changeset_can_say_which_changes_it_could_not_read_first():
    cs = ChangeSet()
    cs.add(_control("known", True), False)
    cs.add(_control("blind", None, reader=lambda: {"available": False}), True)

    assert [c.control_id for c in cs.unread_before] == ["blind"]
    assert len(cs) == 2


def test_nothing_is_unread_when_every_value_was_known():
    cs = ChangeSet()
    cs.add(_control("a", True), False, from_value=True)

    assert cs.unread_before == ()


# -- diff_against must not re-read what the caller already has ---------------

def test_diff_against_uses_readings_the_caller_supplies():
    """The pane holds a reading for every card it has drawn. Making
    diff_against read all 149 again costs 12.7s on this machine."""
    control, calls = _counting_control("a", True)

    cs = diff_against({"a": control}, {"a": False}, readings={"a": True})

    assert calls == [], "diff_against read a control the caller had already read"
    assert cs.changes[0].from_value is True


def test_diff_against_reads_only_what_the_caller_left_out():
    known, known_calls = _counting_control("known", True)
    missing, missing_calls = _counting_control("missing", True)

    diff_against({"known": known, "missing": missing},
                 {"known": False, "missing": False},
                 readings={"known": True})

    assert known_calls == []
    assert len(missing_calls) == 1


def test_a_none_reading_supplied_by_the_caller_is_honoured():
    """None in `readings` means the pane rendered "could not read" -- it is an
    answer, and must not send diff_against back to the machine for a second
    opinion."""
    control, calls = _counting_control("a", True)

    cs = diff_against({"a": control}, {"a": False}, readings={"a": None})

    assert calls == []
    assert cs.changes[0].from_value is None
