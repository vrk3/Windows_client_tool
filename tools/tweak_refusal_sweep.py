r"""Which of the ~700 tweaks turn a REFUSAL into a verdict?

    .venv\Scripts\python.exe tools\tweak_refusal_sweep.py

The Security Dashboard's sibling of this (`security_refusal_sweep.py`) found
`check_bitlocker` answering False -- "your system drive is NOT encrypted" --
for a reading nobody was allowed to take. The tweak engine draws the same
distinction and states it in CLAUDE.md: a missing registry key is
`not_applied` (Windows at its default), and ONLY an access-denied read is
`unknown`. `service_exists()` / `scheduled_task_exists()` return
`Optional[bool]` for exactly this reason -- False means absent, None means the
query itself failed.

So the question this asks of every tweak, on this machine, is:

    does any step's REASON say it was refused, while the tweak's status is a
    verdict (applied / not_applied / partial) that does not DISCLOSE it?

A verdict built on a refused read is a lie the UI has no way to spot: the row
shows a confident tick or dash, and the Apply button acts on it. Disclosed
uncertainty is a different thing and is fine -- `_aggregate` may conclude
"not in place" while one step is unreadable, because a step that is
definitely missing settles the question on its own; it appends
"(N step(s) could not be checked)" when it does. Measured 2026-08-29: 696
tweaks, one such disclosure (`disable_auto_logger`, whose second Autologger
key needs administrator rights to read), and no swallowed refusal.

Run it unelevated -- that is where things get refused. Elevated it should find
nothing, which is itself worth knowing.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.tweaks.tweak_engine import (  # noqa: E402
    APPLIED, NOT_APPLIED, PARTIAL, TweakEngine,
)
from modules.tweaks.tweaks_module import _CATEGORY_FILES, _DEFS_DIR  # noqa: E402

#: Phrases that mean "Windows would not answer", not "the answer is no".
REFUSED_MARKERS = (
    "access denied",
    "access is denied",
    "requires administrator",
    "requires elevation",
    "permission",
    "could not query",
    "could not determine",
    "winerror 5",
)

VERDICTS = (APPLIED, NOT_APPLIED, PARTIAL)

#: What an honest verdict says when it could not read everything. The
#: aggregation is entitled to conclude "not in place" while one step is
#: unreadable -- a step that is definitely missing settles it -- provided it
#: SAYS so. A confident verdict with the refusal swallowed is the bug.
DISCLOSURE = "could not be checked"


def refusal_in(text: str) -> str:
    low = (text or "").lower()
    for marker in REFUSED_MARKERS:
        if marker in low:
            return marker
    return ""


def main() -> int:
    engine = TweakEngine(backup_service=None)

    tweaks = []
    for category, filename in _CATEGORY_FILES.items():
        path = os.path.join(_DEFS_DIR, filename)
        if not os.path.exists(path):
            print(f"   (missing definition file: {filename})")
            continue
        for tweak in TweakEngine.load_definitions(path):
            tweaks.append((category, tweak))

    print(f"{len(tweaks)} tweaks across {len(_CATEGORY_FILES)} categories\n")

    counts = Counter()
    offenders = []
    for category, tweak in tweaks:
        try:
            result = engine.detect(tweak)
        except Exception as exc:
            offenders.append((category, tweak.get("id"), "detect raised",
                              str(exc)[:90], "-"))
            continue
        counts[result.status] += 1
        if result.status not in VERDICTS:
            continue
        marker = refusal_in(result.reason)
        step_hit = ""
        for step in result.steps or []:
            step_hit = refusal_in(step.reason)
            if step_hit:
                break
        if not (marker or step_hit):
            continue
        # A verdict that SAYS a step could not be checked is not the bug --
        # the aggregation is allowed to conclude "not in place" when a known
        # step is missing, as long as it discloses what it could not read.
        # The bug is a confident verdict with the refusal swallowed.
        if DISCLOSURE in (result.reason or "").lower():
            continue
        offenders.append((category, tweak.get("id"), result.status,
                          (result.reason or "")[:90],
                          marker or step_hit))

    print("status distribution:")
    for status, n in counts.most_common():
        print(f"   {status:<16} {n}")

    print()
    if not offenders:
        print("No tweak reported a verdict on top of a refused read.")
        return 0

    print(f"{len(offenders)} tweak(s) gave a VERDICT after a refusal:\n")
    for category, tid, status, reason, marker in offenders:
        print(f"   [{category}] {tid}")
        print(f"      status : {status}   (matched {marker!r})")
        print(f"      reason : {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
