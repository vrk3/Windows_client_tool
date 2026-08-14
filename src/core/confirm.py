"""Standardized confirmation dialog for destructive actions.

Scaffolding only. Modules across the codebase currently hand-roll their own
QMessageBox.question()/.warning() calls for "are you sure?" prompts before
deleting files, stopping services, disabling startup items, etc. — each with
slightly different button sets/defaults/wording. This helper exists so *new*
destructive actions have one consistent, safe-by-default dialog to call.

Existing call sites are intentionally NOT retrofitted here — swapping dozens
of already-working confirmation dialogs for a cosmetic wording change is a
large, low-value diff. New code should prefer this helper over another
raw QMessageBox call.
"""
from typing import Optional

from PyQt6.QtWidgets import QMessageBox, QWidget


def confirm_destructive(
    parent: Optional[QWidget],
    title: str,
    message: str,
    *,
    detail: str = "",
    irreversible: bool = True,
) -> bool:
    """Show a Yes/No warning dialog defaulting to No, for a destructive action.

    `message` is the primary question, e.g. "Delete 12 file(s) (340 MB)?".
    `detail` is optional extra context appended below (paths, counts, etc).
    `irreversible` appends a standard "This cannot be undone." line — set
    False for actions that are destructive but recoverable (e.g. anything
    already covered by a restore point).

    Returns True only if the user explicitly clicked Yes — closing the
    dialog, pressing Escape, or clicking No all return False.
    """
    text = message
    if detail:
        text = f"{text}\n\n{detail}"
    if irreversible:
        text = f"{text}\n\nThis cannot be undone."

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    return box.exec() == QMessageBox.StandardButton.Yes
