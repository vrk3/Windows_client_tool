"""Disk-space preflight checks.

Used before operations that write a meaningful amount of data to a specific
drive — installing Windows Updates, writing maintenance reports/history — so
callers can surface one clear "not enough free space" message up front
instead of a cryptic mid-operation failure (a WU install failing with a
low-level HRESULT, or a report write raising OSError partway through a file).
"""
import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# Windows Update needs headroom well beyond the payload size itself (staging,
# component-store expansion, potential rollback images). This is a
# conservative floor, not a precise budget — it exists to catch the "almost
# no free space" case, not to model WU's actual disk usage.
WU_MIN_FREE_GB = 2.0
WU_SIZE_MULTIPLIER = 1.5

# Reports/history are tiny HTML/JSON files; this just guards against trying
# to write to a genuinely full drive.
REPORT_MIN_FREE_MB = 50.0


def get_free_bytes(path: str) -> Optional[int]:
    """Return free bytes on the drive containing `path`, or None if it can't
    be determined (missing drive, permissions, etc.) — logs a warning rather
    than raising, since this is only ever used for an advisory check."""
    try:
        target = path if os.path.exists(path) else (os.path.dirname(os.path.abspath(path)) or ".")
        return shutil.disk_usage(target).free
    except Exception:
        logger.warning("disk_space: could not determine free space for %s", path, exc_info=True)
        return None


def check_wu_preflight(total_size_mb: float, target_dir: Optional[str] = None) -> Optional[str]:
    """Check free space before a Windows Update install run.

    Returns None if it's safe to proceed, else a human-readable reason the
    install should be blocked. When free space can't be determined at all,
    this does NOT block (returns None) — an unknown isn't a reason to stop
    an update the user asked for.
    """
    drive = target_dir or (os.environ.get("SystemDrive", "C:") + "\\")
    free = get_free_bytes(drive)
    if free is None:
        return None
    free_gb = free / (1024 ** 3)
    needed_gb = max(WU_MIN_FREE_GB, (total_size_mb / 1024.0) * WU_SIZE_MULTIPLIER)
    if free_gb < needed_gb:
        return (
            f"Only {free_gb:.1f} GB free on {drive} — need roughly {needed_gb:.1f} GB "
            f"to safely install {total_size_mb:.0f} MB of updates. Free up space and try again."
        )
    return None


def check_report_preflight(directory: str) -> Optional[str]:
    """Check free space before writing a report/history file into `directory`.

    Returns None if it's safe to proceed, else a human-readable reason to
    skip the write. Same "unknown doesn't block" behavior as check_wu_preflight.
    """
    free = get_free_bytes(directory)
    if free is None:
        return None
    free_mb = free / (1024 ** 2)
    if free_mb < REPORT_MIN_FREE_MB:
        return f"Only {free_mb:.0f} MB free near {directory} — skipping write."
    return None
