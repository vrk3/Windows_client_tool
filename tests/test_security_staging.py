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


# ============================================================================
# Task 10: a cmdlet control's revert is computed from what was there before
# ============================================================================

def test_a_script_step_gets_a_revert_command_built_from_the_current_value():
    """BackupService cannot revert a script step without one, and a static
    revert command in the catalog cannot know what it is reverting TO."""
    control = _control(
        "rt", True,
        on_steps=({"type": "script",
                   "command": "Set-MpPreference -DisableRealtimeMonitoring $false",
                   "revert_template": "Set-MpPreference -DisableRealtimeMonitoring ${old}",
                   "revert_values": {"True": "$false", "False": "$true"}},),
        off_steps=({"type": "script",
                    "command": "Set-MpPreference -DisableRealtimeMonitoring $true",
                    "revert_template": "Set-MpPreference -DisableRealtimeMonitoring ${old}",
                    "revert_values": {"True": "$false", "False": "$true"}},))
    cs = ChangeSet()
    cs.add(control, False)
    step = cs.changes[0].resolved_steps()[0]
    assert step["revert_command"] == (
        "Set-MpPreference -DisableRealtimeMonitoring $false")


def test_a_registry_step_needs_no_revert_command():
    """BackupService restores the recorded before_value exactly, including
    deleting a value that did not exist. Do not invent one."""
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)
    assert "revert_command" not in cs.changes[0].resolved_steps()[0]


def test_an_unreadable_current_value_yields_no_revert_command():
    """Better no revert than a revert to a value we guessed."""
    control = _control(
        "rt", None, reader=lambda: {"available": False},
        on_steps=({"type": "script", "command": "x",
                   "revert_template": "y ${old}",
                   "revert_values": {"True": "$false"}},))
    cs = ChangeSet()
    cs.add(control, True)
    assert cs.changes[0].resolved_steps()[0].get("revert_command") is None


def test_resolving_does_not_mutate_the_catalogs_own_step():
    """The catalog's dicts are shared between every ChangeSet in the process.
    resolved_steps() works on copies; if it popped from the original, the
    second batch of the session would find no revert template at all."""
    step = {"type": "script", "command": "x", "revert_template": "y ${old}",
            "revert_values": {"True": "$false"}}
    control = _control("rt", True, on_steps=(step,), off_steps=(step,))

    cs = ChangeSet()
    cs.add(control, False)
    cs.changes[0].resolved_steps()

    assert "revert_template" in step and "revert_values" in step


def test_a_numeric_control_reverts_to_its_own_number():
    """CloudExtendedTimeout is 0-50: a lookup table of every value would be
    absurd, so a number reverts to itself."""
    control = _control(
        "timeout", 30,
        on_steps=({"type": "script", "command": "Set-X -T 50",
                   "revert_template": "Set-X -T ${old}"},),
        off_steps=({"type": "script", "command": "Set-X -T 0",
                    "revert_template": "Set-X -T ${old}"},))
    cs = ChangeSet()
    cs.add(control, 50)

    assert cs.changes[0].resolved_steps()[0]["revert_command"] == "Set-X -T 30"


def test_a_string_value_is_never_pasted_into_a_command_unmapped():
    """from_value comes off the machine. A bare string substituted into a
    shell command is an injection surface, so a non-numeric value reverts
    only through an explicit map."""
    control = _control(
        "policy", "Bypass; rm -rf /",
        on_steps=({"type": "script", "command": "Set-ExecutionPolicy X",
                   "revert_template": "Set-ExecutionPolicy ${old}"},),
        off_steps=({"type": "script", "command": "Set-ExecutionPolicy Y",
                    "revert_template": "Set-ExecutionPolicy ${old}"},))
    cs = ChangeSet()
    cs.add(control, "Restricted")

    assert cs.changes[0].resolved_steps()[0].get("revert_command") is None


def test_a_value_the_map_does_not_cover_yields_no_revert():
    """The threat-action controls are exactly this: Get-MpPreference reports 0
    for an unconfigured severity, and 0 is not a member of the ThreatAction
    enum, so there IS no command that reverts to it. Saying nothing is the
    honest answer."""
    control = _control(
        "threat", 0,
        on_steps=({"type": "script", "command": "Set-MpPreference -X Quarantine",
                   "revert_template": "Set-MpPreference -X ${old}",
                   "revert_values": {"2": "Quarantine", "3": "Remove"}},),
        off_steps=({"type": "script", "command": "Set-MpPreference -X None",
                    "revert_template": "Set-MpPreference -X ${old}",
                    "revert_values": {"2": "Quarantine", "3": "Remove"}},))
    cs = ChangeSet()
    cs.add(control, 2)

    assert cs.changes[0].resolved_steps()[0].get("revert_command") is None


def test_resolved_steps_uses_the_target_the_user_chose():
    control = _control("a", True)
    cs = ChangeSet()
    cs.add(control, False)

    assert cs.changes[0].resolved_steps()[0]["data"] == 0


# -- the gate: no script step in the real catalog may lack a revert ----------

def test_every_script_step_in_the_catalog_can_compute_a_revert():
    """A `script` step is the one kind BackupService cannot undo on its own --
    it records no before-value for a command. If the catalog ships one with no
    revert_template, that control is a one-way door, silently.
    """
    from modules.security_dashboard.catalog import load_catalog

    missing = []
    for cid, control in load_catalog().items():
        for step in control.on_steps + control.off_steps:
            if step.get("type") == "script" and "revert_template" not in step:
                missing.append(f"{cid}: {step['command'][:60]}")

    assert not missing, (
        f"{len(missing)} script steps have no way back:\n  "
        + "\n  ".join(missing))


# -- which staged changes have no way back -----------------------------------
#
# BackupService reverts a `registry` step from its recorded before-value and a
# `service` step from its recorded start type. It records NOTHING for a
# `command`, and for a `script` only the revert_command computed above. So a
# batch can contain changes that simply cannot be undone by this tool, and the
# review dialog has to be able to say which.

def test_a_registry_change_is_revertible():
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)

    assert cs.changes[0].one_way_steps() == ()


def test_a_command_step_is_a_one_way_door():
    control = _control("feature", True,
                       on_steps=({"type": "command", "cmd": "dism /enable"},),
                       off_steps=({"type": "command", "cmd": "dism /disable"},))
    cs = ChangeSet()
    cs.add(control, False)

    assert len(cs.changes[0].one_way_steps()) == 1


def test_a_script_step_with_a_computed_revert_is_not_one_way():
    control = _control(
        "rt", True,
        on_steps=({"type": "script", "command": "x",
                   "revert_template": "y ${old}",
                   "revert_values": {"True": "on", "False": "off"}},),
        off_steps=({"type": "script", "command": "x2",
                    "revert_template": "y ${old}",
                    "revert_values": {"True": "on", "False": "off"}},))
    cs = ChangeSet()
    cs.add(control, False)

    assert cs.changes[0].one_way_steps() == ()


def test_a_script_step_whose_revert_could_not_be_computed_is_one_way():
    """The threat-action controls on a machine where nothing is configured:
    from_value 0, and no command sets a severity back to 0."""
    control = _control(
        "threat", 0,
        on_steps=({"type": "script", "command": "set Quarantine",
                   "revert_template": "set ${old}",
                   "revert_values": {"2": "Quarantine"}},),
        off_steps=({"type": "script", "command": "set None",
                    "revert_template": "set ${old}",
                    "revert_values": {"2": "Quarantine"}},))
    cs = ChangeSet()
    cs.add(control, 2)

    assert len(cs.changes[0].one_way_steps()) == 1


def test_the_batch_can_count_its_one_way_changes():
    cs = ChangeSet()
    cs.add(_control("safe", True), False)
    cs.add(_control("risky", True,
                    on_steps=({"type": "command", "cmd": "a"},),
                    off_steps=({"type": "command", "cmd": "b"},)), False)

    assert [c.control_id for c in cs.one_way_changes] == ["risky"]
