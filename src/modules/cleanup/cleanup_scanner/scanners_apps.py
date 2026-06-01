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

def scan_office_temp(min_age_days: int = 0) -> ScanResult:
    """Microsoft Office temp, unsaved files, and OfficeFileCache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    temp = os.environ.get("TEMP", "")
    targets = [
        os.path.join(local, r"Microsoft\Office\*\OfficeFileCache"),
        os.path.join(appdata, r"Microsoft\Office\*\UnsavedFiles"),
        os.path.join(appdata, r"Microsoft\Office\*\OfficeFileCache"),
    ]
    for t in targets:
        for office_ver in glob.glob(t):
            item = _make_item(office_ver, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    # Excel/Word temp files in TEMP
    if temp:
        for f in glob.glob(os.path.join(temp, "Excel*.tmp")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
        for f in glob.glob(os.path.join(temp, "Word*.tmp")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
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

def scan_sticky_notes(min_age_days: int = 0) -> ScanResult:
    """Sticky Notes database and UWP sticky notes state."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Sticky Notes\StickyNotes.sqm"),
        os.path.join(local, r"Packages\Microsoft.MicrosoftStickyNotes_*\LocalState"),
    ]
    for t in targets:
        if not os.path.isdir(t) and not os.path.isfile(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_office_cache_extended(min_age_days: int = 0) -> ScanResult:
    """Extended Office caches: Teams, OneNote, Publisher, Visio caches."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Teams\Cache"),
        os.path.join(appdata, r"Microsoft\Teams\blob_storage"),
        os.path.join(appdata, r"Microsoft\Teams\GPUCache"),
        os.path.join(local, r"Microsoft\OneNote\*"),
        os.path.join(local, r"Microsoft\OneNoteCache"),
        os.path.join(appdata, r"Microsoft\UUS"),
    ]
    for t in targets:
        if "*" in t:
            for found in glob.glob(t):
                item = _make_item(found, safety="safe", min_age_days=min_age_days)
                if item and item.size > 0:
                    result.items.append(item)
                    result.total_size += item.size
        elif os.path.isdir(t):
            item = _make_item(t, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_notion_cache(min_age_days: int = 0) -> ScanResult:
    """Notion cache, IndexedDB, and render cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Notion\shared"),
        os.path.join(local, r"Notion"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_obsidian_cache(min_age_days: int = 0) -> ScanResult:
    """Obsidian vault cache, plugins, and community plugin downloads."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"obsidian\cache"),
        os.path.join(appdata, r"obsidian\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_logseq_cache(min_age_days: int = 0) -> ScanResult:
    """Logseq cache, Calva/REPL server logs, and graph database."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Logseq\cache"),
        os.path.join(appdata, r"Logseq\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_evernote_cache(min_age_days: int = 0) -> ScanResult:
    """Evernote cache and local database temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Evernote\logs"),
        os.path.join(appdata, r"Evernote\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_notezilla_cache(min_age_days: int = 0) -> ScanResult:
    """Notezilla sticky notes cache and log files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Notezilla\cache"),
        os.path.join(appdata, r"Notezilla\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_veeam_cache(min_age_days: int = 0) -> ScanResult:
    """Veeam Backup metadata cache and catalog staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Veeam\BackupCatalog"),
        os.path.join(appdata, r"Veeam\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_acronis_cache(min_age_days: int = 0) -> ScanResult:
    """Acronis True Image backup catalog and log files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(appdata, r"Acronis\Logs"),
        os.path.join(progdata, r"Acronis\Catalog"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_macrium_cache(min_age_days: int = 0) -> ScanResult:
    """Macrium Reflect backup logs and differential chain metadata."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Macrium\Reflect\logs"),
        os.path.join(appdata, r"Macrium\Reflect\catalog"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_thunderbird_cache(min_age_days: int = 0) -> ScanResult:
    """Mozilla Thunderbird global inbox cache and panacea.db."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Thunderbird\Profiles\*\cache2"),
        os.path.join(appdata, r"Thunderbird\Profiles\*\startupCache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_outlook_temp_cache(min_age_days: int = 0) -> ScanResult:
    """Outlook send/receive offline folder, .ost compact temp, and sync logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Outlook"),
        os.path.join(local, r"Microsoft\Outlook"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_em_client_cache(min_age_days: int = 0) -> ScanResult:
    """eM Client database temp and attachment staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"eM Client\logs"),
        os.path.join(appdata, r"eM Client\temp"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_ssh_keys_cache(min_age_days: int = 0) -> ScanResult:
    """SSH known_hosts.old backup files only — NOT authorized_keys or private keys."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".ssh\known_hosts.old"),
    ]
    for t in targets:
        if not os.path.isfile(t):
            continue
        item = _make_item_with_age(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_putty_cache(min_age_days: int = 0) -> ScanResult:
    """PuTTY session data, host keys, and scrollback logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"SimonTatham\PuTTY"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_winscp_cache(min_age_days: int = 0) -> ScanResult:
    """WinSCP temporary files, synchronization archive, and cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"WinSCP\temp"),
        os.path.join(appdata, r"WinSCP\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_filezilla_cache(min_age_days: int = 0) -> ScanResult:
    """FileZilla sitemanager.xml, queue, and temp transfer data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"FileZilla"),
        os.path.join(local, r"FileZilla"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_keepass_cache(min_age_days: int = 0) -> ScanResult:
    """KeePass lock file, key file temp, and HTTP proxy credentials."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"KeePass"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_bitwarden_cache(min_age_days: int = 0) -> ScanResult:
    """Bitwarden CLI vault lock and browser extension cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Bitwarden"),
        os.path.join(local, r"Bitwarden"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_1password_cache(min_age_days: int = 0) -> ScanResult:
    """1Password SSH agent cache and session data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"1Password"),
        os.path.join(local, r"1Password"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_lastpass_cache(min_age_days: int = 0) -> ScanResult:
    """LastPass browser extension vault cache and LPAPI token."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"LastPass"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_dashlane_cache(min_age_days: int = 0) -> ScanResult:
    """Dashlane credential cache and dark web monitoring data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Dashlane"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_defraggler_logs(min_age_days: int = 0) -> ScanResult:
    """Defraggler disk analysis history and exclude list cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Defraggler"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_crystaldiskinfo_cache(min_age_days: int = 0) -> ScanResult:
    """CrystalDiskInfo health log and S.M.A.R.T. data cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"CrystalDiskInfo"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_hdtune_logs(min_age_days: int = 0) -> ScanResult:
    """HD Tune health scan log and benchmark result cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"HD Tune"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_msi_afterburner_cache(min_age_days: int = 0) -> ScanResult:
    """MSI Afterburner overlay logs and hardware monitoring cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"MSI Afterburner"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_nzxt_cam_cache(min_age_days: int = 0) -> ScanResult:
    """NZXT CAM hardware monitor logs and RGB profile cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"NZXT CAM"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_coretemp_logs(min_age_days: int = 0) -> ScanResult:
    """Core Temp history log and calibration cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Realtech\OpenHardwareMonitor"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_rufus_logs(min_age_days: int = 0) -> ScanResult:
    """Rufus ISO download cache and log files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Rufus"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
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

def scan_ventoy_cache(min_age_days: int = 0) -> ScanResult:
    """Ventoy plugin data and ISO collection config staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Ventoy"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_hwinfo64_cache(min_age_days: int = 0) -> ScanResult:
    """HWiNFO64 sensor log history and sensor data cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"HWiNFO64"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_aida64_cache(min_age_days: int = 0) -> ScanResult:
    """AIDA64 sensor log and report export cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"AIDA64"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_windows_photo_viewer_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Photo Viewer thumbnail and temporary decode cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows Photo Viewer"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_clevo_ControlCenter_cache(min_age_days: int = 0) -> ScanResult:
    """Clevo ControlCenter fan profile logs and thermal sensor cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Clevo"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_thrustmaster_cache(min_age_days: int = 0) -> ScanResult:
    """Thrustmaster T.A.R.G.E.T. profile logs and firmware update staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Thrustmaster"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_office_clicktorun_cache(min_age_days: int = 0) -> ScanResult:
    """Office Click-to-Run setup pipeline staging and update download cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Office\ClickToRun"),
        os.path.join(local, r"Microsoft\Office\Updates"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_quickbooks_cache(min_age_days: int = 0) -> ScanResult:
    """QuickBooks log files and transaction audit trail cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Intuit")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_complus_cache(min_age_days: int = 0) -> ScanResult:
    """COM+ application metadata and registration cache."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Registration"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_fax_account_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Fax Service cover page cache and received fax staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [os.path.join(local, r"Microsoft\Windows\Fax")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_windows_camera_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Camera app cache, HDR photos staging, and video trim temp."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.WindowsCamera*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_voice_recorder_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Voice Recorder recordings and audio processing temp."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.WindowsSoundRecorder*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result

def scan_7zip_cache(min_age_days: int = 0) -> ScanResult:
    """7-Zip recent archive history and temporary extraction output."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"7-Zip")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_winrar_cache(min_age_days: int = 0) -> ScanResult:
    """WinRAR recent archive list and temp extraction folder."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"WinRAR")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_peazip_cache(min_age_days: int = 0) -> ScanResult:
    """PeaZip temp extraction and bookmark history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"PeaZip")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_bandizip_cache(min_age_days: int = 0) -> ScanResult:
    """Bandizip recent archive history and preview cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Bandizip")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_winzip_cache(min_age_days: int = 0) -> ScanResult:
    """WinZip history database and secure temp files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"WinZip")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_evernote_full_cache(min_age_days: int = 0) -> ScanResult:
    """Evernote full cache: databases, thumbnails, and web clip cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Evernote\logs"),
        os.path.join(appdata, r"Evernote\Cache"),
        os.path.join(appdata, r"Evernote\Thumbnails"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_simplenote_cache(min_age_days: int = 0) -> ScanResult:
    """Simplenote sync cache and local database."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Simplenote")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_joplin_cache(min_age_days: int = 0) -> ScanResult:
    """Joplin markdown notes cache and synchronisation database."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Joplin"),
        os.path.join(local, r"Joplin"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_zotero_cache(min_age_days: int = 0) -> ScanResult:
    """Zotero PDF index cache, translator data, and connector browser cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Zotero"),
        os.path.join(local, r"Zotero"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_mendeley_cache(min_age_days: int = 0) -> ScanResult:
    """Mendeley Desktop PDF index and citation cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Mendeley Ltd")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_readcube_cache(min_age_days: int = 0) -> ScanResult:
    """ReadCube paper viewer cache and annotation data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"ReadCube")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_papers_cache(min_age_days: int = 0) -> ScanResult:
    """Papers 3/4 PDF library index and sync cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Papers")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_scrivener_cache(min_age_days: int = 0) -> ScanResult:
    """Scrivener project auto-save and compile staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Scrivener")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_bluetooth_cache(min_age_days: int = 0) -> ScanResult:
    """Bluetooth radio firmware cache and paired device pairing records."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\BthCache"),
        os.path.join(local, r"Microsoft\Windows\INF"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_wifi_profiles_cache(min_age_days: int = 0) -> ScanResult:
    """Saved Wi-Fi network profiles (XML) and WLAN autoconfig service cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Microsoft\Windows\WLAN")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_ccleaner_cache(min_age_days: int = 0) -> ScanResult:
    """CCleaner scan history and custom cleaner rule cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"CCleaner")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_bleachbit_cache(min_age_days: int = 0) -> ScanResult:
    """BleachBit痕清理工具 cache and cleaner definition update cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"BleachBit")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_glary_utilities_cache(min_age_days: int = 0) -> ScanResult:
    """Glary Utilities registry backup and disk cleaning history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"GlarySoft")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_wise_cache360_cache(min_age_days: int = 0) -> ScanResult:
    """Wise Care 365 registry backup and system optimization history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"WiseFolderHider")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_auslogics_cache(min_age_days: int = 0) -> ScanResult:
    """Auslogics BoostSpeed registry backup and disk defrag log."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Auslogics")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_privacy_guardian_cache(min_age_days: int = 0) -> ScanResult:
    """Privacy Guardian browser monitoring log and telemetry history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Privacy Guardian")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_duplicate_cleaner_cache(min_age_days: int = 0) -> ScanResult:
    """Duplicate Cleaner Pro scan database and thumbnail cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Duplicate Cleaner")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_disk_nuker_cache(min_age_days: int = 0) -> ScanResult:
    """Disk Ninja / Disk Pulse disk change log and alert history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Disk Pulse")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_easeus_cache(min_age_days: int = 0) -> ScanResult:
    """EaseUS Todo Backup image catalog and clone log."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"EaseUS")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_minitool_cache(min_age_days: int = 0) -> ScanResult:
    """Minitool partition wizard logs and data recovery scan history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Minitool")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_aomei_cache(min_age_days: int = 0) -> ScanResult:
    """AOMEI Backupper backup image catalog and sync log."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"AOMEI")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_paragon_cache(min_age_days: int = 0) -> ScanResult:
    """Paragon Hard Disk Manager backup catalog and imaging log."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Paragon")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_macrium_reflect_logs(min_age_days: int = 0) -> ScanResult:
    """Macrium Reflect imaging log and differential backup catalog."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Macrium")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_corsair_logs(min_age_days: int = 0) -> ScanResult:
    """Corsair iCUE software logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Corsair\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_windows_photos_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Photos UWP cache and temp files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.Windows.Photos*\LocalCache"),
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

def scan_sparkle_logs(min_age_days: int = 0) -> ScanResult:
    """Sparkle (macOS-style update checker) logs for cross-platform apps."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"sparkle\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

def scan_bitwarden_desktop_cache(min_age_days: int = 0) -> ScanResult:
    """Bitwarden Desktop app cache and logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Bitwarden\cache"),
        os.path.join(local, r"Bitwarden\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result

__all__ = ['scan_1password_cache', 'scan_7zip_cache', 'scan_acronis_cache', 'scan_adobe_cache', 'scan_aida64_cache', 'scan_aomei_cache', 'scan_auslogics_cache', 'scan_bandizip_cache', 'scan_bitwarden_cache', 'scan_bitwarden_desktop_cache', 'scan_bleachbit_cache', 'scan_bluetooth_cache', 'scan_ccleaner_cache', 'scan_clevo_ControlCenter_cache', 'scan_clipboard', 'scan_complus_cache', 'scan_coretemp_logs', 'scan_corsair_logs', 'scan_crystaldiskinfo_cache', 'scan_dashlane_cache', 'scan_defraggler_logs', 'scan_disk_nuker_cache', 'scan_duplicate_cleaner_cache', 'scan_easeus_cache', 'scan_em_client_cache', 'scan_evernote_cache', 'scan_evernote_full_cache', 'scan_fax_account_cache', 'scan_filezilla_cache', 'scan_glary_utilities_cache', 'scan_hdtune_logs', 'scan_hwinfo64_cache', 'scan_joplin_cache', 'scan_keepass_cache', 'scan_lastpass_cache', 'scan_logseq_cache', 'scan_macrium_cache', 'scan_macrium_reflect_logs', 'scan_mendeley_cache', 'scan_minitool_cache', 'scan_msi_afterburner_cache', 'scan_notezilla_cache', 'scan_notion_cache', 'scan_nzxt_cam_cache', 'scan_obsidian_cache', 'scan_office_cache_extended', 'scan_office_clicktorun_cache', 'scan_office_temp', 'scan_outlook_cache', 'scan_outlook_temp_cache', 'scan_papers_cache', 'scan_paragon_cache', 'scan_peazip_cache', 'scan_privacy_guardian_cache', 'scan_putty_cache', 'scan_quickbooks_cache', 'scan_readcube_cache', 'scan_rufus_logs', 'scan_scrivener_cache', 'scan_simplenote_cache', 'scan_sparkle_logs', 'scan_ssh_keys_cache', 'scan_sticky_notes', 'scan_thrustmaster_cache', 'scan_thunderbird_cache', 'scan_veeam_cache', 'scan_ventoy_cache', 'scan_voice_recorder_cache', 'scan_wifi_profiles_cache', 'scan_windows_camera_cache', 'scan_windows_photo_viewer_cache', 'scan_windows_photos_cache', 'scan_winrar_cache', 'scan_winscp_cache', 'scan_winzip_cache', 'scan_wise_cache360_cache', 'scan_zotero_cache', 'scanetcher_cache']
