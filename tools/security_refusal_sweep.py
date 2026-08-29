r"""Which controls turn a REFUSAL into a verdict?

    .venv\Scripts\python.exe tools\security_refusal_sweep.py

`SecurityControl.read()` documents the rule: None means "we could not look",
and is never collapsed into False. A reader signals that with
`available: False`. A reader that instead returns only a status string -- as
check_bitlocker's WMI failure path did -- falls through to `read_value`, which
asks questions like `"Protected" in status`. "Requires administrator" does not
contain "Protected", so the answer became **False**: not "we could not look"
but "your system drive is NOT encrypted".

That is invisible on this machine, whose C: really is unencrypted, and wrong
on any machine that is. It also reaches further than the card: `read()` is
what staging, baselines and profiles compare.

This asks every control for its reading, unelevated, and reports any whose
status says it was refused while its value is not None. Run it unelevated --
elevated there is nothing to refuse and it will find nothing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.security_dashboard.catalog import load_catalog  # noqa: E402

#: Phrases a reader uses when Windows would not answer it.
REFUSED_MARKERS = (
    "requires administrator",
    "access denied",
    "access is denied",
    "requires elevation",
    "could not determine",
    "no answer from",
)


def looks_refused(result: dict) -> str:
    """The phrase that says this reading was refused, or ""."""
    haystack = [str(result.get("status", ""))]
    for entry in result.get("details") or []:
        haystack.extend(str(part) for part in entry)
    text = " | ".join(haystack).lower()
    for marker in REFUSED_MARKERS:
        if marker in text:
            return marker
    return ""


def main() -> int:
    controls = load_catalog().values()   # load_catalog is id -> control
    offenders = []
    checked = 0

    for control in controls:
        try:
            result = control.reader() or {}
        except Exception as exc:
            print(f"   {control.id}: reader raised ({exc})")
            continue
        checked += 1
        marker = looks_refused(result)
        if not marker:
            continue
        value = control.read()
        if value is None:
            continue        # correctly reported as "we could not look"
        offenders.append((control.id, marker, value,
                          str(result.get("status", ""))[:60],
                          result.get("available")))

    print(f"\n{checked} control(s) read, unelevated.\n")
    if not offenders:
        print("No control turned a refusal into a value.")
        return 0

    print(f"{len(offenders)} control(s) answer with a VALUE after being "
          f"refused:\n")
    for cid, marker, value, status, available in offenders:
        print(f"   {cid}")
        print(f"      status      : {status!r}  (matched {marker!r})")
        print(f"      available   : {available!r}")
        print(f"      read()      : {value!r}   <- should be None")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
