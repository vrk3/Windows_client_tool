"""Cleanup scanners: browsers category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item,
)

logger = logging.getLogger(__name__)

def scan_brave_cache(min_age_days: int = 0) -> ScanResult:
    """Brave browser cache, code cache, and GPU cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\*\Cache"),
        os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\*\Code Cache"),
        os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\*\GPUCache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_vivaldi_cache(min_age_days: int = 0) -> ScanResult:
    """Vivaldi browser cache, code cache, and blob storage."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Vivaldi\User Data\*\Cache"),
        os.path.join(local, r"Vivaldi\User Data\*\Code Cache"),
        os.path.join(local, r"Vivaldi\User Data\*\GPUCache"),
        os.path.join(appdata, r"Vivaldi\BlobStorage"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_opera_cache(min_age_days: int = 0) -> ScanResult:
    """Opera browser cache, media cache, and code cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Opera Software\Opera Stable\Cache"),
        os.path.join(local, r"Opera Software\Opera Stable\Code Cache"),
        os.path.join(local, r"Opera Software\Opera Stable\GPUCache"),
        os.path.join(local, r"Opera Software\Opera Stable\Media Cache"),
        os.path.join(appdata, r"Opera Software\Opera Stable"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_yandex_cache(min_age_days: int = 0) -> ScanResult:
    """Yandex browser cache and disk cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Yandex\YandexBrowser\User Data\*\Cache"),
        os.path.join(local, r"Yandex\YandexBrowser\User Data\*\Code Cache"),
        os.path.join(local, r"Yandex\YandexBrowser\User Data\*\GPUCache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_edge_cache(min_age_days: int = 0) -> ScanResult:
    """Microsoft Edge cache, code cache, GPU cache, and web data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Edge\User Data\*\Cache"),
        os.path.join(local, r"Microsoft\Edge\User Data\*\Code Cache"),
        os.path.join(local, r"Microsoft\Edge\User Data\*\GPUCache"),
        os.path.join(local, r"Microsoft\Edge\User Data\*\ShaderCache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_firefox_cache(min_age_days: int = 0) -> ScanResult:
    """Mozilla Firefox cache, startup cache, and content prefs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Mozilla\Firefox\Profiles\*\cache2"),
        os.path.join(local, r"Mozilla\Firefox\Profiles\*\cache2"),
        os.path.join(appdata, r"Mozilla\Firefox\Profiles\*\startupCache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_chrome_cache(min_age_days: int = 0) -> ScanResult:
    """Google Chrome cache, code cache, and GPU cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Google\Chrome\User Data\*\Cache"),
        os.path.join(local, r"Google\Chrome\User Data\*\Code Cache"),
        os.path.join(local, r"Google\Chrome\User Data\*\GPUCache"),
        os.path.join(local, r"Google\Chrome\User Data\*\ShaderCache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_tor_browser_cache(min_age_days: int = 0) -> ScanResult:
    """Tor Browser session data, cache, and circuit display logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Tor Browser")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_phantom_cache(min_age_days: int = 0) -> ScanResult:
    """Phantom wallet extension cache and transaction history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"phantom")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_chrome_cache_full(min_age_days: int = 0) -> ScanResult:
    """Chrome full cache paths including GPUCache and Code Cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    profile = os.path.join(local, r"Google\Chrome\User Data\Default")
    targets = [
        os.path.join(profile, r"Cache"),
        os.path.join(profile, r"Code Cache"),
        os.path.join(profile, r"GPUCache"),
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_edge_cache_full(min_age_days: int = 0) -> ScanResult:
    """Microsoft Edge full cache paths including GPUCache and Code Cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    profile = os.path.join(local, r"Microsoft\Edge\User Data\Default")
    targets = [
        os.path.join(profile, r"Cache"),
        os.path.join(profile, r"Code Cache"),
        os.path.join(profile, r"GPUCache"),
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_brave_cache_full(min_age_days: int = 0) -> ScanResult:
    """Brave full cache paths including GPUCache and Code Cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    profile = os.path.join(local, r"BraveSoftware\Brave-Browser\User Data\Default")
    targets = [
        os.path.join(profile, r"Cache"),
        os.path.join(profile, r"Code Cache"),
        os.path.join(profile, r"GPUCache"),
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_inetcache_ietlc(min_age_days: int = 0) -> ScanResult:
    """IE/Edge INetCache, Cookies, and DownloadHistory temp files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\INetCache"),
        os.path.join(local, r"Microsoft\Windows\IEDownloadHistory"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

__all__ = ['scan_brave_cache', 'scan_brave_cache_full', 'scan_chrome_cache', 'scan_chrome_cache_full', 'scan_edge_cache', 'scan_edge_cache_full', 'scan_firefox_cache', 'scan_inetcache_ietlc', 'scan_opera_cache', 'scan_phantom_cache', 'scan_tor_browser_cache', 'scan_vivaldi_cache', 'scan_yandex_cache']
