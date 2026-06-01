"""Cleanup scanners: comms category (auto-split from cleanup_scanner.py)."""
import logging
import os

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item,
)

logger = logging.getLogger(__name__)

def scan_discord_cache(min_age_days: int = 0) -> ScanResult:
    """Discord cache, code cache, GPU cache, video and voice cache — NOT databases/Local Storage."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"discord\Cache"),
        os.path.join(appdata, r"discord\Code Cache"),
        os.path.join(appdata, r"discord\GPUCache"),
        os.path.join(appdata, r"discord\Video"),
        os.path.join(appdata, r"discord\Voice"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_zoom_cache(min_age_days: int = 0) -> ScanResult:
    """Zoom video meeting recordings temp files and cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Zoom\cache"),
        os.path.join(local, r"Zoom\thumbnail"),
        os.path.join(local, r"Zoom\sticker"),
        os.path.join(local, r"Zoom\report"),
        os.path.join(local, r"Zoom\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_slack_cache(min_age_days: int = 0) -> ScanResult:
    """Slack cache, code cache, GPU cache — NOT Local Storage/IndexedDB/databases/blob."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Slack\Cache"),
        os.path.join(appdata, r"Slack\Code Cache"),
        os.path.join(appdata, r"Slack\GPUCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_telegram_cache(min_age_days: int = 0) -> ScanResult:
    """Telegram cache, video stamps, and session data (keeps messages/contacts)."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Telegram Desktop\cache"),
        os.path.join(appdata, r"Telegram Desktop\tdata"),
        os.path.join(appdata, r"Telegram Desktop\emoji"),
        os.path.join(local, r"Telegram Desktop\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_signal_cache(min_age_days: int = 0) -> ScanResult:
    """Signal cache, attachment temp, and sticker downloads."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Signal\Cache"),
        os.path.join(appdata, r"Signal\Logs"),
        os.path.join(local, r"Signal"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_whatsapp_cache(min_age_days: int = 0) -> ScanResult:
    """WhatsApp media cache and attachment staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"WhatsApp\Cache"),
        os.path.join(local, r"WhatsApp\Media"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_skype_cache(min_age_days: int = 0) -> ScanResult:
    """Skype cache, shared files temp, and media cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Skype\Media\content"),
        os.path.join(appdata, r"Skype\Caches"),
        os.path.join(local, r"Packages\Microsoft.SkypeApp*\LocalState"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_viber_cache(min_age_days: int = 0) -> ScanResult:
    """Viber media cache, thumbnails, and download staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"ViberPC\cache"),
        os.path.join(appdata, r"ViberPC\media"),
        os.path.join(local, r"Viber\Media"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_teams_cache(min_age_days: int = 0) -> ScanResult:
    """Microsoft Teams cache, blob storage, GPU cache — NOT databases/IndexedDB/Local Storage."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Teams\Cache"),
        os.path.join(appdata, r"Microsoft\Teams\blob_storage"),
        os.path.join(appdata, r"Microsoft\Teams\GPUCache"),
        os.path.join(local, r"Microsoft\Teams\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_slack_cache_full(min_age_days: int = 0) -> ScanResult:
    """Slack full cache: cache, code cache, GPU cache, blob storage — NOT Local Storage/IndexedDB/databases."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Slack\Cache"),
        os.path.join(appdata, r"Slack\Code Cache"),
        os.path.join(appdata, r"Slack\GPUCache"),
        os.path.join(appdata, r"Slack\blob_storage"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_discord_full_cache(min_age_days: int = 0) -> ScanResult:
    """Discord full cache: video, voice, GPU cache — keeps login/servers."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"discord\Cache"),
        os.path.join(appdata, r"discord\Code Cache"),
        os.path.join(appdata, r"discord\GPUCache"),
        os.path.join(appdata, r"discord\blob_storage"),
        os.path.join(appdata, r"discord\Video"),
        os.path.join(appdata, r"discord\Voice"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_mumble_cache(min_age_days: int = 0) -> ScanResult:
    """Mumble voice chat logs and overlay cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Mumble\Mumble\logs"),
        os.path.join(appdata, r"Mumble\Overlay\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_teamspeak_cache(min_age_days: int = 0) -> ScanResult:
    """TeamSpeak 3/5 cache, logs, and client query interface."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"TS3Client\logs"),
        os.path.join(appdata, r"TeamSpeak\logs"),
        os.path.join(local, r"TeamSpeak"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_rdp_cache(min_age_days: int = 0) -> ScanResult:
    """Remote Desktop Protocol clipboard temp and redirected drive cache. NOT the Vault."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Terminal Server Client\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_teamviewer_cache(min_age_days: int = 0) -> ScanResult:
    """TeamViewer remote session logs and RemoteFX data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"TeamViewer"),
        os.path.join(appdata, r"TeamViewer11"),
        os.path.join(appdata, r"TeamViewer12"),
        os.path.join(appdata, r"TeamViewer14"),
        os.path.join(appdata, r"TeamViewer15"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_anydesk_cache(min_age_days: int = 0) -> ScanResult:
    """AnyDesk custom session recordings and address book logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"AnyDesk"),
        os.path.join(local, r"AnyDesk"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_parsec_cache(min_age_days: int = 0) -> ScanResult:
    """Parsec virtual display driver logs and encode cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Parsec\logs"),
        os.path.join(appdata, r"Parsec\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_sunshine_cache(min_age_days: int = 0) -> ScanResult:
    """Sunshine GameStream logs and configuration cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Sunshine\logs"),
        os.path.join(appdata, r"Sunshine\config"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_nordpass_cache(min_age_days: int = 0) -> ScanResult:
    """NordPass vault cache and browser extension data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"NordPass"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_discord_canary_cache(min_age_days: int = 0) -> ScanResult:
    """Discord Canary / PTB beta cache and crash reports."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"discordcanary\Cache"),
        os.path.join(appdata, r"discordptb\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_mattermost_cache(min_age_days: int = 0) -> ScanResult:
    """Mattermost client cache and team data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Mattermost")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_zulip_cache(min_age_days: int = 0) -> ScanResult:
    """Zulip client cache and realm data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Zulip")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_element_cache(min_age_days: int = 0) -> ScanResult:
    """Element (Matrix) client cache and session storage."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Element"),
        os.path.join(local, r"Element"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_teamspeak5_cache(min_age_days: int = 0) -> ScanResult:
    """TeamSpeak 5 client cache and identity data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"TS5"),
        os.path.join(appdata, r"TeamSpeak5"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_mumble_full_cache(min_age_days: int = 0) -> ScanResult:
    """Mumble full cache: overlay logs, identity, and certificate store."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Mumble"),
        os.path.join(local, r"Mumble"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_nomachine_cache(min_age_days: int = 0) -> ScanResult:
    """NoMachine NX session logs and connection history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"NoMachine")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_vnc_cache(min_age_days: int = 0) -> ScanResult:
    """VNC (RealVNC / TightVNC / UltraVNC) connection logs and settings."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"RealVNC"),
        os.path.join(appdata, r"TightVNC"),
        os.path.join(appdata, r"UltraVNC"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_remote_desktop_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Remote Desktop redirected print and clipboard cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [os.path.join(local, r"Microsoft\Terminal Server Client")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_skype_for_business_cache(min_age_days: int = 0) -> ScanResult:
    """Skype for Business / Lync meeting recording and content cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Office\16.0\Lync"),
        os.path.join(local, r"Microsoft\Office\16.0\Lync"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_zoom_recordings_cache(min_age_days: int = 0) -> ScanResult:
    """Zoom cloud recording staging and local recording temp."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Zoom\recordings"),
        os.path.join(local, r"Zoom\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_microsoft_teams_full_cache(min_age_days: int = 0) -> ScanResult:
    """Microsoft Teams full cache: GPUCache, blob_storage, Cache — NOT databases/IndexedDB/Local Storage."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Teams\Cache"),
        os.path.join(appdata, r"Microsoft\Teams\blob_storage"),
        os.path.join(appdata, r"Microsoft\Teams\GPUCache"),
        os.path.join(local, r"Microsoft\Teams\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_ms_teams_npc_cache(min_age_days: int = 0) -> ScanResult:
    """Microsoft Teams (New PRC) UWP local cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.MSTeamsNPC*\LocalCache"),
    ]
    import glob as _glob
    for pattern in targets:
        for t in _glob.glob(pattern):
            if not os.path.isdir(t):
                continue
            item = _make_item(t, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_whatsapp_uwp_cache(min_age_days: int = 0) -> ScanResult:
    """WhatsApp Desktop UWP local cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\WhatsAppDesktop*\LocalCache"),
    ]
    import glob as _glob
    for pattern in targets:
        for t in _glob.glob(pattern):
            if not os.path.isdir(t):
                continue
            item = _make_item(t, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_anydesk_thumbnails(min_age_days: int = 0) -> ScanResult:
    """AnyDesk connection thumbnails — safe to clear."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"AnyDesk\thumbnails"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_discord_developer_logs(min_age_days: int = 0) -> ScanResult:
    """Discord logs folder — safe to clear."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"discord\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

__all__ = ['scan_anydesk_cache', 'scan_anydesk_thumbnails', 'scan_discord_cache', 'scan_discord_canary_cache', 'scan_discord_developer_logs', 'scan_discord_full_cache', 'scan_element_cache', 'scan_mattermost_cache', 'scan_microsoft_teams_full_cache', 'scan_ms_teams_npc_cache', 'scan_mumble_cache', 'scan_mumble_full_cache', 'scan_nomachine_cache', 'scan_nordpass_cache', 'scan_parsec_cache', 'scan_rdp_cache', 'scan_remote_desktop_cache', 'scan_signal_cache', 'scan_skype_cache', 'scan_skype_for_business_cache', 'scan_slack_cache', 'scan_slack_cache_full', 'scan_sunshine_cache', 'scan_teams_cache', 'scan_teamspeak5_cache', 'scan_teamspeak_cache', 'scan_teamviewer_cache', 'scan_telegram_cache', 'scan_viber_cache', 'scan_vnc_cache', 'scan_whatsapp_cache', 'scan_whatsapp_uwp_cache', 'scan_zoom_cache', 'scan_zoom_recordings_cache', 'scan_zulip_cache']
