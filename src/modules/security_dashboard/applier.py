"""Execute a staged batch, and believe the reader rather than the writer.

Two rules, both of which exist because of something that has already gone
wrong in this project:

* **A writer that returned is not evidence the machine changed.** Four
  separate Windows admin commands are on record here exiting 0 while
  refusing, and Tamper Protection silently discards every `Set-MpPreference`
  on the machine this was written on. So every control is re-read afterwards,
  and a write the reader contradicts gets its own state --
  `APPLIED_UNVERIFIED` -- rather than being counted as a success.

* **Every write in the batch happens before any verifying read.** 135 of the
  149 readers answer out of `snapshots.py`, whose cache has no expiry. Reading
  a control back without dropping that cache returns the value from before the
  write; dropping it between each control instead of once would leave the
  snapshot warmed by control 1's verify stale for control 5's write. So the
  batch is applied, the caches are dropped once, and only then is anything
  read.
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

from . import snapshots
from .catalog.model import ControlState, Risk
from .staging import ChangeSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlResult:
    control_id: str
    state: ControlState
    requested: Any
    observed: Any
    reason: str = ""


@dataclass
class BatchResult:
    rp_id: str
    results: List[ControlResult] = field(default_factory=list)
    windows_restore_point: Optional[str] = None
    #: Set only by the elevated helper, which cannot report to its parent any
    #: way except through the result file: if the batch could not be run at
    #: all, this is why. Empty results with no error means nothing was staged.
    error: str = ""

    @property
    def verified(self) -> int:
        return sum(1 for r in self.results
                   if r.state is ControlState.APPLIED_VERIFIED)

    @property
    def problems(self) -> Tuple[ControlResult, ...]:
        return tuple(r for r in self.results
                     if r.state in (ControlState.APPLIED_UNVERIFIED,
                                    ControlState.REFUSED))


_UNVERIFIED_REASON = (
    "the write reported success but the setting still reads {observed!r}. "
    "Something is overriding it: a Group Policy, Tamper Protection, an MDM "
    "enrolment, or another security product.")


def apply_batch(changeset: ChangeSet, engine, backup, *,
                create_windows_restore_point: Optional[Callable] = None,
                invalidate_reads: Callable[[], None] = snapshots.invalidate
                ) -> BatchResult:
    """Apply every staged change, then re-read each control to check.

    A restore point is always taken in the app's own backup store; a Windows
    restore point costs 30+ seconds and is taken only when the batch carries a
    high-risk control.

    Runs the writes for the whole batch first and the verifying reads second,
    with `invalidate_reads` in between -- see the module docstring. Both the
    reads and `invalidate_reads` are blocking, so this belongs in a worker
    thread, never on the Qt main thread.
    """
    rp_id = backup.create_restore_point(
        f"Security Dashboard: {len(changeset)} change(s)", "Security Dashboard")

    windows_rp = None
    if (create_windows_restore_point is not None
            and changeset.highest_risk is Risk.HIGH):
        ok, message = create_windows_restore_point(
            "Before Security Dashboard changes")
        windows_rp = message if ok else None
        if not ok:
            logger.warning("Windows restore point refused: %s", message)

    result = BatchResult(rp_id=rp_id, windows_restore_point=windows_rp)

    # Pass one: write. `to_verify` holds the index in result.results that each
    # still-unsettled change will fill in, so the report stays in the order
    # the user staged them.
    to_verify: List[Tuple[int, Any]] = []
    for change in changeset.changes:
        errors: List[str] = []
        tweak = {"id": change.control_id, "steps": list(change.resolved_steps())}
        try:
            ok = engine.apply_tweak(tweak, rp_id, on_error=errors.append)
        except Exception as exc:            # a writer that raised is a refusal
            logger.warning("control %r: the writer raised",
                           change.control_id, exc_info=True)
            ok, _ = False, errors.append(str(exc))

        if not ok:
            result.results.append(ControlResult(
                change.control_id, ControlState.REFUSED,
                change.to_value, change.from_value,
                reason="; ".join(errors) or "the writer reported failure"))
            continue

        if change.control.requires_reboot:
            result.results.append(ControlResult(
                change.control_id, ControlState.APPLIED_PENDING_REBOOT,
                change.to_value, change.from_value,
                reason="takes effect after a restart"))
            continue

        to_verify.append((len(result.results), change))
        result.results.append(None)         # placeholder, filled in below

    if not to_verify:
        return result

    # Pass two: read the machine back, once the whole batch has landed. A
    # reader that raises is handled by SecurityControl.read(), which answers
    # None -- "could not look" -- and that is never equal to a target, so an
    # unreadable control is unverified rather than a crash mid-batch.
    invalidate_reads()
    for index, change in to_verify:
        observed = change.control.read()
        if observed == change.to_value:
            state, reason = ControlState.APPLIED_VERIFIED, ""
        else:
            state = ControlState.APPLIED_UNVERIFIED
            reason = _UNVERIFIED_REASON.format(observed=observed)
        result.results[index] = ControlResult(
            change.control_id, state, change.to_value, observed, reason)

    return result
