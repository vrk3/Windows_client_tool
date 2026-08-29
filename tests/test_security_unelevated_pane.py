r"""Unelevated, this pane was disabled outright. It did not need to be.

`requires_admin = True` makes ModuleRegistry.start_all() refuse to start the
module at all, so an ordinary user got a greyed-out sidebar entry and nothing
else. Two things say that was too blunt:

* **112 of the 149 controls read fine without elevation** -- an elevated run
  and an unelevated one, diffed with `security_catalog_check.py --compare`,
  disagree on 38. After the 2026-08-29 work they also read FAST unelevated:
  every tab is now ~1-2s, where Device & Boot alone used to be 16.79s.
* **The apply path already handles being unelevated.** `_on_apply` branches on
  `is_admin()` and hands the batch to `run_elevated_batch()` -- the helper
  built for exactly this, one UAC prompt reporting back through a file. That
  branch could never run in the real app, because the module was disabled
  before anyone could reach it.

So the pane opens, reads what it can, says plainly what it could not read,
and prompts for elevation only when somebody actually applies something.
A control that cannot be READ already reports itself unavailable -- that
discipline is what the rest of this module is built on.
"""
import pytest

from modules.security_dashboard import security_module as sm
from modules.security_dashboard.security_module import SecurityDashboardModule


def test_the_pane_is_not_gated_behind_elevation():
    """ModuleRegistry.start_all() disables the whole module on this flag."""
    assert SecurityDashboardModule.requires_admin is False


def test_an_unelevated_apply_goes_through_the_elevation_helper(monkeypatch):
    """The branch that could never be reached. It is the reason the pane can
    be opened without admin at all: reads are best-effort, writes prompt."""
    monkeypatch.setattr(sm, "is_admin", lambda: False)
    sent = []
    monkeypatch.setattr(sm, "run_elevated_batch",
                        lambda changes, **kw: sent.append(changes) or "done")

    module = SecurityDashboardModule()
    module.on_start(None)
    in_process = []
    monkeypatch.setattr(module, "_apply_in_process",
                        lambda: in_process.append(1))

    outcome = module._elevated_or_in_process([("some", "change")])

    assert outcome == "done"
    assert sent == [[("some", "change")]]
    assert in_process == [], "it wrote in a process that cannot write"


def test_an_elevated_apply_stays_in_process(monkeypatch):
    monkeypatch.setattr(sm, "is_admin", lambda: True)
    monkeypatch.setattr(sm, "run_elevated_batch",
                        lambda changes, **kw: pytest.fail(
                            "it asked for a UAC prompt it did not need"))

    module = SecurityDashboardModule()
    module.on_start(None)
    monkeypatch.setattr(module, "_apply_in_process", lambda: "applied")

    assert module._elevated_or_in_process([("some", "change")]) == "applied"


def test_an_unelevated_pane_says_so(qapp, monkeypatch):
    """Per-control "Requires administrator" is true but scattered; the pane
    says once, up front, that this is a partial view and that changes will
    ask for elevation."""
    monkeypatch.setattr(sm, "is_admin", lambda: False)

    module = SecurityDashboardModule()
    module.on_start(None)
    widget = module.create_widget()
    try:
        note = module._elevation_note()
        assert note, "nothing told the user this is an unelevated view"
        lowered = note.lower()
        assert "administrator" in lowered
        assert any(word in lowered for word in ("some", "not all", "cannot"))
    finally:
        widget.deleteLater()
        module.on_stop()


def test_the_note_actually_reaches_the_pane(qapp, monkeypatch):
    """`AppCatalog.remove_appx` was fully implemented and called by no UI path
    for as long as it existed. A note nobody renders is the same bug."""
    from PyQt6.QtWidgets import QLabel

    monkeypatch.setattr(sm, "is_admin", lambda: False)
    module = SecurityDashboardModule()
    module.on_start(None)
    widget = module.create_widget()
    try:
        shown = [lbl.text() for lbl in widget.findChildren(QLabel)
                 if lbl.isVisibleTo(widget)]
        assert any("administrator" in text.lower() for text in shown), (
            f"the pane never displays the note; labels were {shown}")
    finally:
        widget.deleteLater()
        module.on_stop()


def test_an_elevated_pane_does_not_show_the_note(qapp, monkeypatch):
    from PyQt6.QtWidgets import QLabel

    monkeypatch.setattr(sm, "is_admin", lambda: True)
    module = SecurityDashboardModule()
    module.on_start(None)
    widget = module.create_widget()
    try:
        shown = [lbl.text() for lbl in widget.findChildren(QLabel)
                 if lbl.isVisibleTo(widget)]
        assert not any("without administrator" in text.lower()
                       for text in shown)
    finally:
        widget.deleteLater()
        module.on_stop()


def test_an_elevated_pane_has_nothing_to_apologise_for(qapp, monkeypatch):
    monkeypatch.setattr(sm, "is_admin", lambda: True)

    module = SecurityDashboardModule()
    module.on_start(None)
    widget = module.create_widget()
    try:
        assert module._elevation_note() == ""
    finally:
        widget.deleteLater()
        module.on_stop()
