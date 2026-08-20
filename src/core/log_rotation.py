"""Deletes old dated log/report files past a configurable retention window.

Mirrors Update Center's log-rotation behavior (uc-*.log / report-*.html cleanup):
run once at startup, delete anything matching a glob pattern older than N days.
retention_days == 0 means "keep forever" (no-op), matching that same convention.
"""
import glob
import logging
import os
import time

logger = logging.getLogger(__name__)


def rotate_old_files(directory: str, glob_pattern: str, retention_days: int) -> int:
    """Delete files in `directory` matching `glob_pattern` older than `retention_days`.

    Returns the number of files deleted. Silently skips files it can't remove
    (in use, permissions) and logs a warning rather than raising.
    """
    if retention_days <= 0:
        return 0
    if not directory or not os.path.isdir(directory):
        return 0

    cutoff = time.time() - (retention_days * 86400)
    deleted = 0
    try:
        candidates = glob.glob(os.path.join(directory, glob_pattern))
    except Exception:
        logger.warning("Log rotation: failed to list %s", directory, exc_info=True)
        return 0

    for path in candidates:
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                deleted += 1
        except Exception:
            logger.warning("Log rotation: could not remove %s", path, exc_info=True)

    if deleted:
        logger.info("Log rotation: removed %d old file(s) from %s", deleted, directory)
    return deleted
