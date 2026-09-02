"""Cleanup scanners: cloud category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item, _make_item_with_age,
)

logger = logging.getLogger(__name__)

def scan_onedrive_logs(min_age_days: int = 0) -> ScanResult:
    """OneDrive sync logs under %LOCALAPPDATA%\\Microsoft\\OneDrive\\logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    log_dir = os.path.join(local, r"Microsoft\OneDrive\logs")
    if not os.path.isdir(log_dir):
        return result
    for f in glob.glob(os.path.join(log_dir, "*.log")):
        item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_google_drive_cache(min_age_days: int = 0) -> ScanResult:
    """Google Drive File Stream and Backup and Sync cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Google\DriveFS"),
        os.path.join(local, r"Google\Backup and Sync"),
        os.path.join(local, r"Google\DriveFS\Cache"),
        os.path.join(local, r"Google\DriveFS\Logs"),
        os.path.join(appdata, r"Google\DriveFS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scanPIA_vpn_cache(min_age_days: int = 0) -> ScanResult:
    """Private Internet Access VPN cache and connection diagnostic logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"pia")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

__all__ = [
    'scanPIA_vpn_cache',
    'scan_google_drive_cache',
    'scan_onedrive_logs',
]