r"""Superseded third-party driver packages, found without guessing.

`DriverStore\FileRepository` is **7.13 GB** on the machine this was written
for — the largest single reclaimable figure in the whole cleanup module, and
the one nothing could safely offer. The catalog's `driver_store` entry used
to point at that folder as one deletable item; it was tagged danger so it was
never auto-selected, but ticking it costs the machine its drivers. It is
disabled now, with its reason kept.

Reclaiming the space properly means removing SUPERSEDED packages one at a
time. Three things about `pnputil /enum-drivers` make that delicate, and all
three are handled here rather than discovered later:

* **Unelevated it prints its HELP TEXT and exits 0.** No error, nothing on
  stderr. A parser that trusts the return code reports "no superseded
  drivers" on every unelevated machine, forever — the same shape as `Get-Tpm`
  answering `{"TpmPresent":null}` or `gpresult /x` silently dropping the
  computer half. The refusal is detected by the ABSENCE of `Published Name:`
  records, and `parse_enum_drivers` returns **None** for it, never `[]`.
* **The output is UTF-16.** Decoded as UTF-8 it is mojibake.
* **"Newer" is sometimes genuinely ambiguous.** On this machine `amdxe.inf`
  has oem60 at 09/09/2025 25.20.0.11 and oem53 at 09/23/2025 25.10.0.1 — a
  later date carrying a lower version. Neither is offered: a wrong call
  costs a driver, so ambiguity resolves to "leave it alone". See
  `DriverPackage.supersedes` for the exact rule and why each half of it is
  shaped the way it is.

Sizing needs no elevation at all:
`HKLM\SYSTEM\DriverDatabase\DriverInfFiles\<published>\Active` names the
FileRepository folder for a published package, so oem49.inf and oem35.inf —
two versions of the same inf — resolve to their own folders and their own
byte counts.

Nothing here deletes. `pnputil /delete-driver` is the only correct removal
and it belongs behind an explicit, confirmed action, never behind the
checkbox tree that `delete_items` walks.
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000

_FIELD = re.compile(r"^([A-Za-z][A-Za-z ]*?):\s+(.*)$")
_VERSION_LINE = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+([0-9.]+)$")


@dataclass(frozen=True)
class DriverPackage:
    """One package in the driver store, as pnputil describes it."""

    published: str          # oem49.inf — how pnputil addresses it
    original: str           # amd3dvcache.inf — the vendor's own name
    provider: str
    class_guid: str
    version: Tuple[int, ...]
    date: datetime.date
    class_name: str = ""
    version_text: str = ""

    def supersedes(self, other: "DriverPackage") -> bool:
        """True only if this is strictly newer in VERSION and no older in DATE.

        Both halves come from the real data:

        * version must be strictly greater, so `amdxe.inf` — oem60 at
          09/09/2025 25.20.0.11 against oem53 at 09/23/2025 25.10.0.1, a
          later date carrying a LOWER version — resolves to "leave both
          alone" rather than to a guess. A wrong call costs a driver.
        * the date only has to be no OLDER, not strictly newer, because
          `amdocl.inf` ships oem56 (32.0.21042.62) and oem62
          (32.0.23034.4) on the same day, 04/17/2026. Requiring a strictly
          later date left oem56 unclaimed for no reason.
        """
        return self.version > other.version and self.date >= other.date


@dataclass
class SupersededReport:
    """What could be reclaimed, or why we could not tell."""

    available: bool
    packages: List[DriverPackage] = field(default_factory=list)
    total_bytes: int = 0
    #: Superseded packages whose bytes could NOT be determined, kept apart
    #: from the total rather than counted as zero. Five of eleven on the
    #: machine this was written for have no DriverInfFiles registry entry,
    #: so folding them in as 0 would have quietly understated the figure —
    #: a measurement that could not be taken reported as a measurement.
    unsized: List[DriverPackage] = field(default_factory=list)
    reason: str = ""


def _decode(raw) -> str:
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-16", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            logger.debug("pnputil output is not %s, trying the next encoding",
                         encoding)
            continue
        if "Published Name" in text or "PNPUTIL" in text.upper():
            return text
    return raw.decode("utf-8", errors="replace")


def parse_enum_drivers(raw) -> Optional[List[DriverPackage]]:
    """`pnputil /enum-drivers` output -> packages, or None if refused.

    None rather than an empty list, deliberately. A machine really can have
    no third-party drivers, and that is a different fact from "pnputil
    would not tell us" — which is what happens unelevated, where it prints
    its usage banner and exits 0.
    """
    text = _decode(raw)
    records: List[dict] = []
    current: dict = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                records.append(current)
                current = {}
            continue
        match = _FIELD.match(stripped)
        if match:
            current[match.group(1).strip()] = match.group(2).strip()
    if current:
        records.append(current)

    packages: List[DriverPackage] = []
    for record in records:
        published = record.get("Published Name")
        if not published:
            continue
        version_text = record.get("Driver Version", "")
        parsed = _VERSION_LINE.match(version_text)
        if not parsed:
            logger.debug("Unparseable driver version %r for %s",
                         version_text, published)
            continue
        month, day, year, version = parsed.groups()
        try:
            date = datetime.date(int(year), int(month), int(day))
        except ValueError:
            logger.debug("Impossible driver date %r for %s",
                         version_text, published)
            continue
        packages.append(DriverPackage(
            published=published,
            original=record.get("Original Name", ""),
            provider=record.get("Provider Name", ""),
            class_guid=record.get("Class GUID", ""),
            class_name=record.get("Class Name", ""),
            version=tuple(int(part) for part in version.split(".") if part.isdigit()),
            date=date,
            version_text=version_text,
        ))

    if not packages:
        logger.info("pnputil listed no driver packages — treating as refused; "
                    "unelevated it prints its usage banner and exits 0")
        return None
    return packages


def enumerate_packages() -> Optional[List[DriverPackage]]:
    """Ask pnputil what is in the driver store."""
    try:
        proc = subprocess.run(
            ["pnputil.exe", "/enum-drivers"],
            capture_output=True, timeout=120,
            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        logger.warning("pnputil /enum-drivers did not run", exc_info=True)
        return None
    # Deliberately not checking proc.returncode: it is 0 both when this
    # works and when it refuses.
    return parse_enum_drivers(proc.stdout)


def superseded_packages(packages: Optional[Sequence[DriverPackage]]
                        ) -> List[DriverPackage]:
    """Every package another package supersedes on BOTH version and date.

    None in — the enumeration was refused — means nothing out. Offering
    the whole driver store because a read failed is the failure this is
    written to make impossible.
    """
    if not packages:
        return []

    groups: dict = {}
    for package in packages:
        key = (package.original.lower(), package.class_guid)
        groups.setdefault(key, []).append(package)

    out: List[DriverPackage] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        for candidate in members:
            if any(other.supersedes(candidate)
                   for other in members if other is not candidate):
                out.append(candidate)
    out.sort(key=lambda p: (p.original.lower(), p.version))
    return out


def store_folder_for(published: str) -> Optional[str]:
    r"""The FileRepository folder holding this published package.

    `HKLM\SYSTEM\DriverDatabase\DriverInfFiles\<published>\Active`, which is
    readable WITHOUT elevation — so only the enumeration itself needs it.
    Two versions of one inf resolve to two different folders, which is what
    makes a per-package byte count possible at all.
    """
    import winreg

    key = (r"SYSTEM\DriverDatabase\DriverInfFiles" "\\" + published)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as handle:
            value, _ = winreg.QueryValueEx(handle, "Active")
    except OSError:
        logger.debug("No driver database entry for %s", published,
                     exc_info=True)
        return None
    return value or None


def file_repository() -> str:
    windir = os.environ.get("windir", r"C:\Windows")
    return os.path.join(windir, "System32", "DriverStore", "FileRepository")


def package_size(package: DriverPackage) -> Optional[int]:
    """Bytes this package occupies, or **None** if that cannot be told.

    None, never 0. Five of the eleven superseded packages on the machine
    this was written for have no `DriverInfFiles` entry at all, so their
    folder is unknown; counting them as zero turned "we could not measure
    this" into "this is empty" and understated the total without saying so.
    """
    from modules.cleanup.cleanup_scanner._common import get_dir_size

    folder = store_folder_for(package.published)
    if not folder:
        return None
    path = os.path.join(file_repository(), folder)
    if not os.path.isdir(path):
        logger.debug("Driver store folder %s is not on disk", folder)
        return None
    return get_dir_size(path)


def superseded_report() -> SupersededReport:
    """What could be reclaimed by pruning superseded driver packages."""
    packages = enumerate_packages()
    if packages is None:
        return SupersededReport(
            available=False,
            reason="pnputil could not enumerate the driver store — it needs "
                   "elevation, and unelevated it prints its usage banner and "
                   "exits 0 rather than reporting an error.")

    stale = superseded_packages(packages)
    total = 0
    unsized: List[DriverPackage] = []
    for package in stale:
        size = package_size(package)
        if size is None:
            unsized.append(package)
        else:
            total += size

    reason = (f"{len(packages)} driver packages installed, "
              f"{len(stale)} superseded.")
    if unsized:
        reason += (f" {len(unsized)} of them could not be located in the "
                   f"driver store, so their size is not in this total.")
    return SupersededReport(available=True, packages=stale, total_bytes=total,
                            unsized=unsized, reason=reason)


def removal_command(package: DriverPackage) -> List[str]:
    """The command that would remove `package`. Nothing here runs it.

    Removal is `pnputil /delete-driver <published>`, it needs elevation,
    and it belongs behind an explicit confirmed action — never behind the
    checkbox tree that `delete_items` walks, which would delete the
    FileRepository directory out from under Windows instead.
    """
    return ["pnputil.exe", "/delete-driver", package.published]
