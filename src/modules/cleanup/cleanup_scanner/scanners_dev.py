"""Cleanup scanners: dev category (auto-split from cleanup_scanner.py)."""
import logging
import os

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item,
)

logger = logging.getLogger(__name__)

def scan_winget_packages(min_age_days: int = 0) -> ScanResult:
    """Windows Package Manager (WinGet) downloaded package cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    winget_dir = os.path.join(local, r"Microsoft\WinGet\Packages")
    if not os.path.isdir(winget_dir):
        return result
    for pkg in os.listdir(winget_dir):
        pkg_path = os.path.join(winget_dir, pkg)
        item = _make_item(pkg_path, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_yarn_cache(min_age_days: int = 0) -> ScanResult:
    """Yarn package manager cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
    targets = [
        os.path.join(appdata, r"yarn\Cache"),
        os.path.join(os.path.expanduser("~"), r".config\yarn\Berry\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

__all__ = [
    'scan_winget_packages',
    'scan_yarn_cache',
]