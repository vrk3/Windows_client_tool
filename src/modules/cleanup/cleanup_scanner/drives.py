r"""Which volumes the cleaner is allowed to sweep.

Of 537 scanners, exactly two ever looked past C: — `scan_recycle_bin` and
`scan_recycle_bin_drive`, which were byte-identical duplicates of each
other. Everything else hardcoded `C:\` or leaned on `%windir%` /
`%LOCALAPPDATA%`, both of which are on C: here. Measured on this machine:
`E:\temp` holds 20.36 GB that nothing in the cleaner could find.

**Fixed volumes only.** A removable drive is somebody's USB stick, and
offering to delete from whatever happens to be plugged in is not a
cleanup feature. A network drive would be walked over the wire. Neither is
worth the surprise, and `GetDriveTypeW` distinguishes them for free.
"""
from __future__ import annotations

import ctypes
import logging
import string
from typing import List

logger = logging.getLogger(__name__)

DRIVE_FIXED = 3

#: The token a catalog path uses to mean "once per fixed volume".
FIXED_DRIVES_TOKEN = "%FIXED_DRIVES%"

_cache: List[str] | None = None


def fixed_drive_roots(refresh: bool = False) -> List[str]:
    r"""Every fixed volume root, as `X:\`, in drive-letter order.

    Cached: this is asked once per scanner per sweep, and the answer does
    not change while the app runs (a drive appearing mid-session is not
    worth a syscall per path). `refresh` exists for tests.
    """
    global _cache
    if _cache is not None and not refresh:
        return list(_cache)

    kernel32 = ctypes.windll.kernel32
    try:
        mask = kernel32.GetLogicalDrives()
    except OSError:
        logger.warning("Could not enumerate drives", exc_info=True)
        return [r"C:\\"]

    found: List[str] = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << index):
            continue
        root = f"{letter}:\\"
        try:
            if kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_FIXED:
                found.append(root)
        except OSError:
            logger.debug("GetDriveTypeW failed for %s", root, exc_info=True)

    _cache = found
    return list(found)


def expand_fixed_drives(raw: str) -> List[str]:
    r"""`%FIXED_DRIVES%\temp` -> one path per fixed volume.

    A path without the token comes back unchanged, as a single-item list,
    so callers can treat every path the same way.
    """
    if FIXED_DRIVES_TOKEN not in raw.upper():
        return [raw]

    # Case-insensitively, and keeping whatever separator followed it: the
    # token stands in for `X:\`, which already ends in one.
    index = raw.upper().index(FIXED_DRIVES_TOKEN)
    prefix = raw[:index]
    suffix = raw[index + len(FIXED_DRIVES_TOKEN):].lstrip("\\/")
    return [f"{prefix}{root}{suffix}" for root in fixed_drive_roots()]


def reset_cache() -> None:
    """Forget the enumerated drives. For tests."""
    global _cache
    _cache = None
