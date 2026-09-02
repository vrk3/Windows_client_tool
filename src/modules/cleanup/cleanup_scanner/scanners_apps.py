"""Cleanup scanners: apps category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item, _make_item_with_age,
)

logger = logging.getLogger(__name__)

def scan_outlook_cache(min_age_days: int = 0) -> ScanResult:
    """Outlook (olk) Edge WebView2 cache and attachments temp files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    olk_dir = os.path.join(local, r"Microsoft\Olk")
    if not os.path.isdir(olk_dir):
        return result
    targets = [
        os.path.join(olk_dir, "EBWebView", "Cache"),
        os.path.join(olk_dir, "Attachments"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        for entry in os.scandir(t):
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

def scan_adobe_cache(min_age_days: int = 0) -> ScanResult:
    """Adobe Media Cache Files, Peak Files, and Logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Adobe\Common\Media Cache Files"),
        os.path.join(appdata, r"Adobe\Common\Media Cache"),
        os.path.join(appdata, r"Adobe\Common\Peak Files"),
        os.path.join(appdata, r"Adobe\Common\Logs"),
        os.path.join(appdata, r"Adobe\Adobe Reckon Media Cache Files"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        for entry in os.scandir(t):
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

def scan_clipboard(min_age_days: int = 0) -> ScanResult:
    """Windows clipboard pending/in-progress temp files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\Clipboard\pending*.tmp"),
        os.path.join(local, r"Microsoft\Windows\Clipboard\inProgress*.tmp"),
        os.path.join(local, r"Microsoft\Windows\INetCache\Clipboard"),
    ]
    for t in targets:
        if "*" in t:
            dir_path = os.path.dirname(t)
            pattern = os.path.basename(t)
            if not os.path.isdir(dir_path):
                continue
            for f in glob.glob(os.path.join(dir_path, pattern)):
                item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
                if item:
                    result.items.append(item)
                    result.total_size += item.size
        else:
            if os.path.isdir(t):
                item = _make_item(t, safety="safe", min_age_days=min_age_days)
                if item and item.size > 0:
                    result.items.append(item)
                    result.total_size += item.size
    return result

def scanetcher_cache(min_age_days: int = 0) -> ScanResult:
    """Balena Etcher cache, image stage, and flash logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"balena"),
        os.path.join(appdata, r"balena"),
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
    'scan_adobe_cache',
    'scan_clipboard',
    'scan_outlook_cache',
    'scanetcher_cache',
]