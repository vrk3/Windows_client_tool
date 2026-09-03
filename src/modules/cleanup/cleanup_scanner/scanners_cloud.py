"""Cleanup scanners: cloud category (auto-split from cleanup_scanner.py)."""
import logging
import os

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item,
)

logger = logging.getLogger(__name__)

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
]