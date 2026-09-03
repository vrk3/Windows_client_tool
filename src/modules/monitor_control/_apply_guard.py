r"""Snapshot, apply, count down, revert.

Every display change goes through here. A resolution or refresh rate a
monitor cannot show leaves you looking at "no signal", and the control that
would put it back is on a screen you can no longer read — so the change
undoes itself unless someone confirms it. Windows does the same thing for the
same reason.

Two rules matter more than the countdown:

* **The confirm must land on a screen that still exists after the change.**
  Parenting it to the display the change just switched off is precisely the
  failure this guard exists to prevent.
* **A failed apply starts no countdown**, and a change with no way back never
  happens at all. If the snapshot cannot be taken, there is no undo, so the
  change is refused rather than attempted hopefully.

The decision logic is kept as plain functions so it can be tested without a
display; only `CountdownOverlay` needs Qt.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: Long enough to read the dialog and reach the mouse, short enough that a
#: black screen is not frightening. Windows uses 15 too.
COUNTDOWN_SECONDS = 15


class Outcome(enum.Enum):
    KEPT = "kept"
    REVERTED = "reverted"
    REVERT_FAILED = "revert-failed"


@dataclass
class ApplyResult:
    applied: bool
    error: str = ""


def choose_confirm_screen(affected: Any,
                          present: Sequence[Any]) -> Optional[Any]:
    """Where to put the confirm, given what is still attached.

    The affected screen when it survived the change — that is where the user
    is looking. Otherwise any screen that is still there; the point is that
    the button exists somewhere reachable, not which monitor it is on.
    """
    if not present:
        return None
    if affected is not None and affected in present:
        return affected
    return present[0]


def resolve(confirmed: bool, snapshot: Any,
            restore: Callable[[Any], None]) -> Outcome:
    """Keep the change, or put the old configuration back.

    A revert that itself fails is reported, never swallowed: the user is
    sitting in front of a configuration nobody chose, and silence is the
    worst possible answer.
    """
    if confirmed:
        return Outcome.KEPT
    try:
        restore(snapshot)
    except Exception:                                    # noqa: BLE001
        logger.exception("Reverting the display change failed")
        return Outcome.REVERT_FAILED
    return Outcome.REVERTED


def run_apply(snapshot: Callable[[], Any], apply: Callable[[], Any],
              start_countdown: Callable[[Any], None]) -> ApplyResult:
    """Take the snapshot, make the change, then arm the countdown.

    Strictly in that order. The snapshot is the undo, so a change made before
    one exists is a change that cannot be taken back.
    """
    try:
        before = snapshot()
    except Exception as exc:                             # noqa: BLE001
        logger.warning("Refusing a display change with no way back: %s", exc)
        return ApplyResult(applied=False, error=str(exc))

    try:
        apply()
    except Exception as exc:                             # noqa: BLE001
        logger.warning("Display change failed: %s", exc)
        return ApplyResult(applied=False, error=str(exc))

    start_countdown(before)
    return ApplyResult(applied=True)


# ── the Qt half ────────────────────────────────────────────────────────

def build_countdown(parent_screen, seconds: int = COUNTDOWN_SECONDS):
    """A countdown panel on `parent_screen`, or None if there is nowhere.

    Imported lazily so the decision logic above stays importable — and
    testable — with no Qt and no display.
    """
    if parent_screen is None:
        return None
    from modules.monitor_control._screen_overlay import ScreenOverlay

    overlay = ScreenOverlay(parent_screen, interactive=True)
    overlay.show_text(str(seconds), "Keep these changes?")
    return overlay


def present_screens() -> List[Any]:
    """The screens Qt can still see. Asked fresh, never cached.

    A stored QScreen says nothing about whether its monitor is still there;
    after a topology change some of them are gone.
    """
    from PyQt6.QtWidgets import QApplication

    return list(QApplication.screens())
