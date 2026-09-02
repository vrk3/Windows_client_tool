"""Cleanup scanners: games category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanItem, ScanResult, get_dir_size, _make_item,
)

logger = logging.getLogger(__name__)

def scan_steam_cache(min_age_days: int = 0) -> ScanResult:
    """Steam download cache and update files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    steam_dir = os.path.join(local, r"Programs\Steam")
    if not os.path.isdir(steam_dir):
        return result
    # Steam downloads and shader cache
    for sub in ("steamapps", "shadercache", "htmlcache"):
        sub_path = os.path.join(steam_dir, sub)
        if os.path.isdir(sub_path):
            item = _make_item(sub_path, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

__all__ = [
    'scan_steam_cache',
]