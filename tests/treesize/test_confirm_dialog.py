"""Spec 7.2: typed confirmation for permanent delete and secure erase.

Recycle and move get a plain confirmation; the two operations with nothing to
undo them get a gate the user has to type their way through. The point is not
ceremony -- it is that a muscle-memory Enter cannot reach them.
"""
from PyQt6.QtWidgets import QDialogButtonBox

from modules.treesize.ui.confirm_dialog import TypedConfirmDialog


def _dialog(**kwargs):
    kwargs.setdefault("title", "Delete permanently")
    kwargs.setdefault("summary", "Delete permanently: 3 item(s), 1.2 GB")
    return TypedConfirmDialog(**kwargs)


def test_ok_is_refused_until_the_phrase_is_typed(qapp):
    dialog = _dialog(phrase="DELETE")
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    dialog.entry.setText("DELETE")
    assert ok.isEnabled()


def test_a_near_miss_does_not_count(qapp):
    dialog = _dialog(phrase="DELETE")
    dialog.entry.setText("DELET")
    assert not dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_case_and_stray_spaces_are_forgiven(qapp):
    """The gate is there to stop a reflex, not to test typing accuracy."""
    dialog = _dialog(phrase="DELETE")
    dialog.entry.setText("  delete ")
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_the_summary_is_shown_not_summarised_away(qapp):
    dialog = _dialog(summary="Delete permanently: 3 item(s), 1.2 GB")
    assert "1.2 GB" in dialog.summary_label.text()


def test_a_caveat_is_displayed_when_there_is_one(qapp):
    """Secure erase ships WITH its limitation stated (spec 7.1)."""
    from modules.treesize.actions.file_ops import SSD_CAVEAT

    dialog = _dialog(phrase="ERASE", caveat=SSD_CAVEAT)
    assert "SSD" in dialog.caveat_label.text()
    assert dialog.caveat_label.isVisibleTo(dialog)


def test_there_is_no_caveat_row_when_there_is_no_caveat(qapp):
    dialog = _dialog(phrase="DELETE")
    assert not dialog.caveat_label.isVisibleTo(dialog)


def test_a_dry_run_is_always_on_offer(qapp):
    """Spec 7.2 wants dry-run available on the destructive paths, which is
    exactly where a user wants to check before committing."""
    dialog = _dialog(phrase="DELETE")
    assert dialog.dry_run is not None
    assert not dialog.dry_run.isChecked()


def test_a_dry_run_needs_no_typing(qapp):
    """Nothing is destroyed by a dry run, so the gate would be theatre."""
    dialog = _dialog(phrase="DELETE")
    dialog.dry_run.setChecked(True)
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()
    dialog.dry_run.setChecked(False)
    assert not dialog.buttons.button(
        QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_cancel_is_the_default_button(qapp):
    """Enter must not be able to confirm a permanent delete."""
    dialog = _dialog(phrase="DELETE")
    assert dialog.buttons.button(
        QDialogButtonBox.StandardButton.Cancel).isDefault()
