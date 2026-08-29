"""Revert restores what was recorded, and is then checked like any other write.

_ToggleCard.configure defaulted revert_fn to toggle_fn, so Revert called the
setter with the opposite argument -- a guess about the previous value, and
simply wrong for anything multi-valued. BackupService already records the real
before_value and deletes a value that did not exist before.

A revert is a WRITE, so the rule from applier.py applies to it unchanged: the
fact that BackupService returned success is not evidence the machine moved.
"""
from modules.security_dashboard.catalog.model import (
    Category, ControlState, SecurityControl)
from modules.security_dashboard.reverting import revert_batch, revert_control


class _Backup:
    def __init__(self, ok=True): self.ok, self.reverted = ok, []
    def revert_tweak(self, tweak_id):
        self.reverted.append(tweak_id)
        return type("R", (), {"success": self.ok, "partial": False,
                              "failed_steps": [], "errors": ["denied"]})()


def _control(cid, readings, **over):
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": readings.pop(0)},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_revert_delegates_to_the_recorded_steps():
    backup = _Backup()
    revert_control("llmnr", backup, {"llmnr": _control("llmnr", [True])})
    assert backup.reverted == ["llmnr"]


def test_a_revert_that_did_not_take_is_reported_not_assumed():
    catalog = {"llmnr": _control("llmnr", [False])}
    result = revert_control("llmnr", _Backup(ok=False), catalog)
    assert result.state is ControlState.REFUSED


# --- the rest are not in the plan ------------------------------------------
#
# The plan's revert_control reads the control and then reports
# APPLIED_VERIFIED whenever BackupService returned success -- without
# comparing that reading to anything. That is the exact shape applier.py
# exists to prevent, one module over.


class _BatchBackup:
    """restore_point() reverts a whole session and names what it touched."""

    def __init__(self, ids, ok=True):
        self.ids, self.ok, self.calls = ids, ok, []

    def control_ids_in(self, rp_id):
        return list(self.ids)

    def restore_point(self, rp_id):
        self.calls.append(("restore_point", rp_id))
        return type("R", (), {
            "success": self.ok, "partial": False, "failed_steps": [],
            "errors": [], "reverted_ids": list(self.ids), "failed_ids": []})()

    def revert_tweak(self, tweak_id):
        self.calls.append(("revert_tweak", tweak_id))
        return type("R", (), {"success": True, "partial": False,
                              "failed_steps": [], "errors": []})()


def test_a_revert_that_moved_nothing_is_not_reported_as_success():
    """BackupService said it worked; the setting did not budge."""
    catalog = {"llmnr": _control("llmnr", [True, True])}
    result = revert_control("llmnr", _Backup(), catalog)
    assert result.state is ControlState.APPLIED_UNVERIFIED
    assert result.observed is True


def test_a_revert_that_moved_the_setting_is_verified():
    catalog = {"llmnr": _control("llmnr", [False, True])}
    result = revert_control("llmnr", _Backup(), catalog)
    assert result.state is ControlState.APPLIED_VERIFIED
    assert result.observed is True


def test_a_known_prior_value_is_what_the_revert_is_checked_against():
    """Landing on SOME other value is not landing on the right one.

    A multi-valued control -- NTLM level, cloud block level, a threat action --
    can move and still be wrong. When the caller knows what the machine had
    before the change (the pane holds it: staging recorded from_value and the
    batch file carried it through the UAC prompt), that is the target.
    """
    catalog = {"ntlm": _control("ntlm", [5, 3])}   # was 5, reverts to 3, wanted 2
    result = revert_control("ntlm", _Backup(), catalog, expected=2)
    assert result.state is ControlState.APPLIED_UNVERIFIED
    assert result.requested == 2 and result.observed == 3

    catalog = {"ntlm": _control("ntlm", [5, 2])}
    assert revert_control("ntlm", _Backup(), catalog,
                          expected=2).state is ControlState.APPLIED_VERIFIED


def test_a_reboot_control_is_not_called_unverified_before_the_reboot():
    catalog = {"cg": _control("cg", [True, True], requires_reboot=True)}
    result = revert_control("cg", _Backup(), catalog)
    assert result.state is ControlState.APPLIED_PENDING_REBOOT


def test_the_snapshot_caches_are_dropped_before_the_check():
    """Same trap as apply: 135 readers answer from a cache with no expiry, so
    the read after the revert would be the value from before it."""
    dropped = []
    catalog = {"llmnr": _control("llmnr", [False, True])}
    revert_control("llmnr", _Backup(), catalog,
                   invalidate_reads=lambda: dropped.append(1))
    assert dropped == [1]


def test_a_batch_revert_reverts_once_and_then_verifies():
    """The plan reverted the whole restore point AND each control again.

    restore_point() has already undone every step in the session; calling
    revert_tweak() per control afterwards is a second revert of work that is
    no longer applied -- at best a no-op that reports failure, at worst it
    unwinds an earlier session's steps for the same tweak.
    """
    backup = _BatchBackup(["llmnr", "wdigest"])
    catalog = {"llmnr": _control("llmnr", [False, True]),
               "wdigest": _control("wdigest", [False, True])}
    result = revert_batch("rp-1", backup, catalog)
    assert backup.calls == [("restore_point", "rp-1")], backup.calls
    assert [r.control_id for r in result.results] == ["llmnr", "wdigest"]
    assert all(r.state is ControlState.APPLIED_VERIFIED for r in result.results)


def test_a_batch_revert_drops_the_caches_once_for_the_whole_session():
    dropped = []
    backup = _BatchBackup(["llmnr", "wdigest"])
    catalog = {"llmnr": _control("llmnr", [False, True]),
               "wdigest": _control("wdigest", [False, True])}
    revert_batch("rp-1", backup, catalog,
                 invalidate_reads=lambda: dropped.append(1))
    assert dropped == [1]


def test_a_control_whose_steps_failed_to_revert_is_named_as_refused():
    backup = _BatchBackup(["llmnr"], ok=False)
    catalog = {"llmnr": _control("llmnr", [True, True])}
    result = revert_batch("rp-1", backup, catalog)
    assert result.results[0].state is ControlState.REFUSED


def test_a_batch_revert_uses_the_prior_values_it_is_given():
    backup = _BatchBackup(["ntlm"])
    catalog = {"ntlm": _control("ntlm", [5, 3])}
    result = revert_batch("rp-1", backup, catalog, expected={"ntlm": 2})
    assert result.results[0].state is ControlState.APPLIED_UNVERIFIED
    assert result.results[0].requested == 2


def test_a_control_the_catalog_no_longer_has_is_unknown_not_verified():
    """A restore point from an older build naming a control this one dropped."""
    backup = _BatchBackup(["gone"])
    result = revert_batch("rp-1", backup, {})
    assert result.results[0].state is ControlState.APPLIED_UNVERIFIED
    assert result.results[0].observed is None
