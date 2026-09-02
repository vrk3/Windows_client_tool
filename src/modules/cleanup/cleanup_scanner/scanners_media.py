"""Cleanup scanners: media category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item, _make_item_with_age,
)

logger = logging.getLogger(__name__)

def scan_stremio_cache(min_age_days: int = 0) -> ScanResult:
    """Stremio server-side torrent/cache data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    stremio_dir = os.path.join(appdata, r"stremio\stremio-server\stremio-cache")
    if not os.path.isdir(stremio_dir):
        return result
    for entry in os.scandir(stremio_dir):
        try:
            if entry.is_dir():
                item = _make_item(entry.path, safety="safe", min_age_days=min_age_days)
            else:
                item = _make_item_with_age(entry.path, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
        except OSError:
            logger.debug("Ignored OSError", exc_info=True)
    return result

__all__ = [
    'scan_stremio_cache',
]