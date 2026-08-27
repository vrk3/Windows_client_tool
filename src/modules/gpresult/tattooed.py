"""Find *tattooed* policy: values sitting in the managed policy branches that
no `Registry.pol` accounts for.

Windows' Registry client-side extension owns exactly four branches::

    HKLM\\Software\\Policies
    HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies
    HKCU\\Software\\Policies
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies

Everything the CSE writes there comes out of a `Registry.pol`, and everything
it wrote is removed again when the policy goes back to Not Configured. That is
the whole point of the branches: they are owned, volatile and disposable.

Anything **else** that writes into them -- a tweak script, a "debloat" tool,
malware, this application's own Tweaks module -- produces a value that:

* no `Registry.pol` will ever remove, so it survives `gpupdate /force` and
  every policy reset, indefinitely;
* `gpedit.msc` will not show, because gpedit reads the *policy files*, not
  the registry;
* `gpresult` will not attribute to any GPO, because no GPO owns it.

That is a tattooed policy, and it is the hardest class of Windows setting to
track down after the fact -- the tool that set it is usually long gone. This
module finds them by enumerating the live registry and subtracting what the
local `Registry.pol` files account for.

Three things this module refuses to do, because each one turns a useful answer
into a misleading one:

* **It does not swallow access-denied.** A subkey we could not open is counted
  and named, never skipped silently. "We could not look here" is a different
  outcome from "there is nothing here", and only one of them is safe to act
  on -- the same distinction the RSOP side of this package draws between a
  refused scope and an empty one.
* **It does not recurse without a bound.** Depth and value count are capped,
  and hitting a cap is reported in the result rather than quietly truncating.
* **It does not compare case-sensitively.** The registry is case-insensitive;
  `Software\\policies\\...` in a .pol file and `Software\\Policies\\...` in the
  registry are the same key, and treating them as different would make every
  genuinely-managed value look tattooed.

No Qt here on purpose -- this is pure logic, and all of it runs headless
against an injected fake registry reader.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from modules.gpresult.pol_parser import PolFile, local_policy_files

logger = logging.getLogger(__name__)

#: The four branches the Group Policy Registry extension owns, as
#: `(hive, hive-relative key)`. `Registry.pol` stores keys hive-relative too,
#: with the hive implied by the file's scope -- Machine is HKLM, User is HKCU.
#: Getting that mapping wrong makes every managed value look tattooed.
MANAGED_BRANCHES: Tuple[Tuple[str, str], ...] = (
    ("HKLM", r"Software\Policies"),
    ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Policies"),
    ("HKCU", r"Software\Policies"),
    ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies"),
)

#: Deep enough for anything Microsoft or a tweak tool actually writes (the
#: deepest real path on this machine is 9 levels), shallow enough that a
#: pathological key cannot spin a worker thread forever.
DEFAULT_MAX_DEPTH = 32

#: Per-branch value budget. The four branches together hold a few thousand
#: values on a heavily-tweaked machine, so this leaves an order of magnitude
#: of headroom while still bounding the worst case.
DEFAULT_MAX_VALUES = 50_000

_TYPE_NAMES = {
    0: "REG_NONE",
    1: "REG_SZ",
    2: "REG_EXPAND_SZ",
    3: "REG_BINARY",
    4: "REG_DWORD",
    5: "REG_DWORD_BIG_ENDIAN",
    6: "REG_LINK",
    7: "REG_MULTI_SZ",
    11: "REG_QWORD",
}


# ---------------------------------------------------------------------------
# What one registry key contains
# ---------------------------------------------------------------------------

@dataclass
class KeyContents:
    """One key's subkeys and values, or the reason we have neither.

    `denied` and `missing` are separate flags rather than one empty result:
    a key that refused us is a hole in the answer, a key that is not there is
    a fact about the machine.
    """

    subkeys: List[str] = field(default_factory=list)
    #: `(value_name, type_id, data)` -- the same triple `winreg.EnumValue`
    #: returns, reordered so the type sits next to the data it describes.
    values: List[Tuple[str, int, Any]] = field(default_factory=list)
    denied: bool = False
    missing: bool = False
    error: str = ""

    @property
    def readable(self) -> bool:
        return not self.denied and not self.missing and not self.error


#: A registry reader: given a hive name and a hive-relative key, return its
#: contents. Injectable so the walk is testable without this machine's
#: registry -- and so a caller could one day point it at a loaded offline hive.
RegistryReader = Callable[[str, str], KeyContents]


def read_registry_key(hive: str, key: str) -> KeyContents:
    """The real reader: one key out of the live 64-bit registry.

    `KEY_WOW64_64KEY` is not optional. Without it a 32-bit host process is
    silently redirected into `Software\\WOW6432Node\\Policies` -- a different,
    nearly empty branch. The scan would come back clean and be completely
    wrong. Asking for the 64-bit view explicitly costs nothing on a 64-bit
    host and removes the whole failure mode.
    """
    import winreg

    roots = {
        "HKLM": winreg.HKEY_LOCAL_MACHINE,
        "HKCU": winreg.HKEY_CURRENT_USER,
        "HKU": winreg.HKEY_USERS,
        "HKCR": winreg.HKEY_CLASSES_ROOT,
        "HKCC": winreg.HKEY_CURRENT_CONFIG,
    }
    root = roots.get(hive.upper())
    if root is None:
        logger.warning("Unknown hive %r requested", hive)
        return KeyContents(error="unknown hive %r" % hive)

    access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
    try:
        handle = winreg.OpenKeyEx(root, key, 0, access)
    except FileNotFoundError:
        # Perfectly normal: not every machine has every branch.
        logger.debug("Policy branch absent: %s\\%s", hive, key)
        return KeyContents(missing=True)
    except PermissionError as exc:
        logger.warning("Access denied reading %s\\%s: %s", hive, key, exc)
        return KeyContents(denied=True, error=str(exc))
    except OSError as exc:
        logger.warning("Could not open %s\\%s: %s", hive, key, exc)
        return KeyContents(error=str(exc))

    result = KeyContents()
    try:
        with handle:
            n_subkeys, n_values, _ = winreg.QueryInfoKey(handle)
            for index in range(n_subkeys):
                try:
                    result.subkeys.append(winreg.EnumKey(handle, index))
                except OSError as exc:
                    # A subkey deleted mid-enumeration, or one we may not even
                    # name. Keep what we did get and mark the key partial.
                    logger.debug("EnumKey(%s\\%s, %d) failed: %s",
                                 hive, key, index, exc)
                    result.error = result.error or str(exc)
                    break
            for index in range(n_values):
                try:
                    name, data, type_id = winreg.EnumValue(handle, index)
                except OSError as exc:
                    logger.debug("EnumValue(%s\\%s, %d) failed: %s",
                                 hive, key, index, exc)
                    result.error = result.error or str(exc)
                    break
                result.values.append((name, type_id, data))
    except OSError as exc:
        logger.warning("Could not read %s\\%s: %s", hive, key, exc)
        result.error = str(exc)
    return result


# ---------------------------------------------------------------------------
# What we found
# ---------------------------------------------------------------------------

@dataclass
class RegistryValue:
    """A single value living in one of the managed policy branches."""

    hive: str = ""            # "HKLM" / "HKCU"
    key: str = ""             # hive-relative, e.g. Software\\Policies\\...
    value_name: str = ""
    type_id: int = 0
    data: Any = None
    branch: str = ""          # which of the four branches it was found under

    @property
    def type_name(self) -> str:
        return _TYPE_NAMES.get(self.type_id, "REG_TYPE_%d" % self.type_id)

    @property
    def key_path(self) -> str:
        """`HIVE\\key`, the way regedit's address bar wants it."""
        return "%s\\%s" % (self.hive, self.key) if self.key else self.hive

    @property
    def full_path(self) -> str:
        """`HIVE\\key\\value` -- how the setting is identified everywhere else."""
        head = self.key_path
        return "%s\\%s" % (head, self.value_name) if self.value_name else head

    def display(self) -> str:
        """The data as a person would read it."""
        if self.data is None:
            return ""
        if isinstance(self.data, bytes):
            return self.data.hex()
        if isinstance(self.data, (list, tuple)):
            return ", ".join(str(part) for part in self.data)
        return str(self.data)


@dataclass
class BranchScan:
    """The outcome of walking one managed branch.

    "Branch absent" and "branch empty" and "branch refused" look identical
    from a distance and are three different answers, which is why the caps and
    the unreadable list are fields rather than log lines.
    """

    hive: str = ""
    key: str = ""
    exists: bool = False
    values: List[RegistryValue] = field(default_factory=list)
    #: Full paths of keys that refused to open, or that we could only read
    #: part of. Named rather than merely counted, so a pane can show the user
    #: exactly where the blind spots are.
    unreadable_keys: List[str] = field(default_factory=list)
    #: Keys we stopped at because `max_depth` ran out -- their contents are
    #: unexamined, and saying so is the difference between a bounded walk and
    #: a silent truncation.
    depth_capped_keys: List[str] = field(default_factory=list)
    #: True when `max_values` ran out; whatever remained is unexamined.
    value_cap_hit: bool = False
    keys_visited: int = 0
    error: str = ""

    @property
    def branch_path(self) -> str:
        return "%s\\%s" % (self.hive, self.key)

    @property
    def complete(self) -> bool:
        """True only when nothing was refused, capped or errored."""
        return (not self.unreadable_keys and not self.depth_capped_keys
                and not self.value_cap_hit and not self.error)


@dataclass
class TattooedResult:
    """Everything the scan learned, ready for a table."""

    branches: List[BranchScan] = field(default_factory=list)
    #: Values in the managed branches that no `Registry.pol` accounts for.
    tattooed: List[RegistryValue] = field(default_factory=list)
    #: Values a `Registry.pol` does account for -- Group Policy's own.
    accounted: List[RegistryValue] = field(default_factory=list)
    #: Accounted-for values whose live data no longer matches the .pol data.
    #: Group Policy owns the name, but something overwrote what it set; the
    #: next `gpupdate` will put it back and the change will look self-healing.
    drifted: List[RegistryValue] = field(default_factory=list)
    pol_files: List[PolFile] = field(default_factory=list)
    #: Records read out of the .pol files, CSE directives included.
    pol_records: int = 0
    elapsed_seconds: float = 0.0
    #: Non-fatal problems worth putting in front of the user: a .pol that
    #: would not parse, a branch that errored outright.
    warnings: List[str] = field(default_factory=list)

    @property
    def total_values(self) -> int:
        return len(self.tattooed) + len(self.accounted)

    @property
    def unreadable_key_count(self) -> int:
        return sum(len(b.unreadable_keys) for b in self.branches)

    @property
    def capped(self) -> bool:
        """True when a depth or value cap cut the walk short somewhere."""
        return any(b.value_cap_hit or b.depth_capped_keys
                   for b in self.branches)

    @property
    def complete(self) -> bool:
        """True only when every branch was walked to the end, unrefused.

        A caller must not present an incomplete scan as "nothing tattooed
        here" -- that is exactly the refused-read-masquerading-as-a-definite-
        answer failure this codebase forbids everywhere else.
        """
        return bool(self.branches) and all(b.complete for b in self.branches)

    def summary(self) -> str:
        """One sentence a status bar can show without further formatting."""
        parts = ["%d tattooed of %d values across %d branches"
                 % (len(self.tattooed), self.total_values, len(self.branches))]
        if self.unreadable_key_count:
            parts.append("%d keys unreadable" % self.unreadable_key_count)
        if self.capped:
            parts.append("a scan limit was hit, so this is incomplete")
        if self.drifted:
            parts.append("%d policy values overwritten" % len(self.drifted))
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------

def _join(parent: str, child: str) -> str:
    return "%s\\%s" % (parent, child) if parent else child


def scan_branch(hive: str,
                key: str,
                reader: Optional[RegistryReader] = None,
                max_depth: int = DEFAULT_MAX_DEPTH,
                max_values: int = DEFAULT_MAX_VALUES) -> BranchScan:
    """Walk one managed branch, bounded, never aborting on a refused subkey.

    The recursion is an explicit stack rather than a Python one, so the bound
    is a number we chose rather than a number CPython chose for us: a branch
    deeper than `max_depth` yields a *reported* cap instead of a
    RecursionError surfacing from inside a worker thread.
    """
    read = reader or read_registry_key
    scan = BranchScan(hive=hive, key=key)

    root = read(hive, key)
    if root.missing:
        # Not an error: plenty of machines have no HKCU policy branch at all.
        return scan
    if root.denied:
        scan.exists = True
        scan.unreadable_keys.append("%s\\%s" % (hive, key))
        return scan
    scan.exists = True
    if root.error and not root.values and not root.subkeys:
        scan.error = root.error
        return scan

    branch_path = "%s\\%s" % (hive, key)
    # (hive-relative key, depth, already-read contents). Depth 0 is the root.
    stack: List[Tuple[str, int, KeyContents]] = [(key, 0, root)]

    while stack:
        current_key, depth, contents = stack.pop()
        scan.keys_visited += 1

        if contents.error:
            # A partial read: we got some of the key. Record it rather than
            # letting a half-enumerated key pass as fully examined.
            scan.unreadable_keys.append("%s\\%s" % (hive, current_key))

        for value_name, type_id, data in contents.values:
            if len(scan.values) >= max_values:
                scan.value_cap_hit = True
                logger.warning(
                    "Value cap of %d reached while scanning %s; the result "
                    "is incomplete", max_values, branch_path)
                break
            scan.values.append(RegistryValue(
                hive=hive, key=current_key, value_name=value_name,
                type_id=type_id, data=data, branch=branch_path))
        if scan.value_cap_hit:
            break

        if depth >= max_depth:
            if contents.subkeys:
                scan.depth_capped_keys.append("%s\\%s" % (hive, current_key))
                logger.warning(
                    "Depth cap of %d reached at %s\\%s; %d subkeys unexamined",
                    max_depth, hive, current_key, len(contents.subkeys))
            continue

        for sub in contents.subkeys:
            sub_key = _join(current_key, sub)
            child = read(hive, sub_key)
            if child.denied:
                # The whole point: one refused subkey is a hole in the answer,
                # not the end of the walk.
                scan.unreadable_keys.append("%s\\%s" % (hive, sub_key))
                continue
            if child.missing:
                # Enumerated a moment ago, gone now -- the registry is read
                # live, with no snapshot, so this genuinely happens.
                logger.debug("Subkey %s\\%s vanished mid-walk", hive, sub_key)
                continue
            stack.append((sub_key, depth + 1, child))

    return scan


# ---------------------------------------------------------------------------
# What Registry.pol accounts for
# ---------------------------------------------------------------------------

def _norm_key(key: str) -> str:
    """A key in comparable form: lowercased, no stray separators.

    Case-insensitive because the registry is. .pol writers are not consistent
    about case -- Microsoft's own ADMX-generated files disagree with each
    other -- so comparing raw strings makes managed values look tattooed.
    """
    return key.strip("\\").replace("/", "\\").lower()


def pol_index(pol_files: Sequence[PolFile]) -> Dict[Tuple[str, str, str], Any]:
    """`(HIVE, key, value_name) -> policy data`, keys and names lowercased.

    A `**del.Foo` record counts as accounting for `Foo`: Group Policy is
    actively managing that name, even though the state it manages it into is
    "absent". Its data is stored as `None`, which suppresses the drift check
    -- there is no policy data to have drifted from.

    The other directives (`**delvals.`, `**deletekeys`, `**secureKey`) are
    deliberately *not* expanded into value names, because they say nothing
    about which names exist. Anything found under such a key genuinely is
    unaccounted for.
    """
    index: Dict[Tuple[str, str, str], Any] = {}
    for pol in pol_files:
        hive = (pol.hive or "").upper()
        for value in pol.values:
            name = value.value_name
            if value.directive == "delete_value":
                cut = name.lower().find("**del.")
                if cut >= 0:
                    name = name[cut + len("**del."):]
                if not name:
                    continue
                index.setdefault(
                    (hive, _norm_key(value.key), name.lower()), None)
                continue
            if value.directive:
                continue
            index[(hive, _norm_key(value.key), name.lower())] = value.data
    return index


def _same_data(live: Any, policy: Any) -> bool:
    """Whether the live value still holds what the .pol says it should.

    Both sides decode registry data into the same Python shapes (str, int,
    list, bytes), so a direct comparison is meaningful. The list/tuple arm
    exists only because REG_MULTI_SZ can arrive as either.
    """
    if isinstance(live, (list, tuple)) and isinstance(policy, (list, tuple)):
        return list(live) == list(policy)
    return live == policy


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------

def find_tattooed(pol_files: Optional[Sequence[PolFile]] = None,
                  reader: Optional[RegistryReader] = None,
                  branches: Iterable[Tuple[str, str]] = MANAGED_BRANCHES,
                  max_depth: int = DEFAULT_MAX_DEPTH,
                  max_values: int = DEFAULT_MAX_VALUES,
                  system_root: Optional[str] = None) -> TattooedResult:
    """Every value in the managed branches that no `Registry.pol` explains.

    `pol_files` defaults to this machine's own local GPO (both scopes, read
    with no elevation and no UAC prompt); `reader` defaults to the live
    64-bit registry. Both are parameters so the entire comparison can be
    exercised headless, against data that does not change under the test.
    """
    started = time.perf_counter()
    read = reader or read_registry_key
    files = (list(pol_files) if pol_files is not None
             else local_policy_files(system_root))

    result = TattooedResult(pol_files=files)
    for pol in files:
        result.pol_records += len(pol.values)
        if pol.error:
            # A .pol we could not parse under-counts the accounted-for side,
            # which inflates the tattooed list. Never hide that.
            result.warnings.append(pol.error)

    index = pol_index(files)

    for hive, key in branches:
        scan = scan_branch(hive, key, reader=read,
                           max_depth=max_depth, max_values=max_values)
        result.branches.append(scan)
        if scan.error:
            result.warnings.append(
                "Could not scan %s: %s" % (scan.branch_path, scan.error))

        for value in scan.values:
            lookup = (value.hive.upper(), _norm_key(value.key),
                      value.value_name.lower())
            if lookup not in index:
                result.tattooed.append(value)
                continue
            result.accounted.append(value)
            policy_data = index[lookup]
            if policy_data is not None and not _same_data(value.data,
                                                          policy_data):
                result.drifted.append(value)

    result.elapsed_seconds = time.perf_counter() - started
    logger.info("Tattooed scan: %s (%.2fs)",
                result.summary(), result.elapsed_seconds)
    return result
