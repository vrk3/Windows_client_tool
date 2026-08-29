"""Nothing applies until Apply, and the report tells the truth about what did."""
import pytest

from modules.security_dashboard.applier import BatchResult, ControlResult
from modules.security_dashboard.catalog.model import (
    Category, ControlState, SecurityControl)
from modules.security_dashboard.security_module import (
    PendingBar, ResultDialog, ReviewDialog)
from modules.security_dashboard.staging import ChangeSet


def _control(cid="llmnr", **over):
    base = dict(
        id=cid, title=cid, category=Category.FIREWALL_NETWORK,
        description="d", why_it_matters="w",
        reader=lambda: {"available": True, "enabled": True},
        on_steps=({"type": "registry",
                   "key": "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Dnscache",
                   "value": "EnableMulticast", "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry",
                    "key": "HKLM\\SYSTEM\\CurrentControlSet\\Services\\Dnscache",
                    "value": "EnableMulticast", "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


@pytest.fixture
def staged_changeset():
    changeset = ChangeSet()
    changeset.add(_control(), False, from_value=True)
    return changeset


def test_the_review_shows_the_literal_steps_that_will_run(qapp, staged_changeset):
    dialog = ReviewDialog(staged_changeset)
    text = dialog.details_text()
    assert "EnableMulticast" in text, "the user must see what will be written"


def test_a_partly_successful_batch_does_not_look_like_a_successful_one(qapp):
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult("a", ControlState.APPLIED_VERIFIED, False, False),
        ControlResult("b", ControlState.REFUSED, False, True, "Access is denied."),
        ControlResult("c", ControlState.APPLIED_UNVERIFIED, False, True,
                      "still reads True"),
    ])
    dialog = ResultDialog(result)
    summary = dialog.summary_text()
    assert "1" in summary and "3" in summary
    assert "Access is denied" in dialog.details_text()


def test_an_unverified_control_shows_both_values(qapp):
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult("c", ControlState.APPLIED_UNVERIFIED, False, True, "r")])
    text = ResultDialog(result).details_text()
    assert "False" in text and "True" in text


def test_a_reboot_batch_asks_once_at_the_end_not_once_per_control(qapp):
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult(cid, ControlState.APPLIED_PENDING_REBOOT, False, True, "")
        for cid in ("a", "b", "c")])
    dialog = ResultDialog(result)
    assert dialog.reboot_prompts() == 1


# --- the rest are not in the plan ------------------------------------------


def test_the_review_separates_what_differs_from_what_could_not_be_read(qapp):
    """ChangeSet.unread_before exists because one number hides this: a full
    baseline on this machine stages 60 changes, 46 that differ from what you
    want and 14 that were never readable. Applying the second kind is
    defensible; not saying which is which is not."""
    changeset = ChangeSet()
    changeset.add(_control("a"), False, from_value=True)
    changeset.add(_control("b"), False, from_value=None)   # never readable
    text = ReviewDialog(changeset).details_text()
    assert "could not be read" in text.lower()


def test_the_review_names_what_cannot_be_undone(qapp):
    """19 of a 60-change baseline here are one-way: the four threat actions
    plus fifteen command steps. BackupService records nothing for a command."""
    one_way = _control("cmd_one", on_steps=(), off_steps=(
        {"type": "command", "cmd": "net accounts /minpwlen:14"},))
    changeset = ChangeSet()
    changeset.add(one_way, False, from_value=True)
    text = ReviewDialog(changeset).details_text()
    assert "cannot be undone" in text.lower()


def test_the_review_says_when_a_restart_is_needed(qapp):
    changeset = ChangeSet()
    changeset.add(_control("cg", requires_reboot=True), False, from_value=True)
    assert "restart" in ReviewDialog(changeset).details_text().lower()


def test_a_refusal_in_the_report_keeps_its_whole_text_but_leads_with_one_line(qapp):
    """A refused Set-MpPreference is twelve lines of PowerShell formatting."""
    reason = ("Set-MpPreference : You don't have enough permissions.\n"
              "At line:1 char:1\n+ Set-MpPreference -DisableArchiveScanning\n"
              "    + CategoryInfo : NotSpecified")
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult("b", ControlState.REFUSED, False, True, reason)])
    dialog = ResultDialog(result)
    assert dialog.summary_lines()[0].count("\n") == 0
    assert "CategoryInfo" in dialog.details_text()


def test_a_helper_that_could_not_run_says_so_instead_of_showing_nothing(qapp):
    """The elevated child writes `error` when it could not run at all. An
    empty result list with no explanation reads as 'nothing happened'."""
    result = BatchResult(rp_id="", results=[],
                         error="BackupService could not open its database")
    text = ResultDialog(result).summary_text()
    assert "could not open its database" in text


def test_the_pending_bar_is_hidden_until_something_is_staged(qapp):
    """isHidden(), not isVisibleTo(): once the bar has a parent that has never
    been shown, isVisibleTo answers False however the bar itself was set."""
    bar = PendingBar()
    assert bar.isHidden()
    changeset = ChangeSet()
    changeset.add(_control(), False, from_value=True)
    bar.set_changeset(changeset)
    assert not bar.isHidden()
    assert "1" in bar.summary_label.text()


def test_the_pending_bar_does_not_stretch_when_it_is_the_only_thing_added(qapp):
    """The d57cdf2 trap: a widget added to a QVBoxLayout with no stretch
    factor and nothing Expanding takes an equal share of the surplus."""
    from PyQt6.QtWidgets import QSizePolicy
    bar = PendingBar()
    assert bar.sizePolicy().verticalPolicy() != QSizePolicy.Policy.Expanding


def test_a_batch_that_needs_a_reboot_says_so_once_in_the_review(qapp):
    changeset = ChangeSet()
    for cid in ("a", "b", "c"):
        changeset.add(_control(cid, requires_reboot=True), False,
                      from_value=True)
    text = ReviewDialog(changeset).details_text().lower()
    assert text.count("restart the machine") == 1


# --- the apply flow, wired into the pane ------------------------------------

@pytest.fixture
def module(qapp, monkeypatch):
    from modules.security_dashboard.security_module import (
        SecurityDashboardModule)
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.QThreadPool.globalInstance",
        lambda: type("Pool", (), {"start": lambda _s, _w: None})())
    shown = []
    mod = SecurityDashboardModule()
    mod.on_start(None)
    mod._held = mod.create_widget()
    # No modal dialogs: .exec() from a handler blocks the event loop until
    # somebody clicks, and nobody is going to.
    mod._show_result_dialog = lambda result: shown.append(result)
    mod._ask_review = lambda changeset: True
    yield mod
    mod.on_stop()


def _stage_one(module):
    control = next(c for c in module.catalog.values()
                   if c.writable and isinstance(c.desired, bool))
    module._readings[control.id] = not control.desired
    module._on_card_staged(control.id, control.desired)
    return control


def test_the_pending_bar_appears_when_a_card_is_staged(module):
    assert module._pending.isHidden()
    _stage_one(module)
    assert not module._pending.isHidden()
    assert "1 change staged" in module._pending.summary_label.text()


def test_discarding_clears_the_staged_changes_and_the_cards(module):
    control = _stage_one(module)
    module.show_category_tab(control.category.value)
    module._on_discard_requested()
    assert len(module.changeset) == 0
    card = module._card_for(control.id)
    if card is not None:
        assert card.staged_label.text() == ""


def test_apply_with_nothing_staged_starts_no_batch(module):
    started = []
    module._dispatch = lambda worker: started.append(worker)
    module._on_apply_requested()
    assert started == []


def test_a_second_apply_while_one_is_running_starts_nothing(module):
    started = []
    module._dispatch = lambda worker: started.append(worker)
    _stage_one(module)
    module._on_apply_requested()
    module._on_apply_requested()
    assert len(started) == 1


def test_a_helper_that_reported_nothing_is_not_reported_as_success(module):
    """No result file means UNKNOWN. Showing "applied" there would be a lie,
    and showing "failed" would be a different one -- the child may well have
    written everything before dying."""
    refreshed = []
    module._manual_refresh = lambda: refreshed.append(1)
    control = _stage_one(module)
    module._on_batch_result(None)
    assert refreshed == [1]
    assert len(module.changeset) == 1, "nothing was applied, so nothing clears"


def test_a_batch_result_updates_the_cards_and_the_pane_readings(module):
    from modules.security_dashboard.applier import BatchResult, ControlResult
    control = _stage_one(module)
    module.show_category_tab(control.category.value)
    module._on_batch_result(BatchResult(rp_id="rp-1", results=[
        ControlResult(control.id, ControlState.APPLIED_VERIFIED,
                      control.desired, control.desired, "")]))
    assert module._readings[control.id] == control.desired
    assert len(module.changeset) == 0


def test_applying_without_a_backup_service_refuses_rather_than_writing(module):
    """No restore point, no way back. Writing anyway is how a tool becomes
    the thing you cannot undo."""
    module.app = None
    with pytest.raises(RuntimeError, match="way back"):
        module._apply_in_process()


def test_the_review_puts_the_totals_where_they_will_be_read(qapp):
    """Found by rendering a real 60-change baseline: the counts were at the
    BOTTOM of a list nobody scrolls to the end of."""
    changeset = ChangeSet()
    changeset.add(_control("a"), False, from_value=None)
    changeset.add(_control("b", requires_reboot=True), False, from_value=True)
    heading = ReviewDialog(changeset)._heading_text().lower()
    assert "could not be read" in heading
    assert "restart" in heading


def test_the_report_does_not_show_enum_values_to_a_person(qapp):
    """"applied_pending_reboot" is a value in an enum, not a sentence."""
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult("a", ControlState.APPLIED_PENDING_REBOOT, False, True, "")])
    text = ResultDialog(result).details_text()
    assert "applied_pending_reboot" not in text
    assert "awaiting a restart" in text
