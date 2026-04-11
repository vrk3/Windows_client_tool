import logging
import os
import re
import shutil
import glob
import string
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Callable, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ScanItem:
    path: str
    size: int        # bytes
    is_dir: bool
    selected: bool = True
    safety: str = "safe"   # "safe" | "caution" | "danger"


@dataclass
class ScanResult:
    items: List[ScanItem] = field(default_factory=list)
    total_size: int = 0

    def selected_size(self) -> int:
        return sum(i.size for i in self.items if i.selected)


def get_dir_size(path: str) -> int:
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def format_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _make_item(path: str, safety: str = "safe", min_age_days: int = 0) -> Optional[ScanItem]:
    """Return ScanItem for path if it exists, else None. Respects min_age_days."""
    if not os.path.exists(path):
        return None
    if min_age_days > 0:
        try:
            mtime = os.path.getmtime(path)
            age_seconds = time.time() - mtime
            if age_seconds < min_age_days * 86400:
                return None
        except OSError:
            return None
    is_dir = os.path.isdir(path)
    size = get_dir_size(path) if is_dir else os.path.getsize(path)
    return ScanItem(path=path, size=size, is_dir=is_dir, safety=safety)


def _make_item_with_age(path: str, safety: str, min_age_days: int) -> Optional[ScanItem]:
    """Return ScanItem for a file only if it meets the age threshold. Direct file helper."""
    try:
        if min_age_days > 0:
            mtime = os.path.getmtime(path)
            if (time.time() - mtime) < min_age_days * 86400:
                return None
        size = os.path.getsize(path)
        return ScanItem(path=path, size=size, is_dir=False, safety=safety)
    except OSError:
        return None


def scan_temp_files(min_age_days: int = 0) -> ScanResult:
    """User temp files (TEMP env var and C:\\Windows\\Temp)."""
    result = ScanResult()
    targets = [
        os.environ.get("TEMP", ""),
        r"C:\Windows\Temp",
    ]
    for t in targets:
        if not t:
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_browser_caches(min_age_days: int = 0) -> ScanResult:
    """Browser cache directories for Chrome, Edge, Firefox."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Google\Chrome\User Data\Default\Cache"),
        os.path.join(local, r"Microsoft\Edge\User Data\Default\Cache"),
    ]
    # Firefox: detect profiles
    ff_profiles = glob.glob(os.path.join(appdata, r"Mozilla\Firefox\Profiles\*\cache2"))
    targets.extend(ff_profiles)
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wu_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Update download cache (requires stopping wuauserv service)."""
    result = ScanResult()
    path = r"C:\Windows\SoftwareDistribution\Download"
    item = _make_item(path, safety="caution", min_age_days=min_age_days)
    if item:
        result.items.append(item)
        result.total_size = item.size
    return result


def scan_prefetch(min_age_days: int = 0) -> ScanResult:
    """Windows Prefetch .pf files — safe to delete, will be re-created as needed."""
    result = ScanResult()
    pf_dir = r"C:\Windows\Prefetch"
    for pf in glob.glob(os.path.join(pf_dir, "*.pf")):
        item = _make_item_with_age(pf, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_recycle_bin(min_age_days: int = 0) -> ScanResult:
    """Recycle Bin on all fixed drives."""
    result = ScanResult()
    for drive in string.ascii_uppercase:
        rb = f"{drive}:\\$Recycle.Bin"
        if os.path.exists(rb):
            item = _make_item(rb, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_event_logs(min_age_days: int = 0) -> ScanResult:
    """Windows event log .evtx files — may be needed for troubleshooting."""
    result = ScanResult()
    logs_dir = r"C:\Windows\System32\winevt\Logs"
    for evtx in glob.glob(os.path.join(logs_dir, "*.evtx")):
        item = _make_item_with_age(evtx, safety="caution", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wer_reports(min_age_days: int = 0) -> ScanResult:
    """Windows Error Reporting crash archives and pending queues."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        r"C:\ProgramData\Microsoft\Windows\WER\ReportArchive",
        r"C:\ProgramData\Microsoft\Windows\WER\ReportQueue",
        os.path.join(local, r"Microsoft\Windows\WER\ReportArchive"),
        os.path.join(local, r"Microsoft\Windows\WER\ReportQueue"),
    ]
    for t in targets:
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_thumbnail_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Explorer thumbnail and icon cache database files."""
    result = ScanResult()
    cache_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Explorer"
    )
    for f in glob.glob(os.path.join(cache_dir, "thumbcache_*.db")):
        item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    icon_cache = os.path.join(cache_dir, "iconcache_*.db")
    for f in glob.glob(icon_cache):
        item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_memory_dumps(min_age_days: int = 0) -> ScanResult:
    """Windows minidumps and full kernel memory dumps — needed for crash debugging."""
    result = ScanResult()

    # Minidump folder: scan individual .dmp files
    minidump_dir = r"C:\Windows\Minidump"
    if os.path.isdir(minidump_dir):
        for f in glob.glob(os.path.join(minidump_dir, "*.dmp")):
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size

    # Single MEMORY.DMP file
    mem_dmp = r"C:\Windows\MEMORY.DMP"
    item = _make_item(mem_dmp, safety="caution", min_age_days=min_age_days)
    if item:
        result.items.append(item)
        result.total_size += item.size

    # LiveKernelReports folder (contains .dmp subfolders)
    lkr_dir = r"C:\Windows\LiveKernelReports"
    if os.path.isdir(lkr_dir):
        dmp_files = glob.glob(os.path.join(lkr_dir, "**", "*.dmp"), recursive=True)
        for f in dmp_files:
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
        # Also include the folder itself if it exists but no .dmp files found
        if not dmp_files:
            item = _make_item(lkr_dir, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size

    return result


def scan_delivery_optimization(min_age_days: int = 0) -> ScanResult:
    """Delivery Optimization peer-to-peer update cache."""
    result = ScanResult()
    targets = [
        r"C:\Windows\SoftwareDistribution\DeliveryOptimization\Cache",
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_logs(min_age_days: int = 0) -> ScanResult:
    """CBS, DISM, Windows Update, and setup log files."""
    result = ScanResult()
    log_patterns = [
        (r"C:\Windows\Logs\CBS", "*.log"),
        (r"C:\Windows\Logs\DISM", "dism.log"),
        (r"C:\Windows\Logs\MoSetup", "*.log"),
        (r"C:\Windows", "setupapi.*.log"),
        (r"C:\Windows", "WindowsUpdate.log"),
    ]
    for dir_path, pattern in log_patterns:
        for f in glob.glob(os.path.join(dir_path, pattern)):
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_windows_old(min_age_days: int = 0) -> ScanResult:
    """Windows.old folder left after an in-place upgrade (often 10-30 GB)."""
    result = ScanResult()
    item = _make_item(r"C:\Windows.old", safety="safe", min_age_days=min_age_days)
    if item:
        result.items.append(item)
        result.total_size = item.size
    return result


def scan_installer_patch_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Installer patch cache ($PatchCache$) — deleting can break MSI uninstalls."""
    result = ScanResult()
    item = _make_item(r"C:\Windows\Installer\$PatchCache$", safety="danger", min_age_days=min_age_days)
    if item:
        result.items.append(item)
        result.total_size = item.size
    return result


def scan_user_crash_dumps(min_age_days: int = 0) -> ScanResult:
    """User-mode crash dump files written by Windows Error Reporting."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, "CrashDumps"),
        os.path.join(local, "Temp"),
    ]
    # Also grab any .dmp files in TEMP
    temp_dir = os.environ.get("TEMP", "")
    if temp_dir:
        for dmp in glob.glob(os.path.join(temp_dir, "*.dmp")):
            item = _make_item_with_age(dmp, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    for t in targets:
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_dev_tool_caches(min_age_days: int = 0) -> ScanResult:
    """Developer tool caches: npm, pip, NuGet, Cargo, Gradle, Maven."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    home = os.path.expanduser("~")
    targets = [
        os.path.join(appdata, "npm-cache"),
        os.path.join(local, "npm-cache"),       # npm cache in LOCALAPPDATA (often 1GB+)
        os.path.join(local, "pip", "cache"),
        os.path.join(appdata, "pip", "cache"),  # pip cache in APPDATA
        os.path.join(local, "nuget", "cache"),
        os.path.join(home, ".nuget", "packages"),
        os.path.join(home, ".cargo", "registry", "cache"),
        os.path.join(home, ".gradle", "caches"),
        os.path.join(home, ".m2", "repository"),
        os.path.join(local, "Yarn", "Cache"),
        os.path.join(appdata, "yarn", "cache"),
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_d3d_shader_cache(min_age_days: int = 0) -> ScanResult:
    """Direct3D and GPU shader cache directories left by games/graphics apps."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, "D3DSCache"),
        os.path.join(local, r"NVIDIA\DXCache"),
        os.path.join(local, r"NVIDIA\GLCache"),
        os.path.join(local, r"AMD\DXCache"),
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_app_caches(min_age_days: int = 0) -> ScanResult:
    """Common app caches: Teams, Discord, Slack, Spotify, VS Code."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata,  r"Microsoft\Teams\Cache"),
        os.path.join(appdata,  r"Microsoft\Teams\blob_storage"),
        os.path.join(appdata,  r"Microsoft\Teams\databases"),
        os.path.join(appdata,  r"Microsoft\Teams\GPUCache"),
        os.path.join(appdata,  r"discord\Cache"),
        os.path.join(appdata,  r"discord\GPUCache"),
        os.path.join(appdata,  r"Slack\Cache"),
        os.path.join(appdata,  r"Slack\GPUCache"),
        os.path.join(local,    r"Spotify\Data"),
        os.path.join(local,    r"Microsoft\VSCode\Cache"),
        os.path.join(local,    r"Microsoft\VSCode\CachedExtensionVSIXs"),
        os.path.join(local,    r"Microsoft\VSCode\CachedData"),
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_appdata_autodiscover(min_age_days: int = 0) -> ScanResult:
    """Auto-discover cache folders under %LOCALAPPDATA% and %APPDATA% (up to 3 dirs deep).
    Skips known browser paths (covered by browser_scanner) and returns only non-empty dirs.
    """
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")

    _CACHE_DIR_NAMES = {
        "cache", "cache2", "cacheddata", "gpucache", "code cache",
        "blob_storage", "crashpad", "crash reports",
        "grshaderCache", "shadercache", "media cache",
    }
    _CACHE_DIR_NAMES = {s.lower() for s in _CACHE_DIR_NAMES}

    _BROWSER_MARKERS = {
        "bravesoftware", "google", "microsoftedge", "vivaldi", "thorium",
        "chromium", "yandex", "opera software", "mozilla", "librewolf",
        "waterfox", "moonchild productions",
    }

    seen: set = set()

    def _is_browser_path(path_lower: str) -> bool:
        return any(m in path_lower for m in _BROWSER_MARKERS)

    def _walk(root: str, depth: int) -> None:
        if depth < 0:
            return
        try:
            for entry in os.scandir(root):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if _is_browser_path(entry.path.lower()):
                    continue
                if entry.name.lower() in _CACHE_DIR_NAMES:
                    rp = os.path.realpath(entry.path)
                    if rp not in seen:
                        seen.add(rp)
                        item = _make_item(entry.path, safety="safe", min_age_days=min_age_days)
                        if item and item.size > 0:
                            result.items.append(item)
                            result.total_size += item.size
                else:
                    _walk(entry.path, depth - 1)
        except (PermissionError, OSError):
            pass

    for base in (local, appdata):
        if base and os.path.isdir(base):
            _walk(base, 2)

    result.items.sort(key=lambda x: x.size, reverse=True)
    return result


def scan_panther_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Setup/Imagex logs in Panther directory — safe after setup completes."""
    result = ScanResult()
    panther_dir = r"C:\Windows\Panther"
    if not os.path.isdir(panther_dir):
        return result
    for f in glob.glob(os.path.join(panther_dir, "*.log")):
        item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_dmf_logs(min_age_days: int = 0) -> ScanResult:
    """Diagnostic Module Framework logs in Windows\\Logs\\DMF — can be large."""
    result = ScanResult()
    dmf_dir = r"C:\Windows\Logs\DMF"
    if not os.path.isdir(dmf_dir):
        return result
    for ext in ("*.log", "*.etl"):
        for f in glob.glob(os.path.join(dmf_dir, ext)):
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


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
            pass
    return result


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
                pass
    return result


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


def scan_winsxs_cleanup(min_age_days: int = 0) -> ScanResult:
    """Analyze WinSxS component store for superseded updates.

    Dism.exe /AnalyzeComponentStore reports superseded component space.
    Items with > 1 MB superseded space are flagged as 'caution'.
    """
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    winsxs_path = os.path.join(windir, "WinSxS")
    if not os.path.isdir(winsxs_path):
        return result
    try:
        proc = subprocess.run(
            ["Dism.exe", "/Online", "/Cleanup-Image", "/AnalyzeComponentStore"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
        output = proc.stdout
        for line in output.splitlines():
            m = re.search(r"\[(\w+)\]\s*:\s*([\d.]+)\s*(\w+)", line)
            if not m:
                continue
            label, size_val, unit = m.group(1), float(m.group(2)), m.group(3)
            bytes_size = size_val * (
                1024 ** 3 if unit == "GB" else 1024 ** 2 if unit == "MB" else 1
            )
            if label == "Superseded" and bytes_size > 1024 * 1024:  # > 1 MB
                result.items.append(ScanItem(
                    path=winsxs_path,
                    size=int(bytes_size),
                    is_dir=True,
                    safety="caution",
                ))
                result.total_size = int(bytes_size)
                break
    except Exception as e:
        logger.warning("WinSxS component store analysis failed: %s", e)
    return result


def cleanup_winsxs(progress_cb: Optional[Callable[[int, int], None]] = None) -> bool:
    """Run Dism.exe /StartComponentCleanup to reduce WinSxS superseded components.

    This operation can take 30 minutes or more.
    Returns True on success, False on failure.
    """
    try:
        proc = subprocess.Popen(
            ["Dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        # Poll periodically so we can report progress
        while True:
            retcode = proc.poll()
            if retcode is not None:
                break
            if progress_cb:
                progress_cb(-1, 0)  # indeterminate
            time.sleep(5)
        stdout, stderr = proc.communicate()
        if progress_cb:
            progress_cb(1, 1)
        logger.info("WinSxS cleanup finished: rc=%s", retcode)
        return retcode == 0
    except Exception as e:
        logger.error("WinSxS cleanup failed: %s", e)
        return False


def scan_store_app_caches(min_age_days: int = 0) -> ScanResult:
    """UWP / Store app local caches under %LocalAppData%\\Packages\\*\\LocalCache. Skips items < 1 MB."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    packages_dir = os.path.join(local, "Packages")
    if not os.path.isdir(packages_dir):
        return result
    try:
        for pkg in os.scandir(packages_dir):
            if not pkg.is_dir(follow_symlinks=False):
                continue
            cache_path = os.path.join(pkg.path, "LocalCache")
            if not os.path.isdir(cache_path):
                continue
            size = get_dir_size(cache_path)
            if size < 1024 * 1024:
                continue
            result.items.append(ScanItem(path=cache_path, size=size, is_dir=True, safety="safe"))
            result.total_size += size
    except (PermissionError, OSError):
        pass
    result.items.sort(key=lambda x: x.size, reverse=True)
    return result


def scan_defender_history(min_age_days: int = 0) -> ScanResult:
    """Windows Defender detection history and scan results — safe to delete."""
    result = ScanResult()
    targets = [
        r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\Service\DetectionHistory",
        r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\CacheManager",
        r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\Results\Resource",
        r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\Results\Quick",
        r"C:\ProgramData\Microsoft\Windows Defender\Scans\History\Results\System",
    ]
    for t in targets:
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── New Advanced Scan Functions ────────────────────────────────────────────────

def scan_recent_files(min_age_days: int = 0) -> ScanResult:
    """Recent .lnk shortcuts and jump list destinations."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Windows\Recent"),
        os.path.join(appdata, r"Microsoft\Windows\Recent\AutomaticDestinations"),
        os.path.join(appdata, r"Microsoft\Windows\Recent\CustomDestinations"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        for f in glob.glob(os.path.join(t, "*.lnk")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
        for f in glob.glob(os.path.join(t, "*.automaticDestinations-ms")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
        for f in glob.glob(os.path.join(t, "*.customDestinations-ms")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_game_caches(min_age_days: int = 0) -> ScanResult:
    """Caches for Steam, Epic, Xbox, Battle.net, EA app, Ubisoft Connect, GOG Galaxy, Discord."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        # Steam
        os.path.join(local, r"Programs\Steam\steamapps"),
        os.path.join(local, r"Programs\Steam\shadercache"),
        os.path.join(local, r"Programs\Steam\htmlcache"),
        os.path.join(local, r"Programs\Steam\downloads"),
        # Epic
        os.path.join(appdata, r"Epic\EpicGamesLauncher\Data\Manifests"),
        os.path.join(local, r"EpicGamesLauncher\Data\Portal\Cache"),
        # Xbox / Gaming Services
        os.path.join(local, r"Packages\Microsoft.GamingServices_*\LocalCache"),
        os.path.join(local, r"Packages\Microsoft.XboxGamingOverlay_*\LocalCache"),
        os.path.join(local, r"Packages\FamilyNotifications.*\LocalState"),
        os.path.join(os.environ.get("PROGRAMDATA", ""), r"XboxLiveDeviceInfo"),
        # Battle.net
        os.path.join(appdata, r"Blizzard\Battle.net\Cache"),
        # EA app
        os.path.join(appdata, r"EA Desktop\Cache"),
        os.path.join(appdata, r"Electronic Arts\EA Desktop\Cache"),
        # Ubisoft Connect
        os.path.join(appdata, r"Ubisoft\Connect\cache"),
        # GOG Galaxy
        os.path.join(appdata, r"GOG.com\Galaxy\Cache"),
        # Discord
        os.path.join(appdata, r"discord\Cache"),
        os.path.join(appdata, r"discord\GPUCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        try:
            size = get_dir_size(t)
            if size > 0:
                item = ScanItem(path=t, size=size, is_dir=True, safety="safe")
                result.items.append(item)
                result.total_size += size
        except OSError:
            pass
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
                pass
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


def scan_ide_caches(min_age_days: int = 0) -> ScanResult:
    """JetBrains, Visual Studio, Notepad++, FileZilla caches."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    home = os.path.expanduser("~")
    temp = os.environ.get("TEMP", "")

    # JetBrains IDEs (find all IDE folders under JetBrains)
    jb_root = os.path.join(local, r"JetBrains")
    if os.path.isdir(jb_root):
        for ide in glob.glob(os.path.join(jb_root, "*IDE*")):
            for sub in ("caches", "index", "logs"):
                sub_path = os.path.join(ide, sub)
                if os.path.isdir(sub_path):
                    item = _make_item(sub_path, safety="safe", min_age_days=min_age_days)
                    if item and item.size > 0:
                        result.items.append(item)
                        result.total_size += item.size

    # Visual Studio .vs folder and component model cache
    vs_folder = os.path.join(local, r"Microsoft\VisualStudio")
    if os.path.isdir(vs_folder):
        for vs_ver in os.listdir(vs_folder):
            vs_path = os.path.join(vs_folder, vs_ver)
            if not os.path.isdir(vs_path):
                continue
            vs_items = [
                os.path.join(vs_path, ".vs"),
                os.path.join(vs_path, "ComponentModelCache"),
                os.path.join(vs_path, "Settings"),
            ]
            for vi in vs_items:
                if os.path.isdir(vi):
                    item = _make_item(vi, safety="safe", min_age_days=min_age_days)
                    if item and item.size > 0:
                        result.items.append(item)
                        result.total_size += item.size
    # VS ~vs* temp files
    if temp:
        for f in glob.glob(os.path.join(temp, "~vs*")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    # Notepad++ backups
    npp_dir = os.path.join(appdata, r"Notepad++\backup")
    if os.path.isdir(npp_dir):
        item = _make_item(npp_dir, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    # FileZilla
    fz_dir = os.path.join(appdata, r"FileZilla")
    if os.path.isdir(fz_dir):
        item = _make_item(fz_dir, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_print_spooler(min_age_days: int = 0) -> ScanResult:
    """Windows print spooler queue — only when spooler service is stopped."""
    result = ScanResult()
    spool_printers = r"C:\Windows\System32\spool\PRINTERS"
    spool_servers = r"C:\Windows\System32\spool\SERVERS"
    # Check service status
    try:
        proc = subprocess.run(
            ["sc", "query", "spooler"],
            capture_output=True, text=True, errors="replace",
            timeout=10,
        )
        if "RUNNING" in proc.stdout.upper():
            # Service running — mark as danger so it's never auto-selected
            item = _make_item(spool_printers, safety="danger", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
            return result
    except Exception:
        pass
    # Spooler not running — safe to clean
    for t in [spool_printers, spool_servers]:
        if os.path.isdir(t):
            item = _make_item(t, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_winsat_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Performance WinSAT XML, Media.ets, and winsat.log files."""
    result = ScanResult()
    winsat_dir = r"C:\Windows\Performance\WinSAT"
    if not os.path.isdir(winsat_dir):
        return result
    targets = [
        os.path.join(winsat_dir, "*.xml"),
        os.path.join(winsat_dir, "Media.ets"),
        os.path.join(winsat_dir, "winsat.log"),
    ]
    for t in targets:
        for f in glob.glob(t):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_etl_logs(min_age_days: int = 0) -> ScanResult:
    """WindowsUpdate ETL, DeliveryOptimization ETL, and ScriptArtifacts logs."""
    result = ScanResult()
    targets = [
        (r"C:\Windows\Logs\WindowsUpdate", "*.etl"),
        (r"C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Logs", "*.log"),
        (r"C:\Windows\Temp\ScriptArtifacts", "*.log"),
    ]
    for dir_path, pattern in targets:
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, pattern)):
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_telemetry(min_age_days: int = 0) -> ScanResult:
    """Windows telemetry, WER Temp, AutoLogger ETL, diagerr/diagwrn logs."""
    result = ScanResult()
    targets = [
        r"C:\ProgramData\Microsoft\Windows\WER\Temp",
        r"C:\Windows\System32\LogFiles\ETLLogs\AutoLogger",
        r"C:\Windows\System32\WDI\*.etl",
        r"C:\Windows\System32\diagerr.log",
        r"C:\Windows\System32\diagwrn.log",
    ]
    for t in targets:
        if "*" in t:
            dir_path, pattern = os.path.split(t)
            if "WDI" in t:
                dir_path = r"C:\Windows\System32\WDI"
                pattern = "*.etl"
            if not os.path.isdir(dir_path):
                continue
            for f in glob.glob(os.path.join(dir_path, pattern)):
                item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
                if item:
                    result.items.append(item)
                    result.total_size += item.size
        else:
            if os.path.isdir(t):
                item = _make_item(t, safety="caution", min_age_days=min_age_days)
                if item:
                    result.items.append(item)
                    result.total_size += item.size
            elif os.path.isfile(t):
                item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
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


def scan_xbox_cache(min_age_days: int = 0) -> ScanResult:
    """Xbox Gaming Services, Xbox Gaming Overlay, FamilyNotifications cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.GamingServices_*\LocalCache"),
        os.path.join(local, r"Packages\Microsoft.XboxGamingOverlay_*\LocalCache"),
        os.path.join(local, r"Packages\FamilyNotifications.*\LocalState"),
        os.path.join(progdata, r"XboxLiveDeviceInfo"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        try:
            size = get_dir_size(t)
            if size > 0:
                result.items.append(ScanItem(path=t, size=size, is_dir=True, safety="safe"))
                result.total_size += size
        except OSError:
            pass
    return result


def scan_maps_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Maps local tile cache and TileDataLayer database."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Local\Packages\Microsoft.WindowsMaps_*\LocalState"),
        os.path.join(local, r"TileDataLayer\Database"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        try:
            size = get_dir_size(t)
            if size > 0:
                result.items.append(ScanItem(path=t, size=size, is_dir=True, safety="safe"))
                result.total_size += size
        except OSError:
            pass
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


def scan_delivery_opt_user(min_age_days: int = 0) -> ScanResult:
    """Per-user Delivery Optimization cache (separate from system-wide)."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\DeliveryOptimization\Cache"),
        os.path.join(local, r"Microsoft\Windows\DeliveryOptimization\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def delete_items(items: List[ScanItem],
                 on_progress: Optional[Callable[[int, int], None]] = None,
                 stop_wuauserv: bool = False) -> Tuple[int, int]:
    """Delete selected items. Returns (deleted_count, error_count).
    If stop_wuauserv=True, wraps deletions in _ServiceStopped("wuauserv")."""

    class _ServiceStopped:
        def __init__(self, name):
            self.name = name
            self._stopped = False

        def __enter__(self):
            try:
                import win32serviceutil
                win32serviceutil.StopService(self.name)
                self._stopped = True
            except Exception:
                pass

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self._stopped:
                try:
                    import win32serviceutil
                    win32serviceutil.StartService(self.name)
                except Exception:
                    pass
            return False  # do not suppress exceptions

    def _do_delete():
        deleted = 0
        errors = 0
        selected = [i for i in items if i.selected]
        total = len(selected)
        for idx, item in enumerate(selected):
            if on_progress:
                on_progress(idx + 1, total)
            try:
                if not os.path.exists(item.path):
                    continue  # already gone — not an error
                if item.is_dir:
                    shutil.rmtree(item.path, ignore_errors=True)
                else:
                    os.remove(item.path)
                deleted += 1
            except OSError:
                errors += 1
        return deleted, errors

    if stop_wuauserv:
        with _ServiceStopped("wuauserv"):
            return _do_delete()
    else:
        return _do_delete()
