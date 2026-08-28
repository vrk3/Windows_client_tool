"""Changes stage, then apply as one batch. Nothing here touches the machine.

Two rules this module enforces, both of which exist because of something that
already went wrong elsewhere in this project:

* **Staging never reads the machine when the caller already knows the value.**
  `add()` takes an optional `from_value`; a card that has just rendered a
  reading passes it. Reading per click is the per-field-PowerShell trap the
  snapshot layer exists to remove, reintroduced in the UI -- and it is not
  theoretical, since `bitlocker_encryption_detail.read()` costs 6.11s on the
  machine this was written on.

* **A control cannot be staged to no value.** `SecurityControl.steps_for(None)`
  raises rather than quietly returning `off_steps`, because the old behaviour
  would have turned Windows Search off on a control the catalog explicitly has
  no opinion about. Staging `None` as a TARGET would reach that at apply time,
  in a worker thread, with no user in front of it. It is refused here instead,
  where the message can still name the control.
"""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .catalog.model import Risk, SecurityControl


class _Unread:
    """Sentinel: the caller did not say what the current value is.

    Distinct from None, which is a real answer meaning "the machine could not
    be read" -- a control may be staged precisely because it could not be.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unread>"


_UNREAD = _Unread()


@dataclass(frozen=True)
class PendingChange:
    control_id: str
    control: SecurityControl
    from_value: Optional[Any]
    to_value: Any


class ChangeSet:
    """Staged changes, keyed by control id.

    Staging a control back to the value it already has removes it rather than
    queueing a no-op, so the pending count is always the number of things that
    would actually happen.
    """

    def __init__(self) -> None:
        self._changes: Dict[str, PendingChange] = {}

    def add(self, control: SecurityControl, to_value: Any,
            from_value: Any = _UNREAD) -> None:
        """Stage `control` to `to_value`.

        `from_value` is the current value if the caller already has it --
        pass it and the machine is not read again. Omit it and the control is
        read once, here.
        """
        if to_value is None:
            raise ValueError(
                f"control {control.id!r} cannot be staged to no value: "
                "a target of None has no steps to apply")
        if not control.writable:
            raise ValueError(
                f"control {control.id!r} is read-only: {control.read_only_reason}")
        current = control.read() if isinstance(from_value, _Unread) else from_value
        if current == to_value:
            self._changes.pop(control.id, None)
            return
        self._changes[control.id] = PendingChange(
            control_id=control.id, control=control,
            from_value=current, to_value=to_value)

    def remove(self, control_id: str) -> None:
        self._changes.pop(control_id, None)

    def clear(self) -> None:
        self._changes.clear()

    @property
    def changes(self) -> Tuple[PendingChange, ...]:
        """In the order they were staged -- dicts keep insertion order, and
        the review dialog shows them in the order the user clicked."""
        return tuple(self._changes.values())

    def __len__(self) -> int:
        return len(self._changes)

    def __contains__(self, control_id: object) -> bool:
        return control_id in self._changes

    @property
    def unread_before(self) -> Tuple[PendingChange, ...]:
        """Staged changes whose current value could not be read.

        Applying these is defensible -- the target says what they should be,
        and the apply path verifies afterwards -- but they are a different
        thing from "this differs from what you want", and the review dialog
        has to be able to say which is which. Against the real catalog,
        unelevated, a full baseline stages 60 changes of which 14 are these.
        """
        return tuple(c for c in self._changes.values() if c.from_value is None)

    @property
    def needs_admin(self) -> bool:
        return any(c.control.requires_admin for c in self._changes.values())

    @property
    def needs_reboot(self) -> bool:
        return any(c.control.requires_reboot for c in self._changes.values())

    @property
    def highest_risk(self) -> Risk:
        order = {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}
        return max((c.control.risk for c in self._changes.values()),
                   key=lambda r: order[r], default=Risk.LOW)


def diff_against(catalog: Dict[str, SecurityControl],
                 target: Dict[str, Any],
                 readings: Optional[Dict[str, Any]] = None) -> ChangeSet:
    """Stage everything in `target` that differs from the live machine.

    `readings` is what the caller already knows -- the pane holds a value for
    every card it has drawn. A control named there is not read again; one that
    is not, is. Without it this reads all 149 controls, which is 12.7s on the
    machine this was written on.

    Ids the catalog does not know are ignored, not an error: a profile from a
    newer build of the app names controls this one has not got. Read-only
    controls are skipped for the same reason -- a baseline may record what a
    firmware setting was without implying anyone can write it -- and so is a
    target of None, which is what a baseline records for a control the machine
    could not answer for.
    """
    changes = ChangeSet()
    known = readings if readings is not None else {}
    for control_id, desired in target.items():
        control = catalog.get(control_id)
        if control is None or not control.writable or desired is None:
            continue
        if control_id in known:
            changes.add(control, desired, from_value=known[control_id])
        else:
            changes.add(control, desired)
    return changes
