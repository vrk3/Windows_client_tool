"""Answer "is this policy actually in effect?" for local Group Policy.

`pol_parser` says what `Registry.pol` *asks* for. That is not the same thing
as what the machine *does*: the Registry client-side extension writes those
values into the live registry at the next policy refresh, and until it does
-- or if something else overwrites them afterwards -- the file and the
registry disagree. This module reads both and reports the difference.

Four answers, and the fourth is the point of the module:

* ``applied``    -- the live value holds exactly what the policy asks for
* ``different``  -- the value is there, holding something else
* ``missing``    -- the key or value is not in the live registry at all
* ``unreadable`` -- the read was *refused*, so we do not know

`missing` and `unreadable` must never be collapsed. "The value is not set" is
a definite statement about the machine; "we were denied access to look" is a
statement about us. The same distinction `rsop_parser` draws between an empty
scope and a refused one, and the same one `tweak_engine` draws between
`ERROR_FILE_NOT_FOUND` (2, a real answer) and `ERROR_ACCESS_DENIED` (5, no
answer at all). Reporting a refused read as `missing` invents drift that is
not there, and someone then goes hunting for it.

Two record shapes look like drift and are not:

* **A key-only record.** This machine's own `Registry.pol` carries
  ``Software\\Policies\\Microsoft\\Windows\\Safer`` as REG_NONE with an
  *empty value name* and zero bytes of data -- it exists to create the key,
  not to set a value. There is nothing to `QueryValueEx`, so asking for one
  raises; key existence is the whole question. A reader that assumes every
  record names a value crashes on the first real machine it meets.
* **A directive record** (``**del.``, ``**delvals.`` and friends). The policy
  is asking for the value to be *gone*, so absence is success. Flagging those
  as `missing` would mark every working delete directive as drift.

No Qt here, and the registry reader is injectable, so this is testable with
no display, no elevation, and no dependence on this machine's registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .pol_parser import PolFile, PolicyValue, local_policy_files

logger = logging.getLogger(__name__)

try:  # A guarded import so the module still loads (and tests still run) off Windows.
    import winreg
except ImportError:  # pragma: no cover - this repo targets Windows only.
    winreg = None  # type: ignore[assignment]

#: Only this one means "we could not look". Everything else -- notably
#: ERROR_FILE_NOT_FOUND (2) -- is a real answer about the machine.
_ERROR_ACCESS_DENIED = 5

APPLIED = "applied"
DIFFERENT = "different"
MISSING = "missing"
UNREADABLE = "unreadable"

#: Presentation order for a summary row: worst news first.
STATES = (DIFFERENT, MISSING, UNREADABLE, APPLIED)

_HIVE_NAMES = {"HKLM": "HKEY_LOCAL_MACHINE", "HKCU": "HKEY_CURRENT_USER"}

#: winreg type ids happen to match the PReg ones, so a live REG_DWORD and a
#: policy REG_DWORD compare directly -- no translation table is needed.
_NO_TYPE = -1


@dataclass
class RegistryRead:
    """One live-registry lookup, including the case where it was refused.

    `found` is only meaningful when `readable` is True. A refused read leaves
    `found` False *and* `readable` False, and the two must be checked in that
    order -- see the module docstring.
    """

    found: bool = False
    data: Any = None
    type_id: int = _NO_TYPE
    readable: bool = True
    error: str = ""
    key_exists: bool = False


@dataclass
class DriftResult:
    """What one `Registry.pol` record is actually doing on this machine."""

    policy: Optional[PolicyValue] = None
    scope: str = ""            # "Computer" or "User"
    hive: str = ""             # "HKLM" or "HKCU"
    state: str = MISSING       # one of STATES
    reason: str = ""           # the sentence a tooltip shows
    live_data: Any = None
    live_type_id: int = _NO_TYPE
    expects_absent: bool = False   # a **del. directive: gone IS applied
    key_only: bool = False         # empty value name: only the key can be checked

    @property
    def key(self) -> str:
        return self.policy.key if self.policy else ""

    @property
    def value_name(self) -> str:
        return self.policy.value_name if self.policy else ""

    @property
    def full_path(self) -> str:
        """`HKLM\\key\\value`, the way the setting is named everywhere else."""
        if not self.policy:
            return ""
        return "%s\\%s" % (self.hive, self.policy.full_path)

    @property
    def expected_display(self) -> str:
        return self.policy.display() if self.policy else ""

    @property
    def live_display(self) -> str:
        """The live value as a person would read it, or "" when there is none."""
        if self.live_data is None:
            return ""
        if isinstance(self.live_data, bytes):
            return self.live_data.hex()
        if isinstance(self.live_data, list):
            return ", ".join(str(part) for part in self.live_data)
        return str(self.live_data)

    @property
    def is_drift(self) -> bool:
        """True only when we KNOW the machine disagrees with the policy.

        `unreadable` is deliberately excluded: an unanswered question is not
        evidence of drift, and counting it as such is how a permissions
        problem gets reported as a policy problem.
        """
        return self.state in (DIFFERENT, MISSING)

    @property
    def is_certain(self) -> bool:
        return self.state != UNREADABLE


@dataclass
class DriftReport:
    """Every record of every scope, plus the files they came from."""

    results: List[DriftResult] = field(default_factory=list)
    files: List[PolFile] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        """One count per state, every state present even at zero."""
        tally = {state: 0 for state in STATES}
        for result in self.results:
            tally[result.state] = tally.get(result.state, 0) + 1
        return tally

    def by_state(self, state: str) -> List[DriftResult]:
        return [r for r in self.results if r.state == state]

    @property
    def drifted(self) -> List[DriftResult]:
        return [r for r in self.results if r.is_drift]

    @property
    def errors(self) -> List[str]:
        """Whatever stopped a file being read at all, so the pane can say so."""
        return [f.error for f in self.files if f.error]

    def summary(self) -> str:
        tally = self.counts
        return ", ".join("%d %s" % (tally[state], state) for state in STATES)


def read_live_value(hive: str, key: str, value_name: str) -> RegistryRead:
    """Read one value out of the live registry. Never raises.

    `KEY_WOW64_64KEY` is not optional here. Without it a 32-bit Python would
    be silently redirected into `Wow6432Node` and would compare policy against
    the wrong branch -- reporting the policy as missing while it is sitting
    right there in the 64-bit view.
    """
    if winreg is None:  # pragma: no cover - Windows-only tool.
        return RegistryRead(
            readable=False, error="winreg is not available on this platform")

    root = getattr(winreg, _HIVE_NAMES.get(hive, ""), None)
    if root is None:
        # A hive we do not know is a bug in the caller, not a fact about the
        # machine, so it must not be reported as "the value is missing".
        logger.warning("Unknown registry hive %r for %s", hive, key)
        return RegistryRead(readable=False, error="unknown registry hive %r" % hive)

    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    try:
        handle = winreg.OpenKey(root, key, 0, access)
    except OSError as exc:
        if getattr(exc, "winerror", None) == _ERROR_ACCESS_DENIED:
            logger.debug("Access denied opening %s\\%s", hive, key)
            return RegistryRead(
                readable=False,
                error="access denied opening the key (try running elevated)")
        logger.debug("Key %s\\%s is not present: %s", hive, key, exc)
        return RegistryRead(found=False, key_exists=False)

    with handle:
        if not value_name:
            # A key-only record. There is no value to query, so the key's own
            # existence is the entire answer -- and we already have it.
            return RegistryRead(found=True, key_exists=True)
        try:
            data, type_id = winreg.QueryValueEx(handle, value_name)
        except OSError as exc:
            if getattr(exc, "winerror", None) == _ERROR_ACCESS_DENIED:
                logger.debug("Access denied reading %s\\%s\\%s", hive, key, value_name)
                return RegistryRead(
                    readable=False, key_exists=True,
                    error="access denied reading the value")
            logger.debug(
                "Value %s\\%s\\%s is not set: %s", hive, key, value_name, exc)
            return RegistryRead(found=False, key_exists=True)

    return RegistryRead(found=True, data=data, type_id=type_id, key_exists=True)


#: The signature every injected reader must have.
RegistryReader = Callable[[str, str, str], RegistryRead]


def _normalise(value: Any) -> Any:
    """Make a policy value and a live value comparable.

    `pol_parser` already strips the terminating null off REG_SZ, but the
    registry hands back whatever was written -- and a string written with its
    null included compares unequal to the identical string without it.
    """
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, list):
        return [_normalise(part) for part in value]
    return value


def _values_match(policy: PolicyValue, read: RegistryRead) -> bool:
    return _normalise(policy.data) == _normalise(read.data)


def compare_policy_value(
    policy: PolicyValue,
    hive: str,
    scope: str = "",
    reader: RegistryReader = read_live_value,
) -> DriftResult:
    """Classify one `Registry.pol` record against the live registry."""
    result = DriftResult(
        policy=policy,
        scope=scope,
        hive=hive,
        expects_absent=bool(policy.directive),
        key_only=not policy.value_name,
    )
    target = "%s\\%s" % (hive, policy.full_path)

    read = reader(hive, policy.key, policy.value_name)

    if not read.readable:
        result.state = UNREADABLE
        result.reason = "could not read %s: %s" % (
            target, read.error or "the read was refused")
        return result

    result.live_data = read.data
    result.live_type_id = read.type_id

    if result.expects_absent:
        # The policy is a delete directive, so the states invert: gone is the
        # success case and still-present is the drift.
        if read.found:
            result.state = DIFFERENT
            result.reason = (
                "the policy deletes %s, but it still exists%s"
                % (target,
                   " (= %s)" % result.live_display if result.live_display else ""))
        else:
            result.state = APPLIED
            result.reason = "the policy deletes %s, and it is absent" % target
        return result

    if result.key_only:
        # No value name: the record exists to create the key. Comparing data
        # here is meaningless, and QueryValueEx would raise.
        if read.found:
            result.state = APPLIED
            result.reason = "the key %s exists, as the policy requires" % target
        else:
            result.state = MISSING
            result.reason = "the key %s does not exist" % target
        return result

    if not read.found:
        result.state = MISSING
        if read.key_exists:
            result.reason = "%s is not set; the policy sets it to %s" % (
                target, policy.display() or "(no data)")
        else:
            result.reason = (
                "the key %s\\%s does not exist, so the policy is not in effect"
                % (hive, policy.key))
        return result

    if not _values_match(policy, read):
        result.state = DIFFERENT
        result.reason = "%s is %s, the policy sets %s" % (
            target, result.live_display or "(empty)", policy.display() or "(no data)")
        return result

    if read.type_id != policy.type_id:
        # Same bytes, wrong type. Windows reads a policy value by type, so an
        # expected DWORD stored as a string is not in effect however right it
        # looks in regedit.
        result.state = DIFFERENT
        result.reason = "%s holds %s but as type %d, the policy declares %s" % (
            target, result.live_display or "(empty)",
            read.type_id, policy.type_name)
        return result

    result.state = APPLIED
    result.reason = "%s = %s, matching the policy" % (
        target, result.live_display or "(empty)")
    return result


def drift_for_pol_file(
    pol: PolFile,
    reader: RegistryReader = read_live_value,
) -> List[DriftResult]:
    """Classify every record in one `Registry.pol`, directives included.

    `pol.values` rather than `pol.settings`: a delete directive is a policy
    that can drift like any other, and dropping it would hide the case where
    a value the policy removes has come back.
    """
    return [
        compare_policy_value(value, pol.hive, pol.scope, reader)
        for value in pol.values
    ]


def drift_report(
    pol_files: Optional[List[PolFile]] = None,
    reader: RegistryReader = read_live_value,
    system_root: Optional[str] = None,
) -> DriftReport:
    """The whole local GPO, both scopes, compared against the live registry.

    A `Registry.pol` that does not exist contributes no results and is not an
    error -- that is the normal state of a scope with nothing configured, and
    `pol_parser` already draws that line.
    """
    files = pol_files if pol_files is not None else local_policy_files(system_root)
    report = DriftReport(files=list(files))
    for pol in report.files:
        if pol.error:
            logger.warning("Skipping %s: %s", pol.path, pol.error)
            continue
        report.results.extend(drift_for_pol_file(pol, reader))
    return report
