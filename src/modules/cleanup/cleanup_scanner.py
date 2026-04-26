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
            creationflags=subprocess.CREATE_NO_WINDOW,
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
            creationflags=subprocess.CREATE_NO_WINDOW,
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
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if "RUNNING" in proc.stdout.upper():
            # Service running — mark as danger so it's never auto-selected
            item = _make_item(spool_printers, safety="danger", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
            return result
    except Exception as e:
        logger.warning("Spooler scan failed: %s", e)
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


def scan_font_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Font Cache service (FNTCACHE.DAT) and font link temporary files."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\FNTCACHE.DAT"),
        os.path.join(windir, r"ServiceProfiles\LocalService\AppData\Local\FontDrivers"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts"),
    ]
    for t in targets:
        if not os.path.exists(t):
            continue
        if os.path.isfile(t):
            item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
        else:
            item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_crash_dumps_system(min_age_days: int = 0) -> ScanResult:
    """System-wide crash dumps: MEMORY.DMP, Minidump folder, LiveKernelReports."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Minidump"),
        os.path.join(windir, r"LiveKernelReports"),
        os.path.join(windir, r"MEMORY.DMP"),
        os.path.join(windir, r"cluster.log"),
    ]
    for t in targets:
        if not os.path.exists(t):
            continue
        if os.path.isfile(t):
            item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
        else:
            item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_bits_transfers(min_age_days: int = 0) -> ScanResult:
    """BITS (Background Intelligent Transfer Service) transfer job queue files."""
    result = ScanResult()
    targets = [
        r"C:\Windows\Tasks\BITS",
        r"C:\ProgramData\Microsoft\Windows\BITS",
        os.path.join(os.environ.get("PROGRAMDATA", ""), r"Microsoft\Windows\BITS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_update_cleanup(min_age_days: int = 0) -> ScanResult:
    """Windows Update cleanup: downloaded patches, softwaredistribution backup, orphaned patches."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"SoftwareDistribution\Download"),
        os.path.join(windir, r"SoftwareDistribution\Backup"),
        os.path.join(windir, r"WinSxS\Temp"),
        os.path.join(windir, r"Temp\PostReboot"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_dxgi_cache(min_age_days: int = 0) -> ScanResult:
    """DirectX Graphics Infrastructure cache — GPU-related temp data from games."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"D3DSCache"),
        os.path.join(local, r"NVIDIA\DXCache"),
        os.path.join(local, r"NVIDIA\GLCache"),
        os.path.join(local, r"AMD\DXCache"),
        os.path.join(local, r"AMD\VulkanCache"),
        os.path.join(local, r"Intel\GraphicsCache"),
        os.path.join(local, r"Intel\GLCache"),
        os.path.join(local, r"Microsoft\DirectX"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_perflogs(min_age_days: int = 0) -> ScanResult:
    """Windows Performance Logs — BLG files and output from scheduled perf monitoring."""
    result = ScanResult()
    targets = [
        r"C:\PerfLogs\Admin",
        r"C:\PerfLogs\Custom",
        r"C:\PerfLogs\System",
        r"C:\Windows\System32\LogFiles\WMI\RtTracking",
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_diag_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Diagnostic logs: ETW trace logs, MSI install logs, DeviceMetaData."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(windir, r"Logs\CBS"),
        os.path.join(windir, r"Logs\DISM"),
        os.path.join(windir, r"Logs\MoSetup"),
        os.path.join(windir, r"Logs\SIH"),
        os.path.join(windir, r"Logs\WindowsUpdate"),
        os.path.join(windir, r"System32\WDI\*.etl"),
        os.path.join(windir, r"System32\diagerr.log"),
        os.path.join(windir, r"System32\diagwrn.log"),
        os.path.join(local, r"Microsoft\Windows\WDI\LogFiles"),
        os.path.join(local, r"Microsoft\Windows\DeviceMetadataStore"),
    ]
    for t in targets:
        if "*" in t:
            dir_path, pattern = os.path.split(t)
            if not os.path.isdir(dir_path):
                continue
            for f in glob.glob(os.path.join(dir_path, pattern)):
                item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
                if item:
                    result.items.append(item)
                    result.total_size += item.size
        elif os.path.isdir(t):
            item = _make_item(t, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
        elif os.path.isfile(t):
            item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
            if item:
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


def scan_spotify_cache(min_age_days: int = 0) -> ScanResult:
    """Spotify local track cache and thumbnail cache — keeps login/settings."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Spotify\Data"),
        os.path.join(local, r"Spotify\Cache"),
        os.path.join(local, r"Spotify\thumbs"),
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


def scan_epic_launcher_cache(min_age_days: int = 0) -> ScanResult:
    """Epic Games Launcher download cache, shader cache, and web data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"EpicGamesLauncher\Data\Portal\Cache"),
        os.path.join(local, r"EpicGamesLauncher\Data\Manifests"),
        os.path.join(local, r"EpicGamesLauncher\Saved\webcache"),
        os.path.join(local, r"EpicGamesLauncher\Saved\logs"),
        os.path.join(local, r"EpicGamesLauncher\Saved\ShaderCompiler"),
        os.path.join(appdata, r"Epic\EpicGamesLauncher\Data\Manifests"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ea_app_cache(min_age_days: int = 0) -> ScanResult:
    """EA app (new) and Origin cache — download cache and web data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"EA Desktop\Cache"),
        os.path.join(appdata, r"EA Desktop\logs"),
        os.path.join(appdata, r"Electronic Arts\EA Desktop\Cache"),
        os.path.join(appdata, r"Origin\LocalContent"),
        os.path.join(appdata, r"Origin\logs"),
        os.path.join(appdata, r"Origin\PackageCache"),
        os.path.join(local, r"Origin\WebCache"),
        os.path.join(local, r"Origin\LocalContent"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gog_cache(min_age_days: int = 0) -> ScanResult:
    """GOG Galaxy cache, web cache, and game manager data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"GOG.com\Galaxy\Cache"),
        os.path.join(appdata, r"GOG.com\Galaxy\WebCache"),
        os.path.join(appdata, r"GOG.com\Galaxy\logs"),
        os.path.join(local, r"GOG.com\Galaxy\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ubisoft_cache(min_age_days: int = 0) -> ScanResult:
    """Ubisoft Connect cache, download, and shader cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Ubisoft\Connect\cache"),
        os.path.join(appdata, r"Ubisoft\Connect\downloads"),
        os.path.join(appdata, r"Ubisoft\Connect\logs"),
        os.path.join(appdata, r"Ubisoft\Connect\shader-cache"),
        os.path.join(local, r"Ubisoft\Connect\Cache"),
        os.path.join(local, r"Ubisoft\Connect\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_humble_cache(min_age_days: int = 0) -> ScanResult:
    """Humble Bundle app cache and downloads."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Humble Bundle\Humble App\Cache"),
        os.path.join(local, r"Humble Bundle\Humble App\logs"),
        os.path.join(appdata, r"HumbleBundle\Humble App\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_itch_cache(min_age_days: int = 0) -> ScanResult:
    """itch.io game manager cache and downloads."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"itch\apps"),
        os.path.join(local, r"itch\buckets"),
        os.path.join(local, r"itch\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gamepass_cache(min_age_days: int = 0) -> ScanResult:
    """Xbox Game Pass (PC) app cache, downloads, and shader cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\XboxLiveDeviceInfo"),
        os.path.join(local, r"Packages\Microsoft.GamingServices_*\LocalCache"),
        os.path.join(local, r"Packages\Microsoft.XboxGameCallableUI_*\LocalCache"),
        os.path.join(local, r"Packages\FamilyNotifications.*\LocalState"),
        os.path.join(progdata, r"XboxLiveDeviceInfo"),
        os.path.join(local, r"Microsoft\GameBar\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_java_cache(min_age_days: int = 0) -> ScanResult:
    """Java WebStart, Maven local repo, and Gradle caches."""
    result = ScanResult()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Maven\repository"),
        os.path.join(home, r".m2\repository"),
        os.path.join(home, r".gradle\caches"),
        os.path.join(home, r".gradle\daemon"),
        os.path.join(home, r".ivy2\cache"),
        os.path.join(local, r"Sun\Java\Deployment\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vscode_cache(min_age_days: int = 0) -> ScanResult:
    """VS Code cache, extension cache, and log files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\VSCode\Cache"),
        os.path.join(local, r"Microsoft\VSCode\CachedData"),
        os.path.join(local, r"Microsoft\VSCode\CachedExtensions"),
        os.path.join(local, r"Microsoft\VSCode\CachedExtensionVSIXs"),
        os.path.join(local, r"Microsoft\VSCode\Code Cache"),
        os.path.join(local, r"Microsoft\VSCode\logs"),
        os.path.join(appdata, r"Code\Cache"),
        os.path.join(appdata, r"Code\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_unity_cache(min_age_days: int = 0) -> ScanResult:
    """Unity Editor cache, library, and build cache folders."""
    result = ScanResult()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Unity\Editor\Cache"),
        os.path.join(local, r"Unity\Editor\logs"),
        os.path.join(local, r"Unity\Editor\Library"),
        os.path.join(local, r"Unity\Hub\logs"),
        os.path.join(local, r"Unity\Hub\Cache"),
        os.path.join(home, r"Unity\Projects"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_unreal_cache(min_age_days: int = 0) -> ScanResult:
    """Unreal Engine build, intermediate, and saved folders."""
    result = ScanResult()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"UnrealEngine\Engine\DerivedDataCache"),
        os.path.join(local, r"UnrealEngine\Projects"),
        os.path.join(home, r"Unreal Projects"),
        os.path.join(home, r"Documents\Unreal Projects"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_golang_cache(min_age_days: int = 0) -> ScanResult:
    """Go module proxy cache and build cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"go\pkg\mod\cache"),
        os.path.join(home, r"go\build"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), r"go-build"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_rust_cache(min_age_days: int = 0) -> ScanResult:
    """Rust cargo registry and target build cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".cargo\registry\cache"),
        os.path.join(home, r".cargo\registry\src"),
        os.path.join(home, r".cargo\target"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_npm_cache(min_age_days: int = 0) -> ScanResult:
    """npm cache in all locations — npm, pnpm, yarn global."""
    result = ScanResult()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"npm-cache"),
        os.path.join(local, r"npm-cache"),
        os.path.join(appdata, r"pnpm-store"),
        os.path.join(appdata, r"pnpm"),
        os.path.join(local, r"Yarn\Cache"),
        os.path.join(appdata, r"yarn\cache"),
        os.path.join(appdata, r"yarn\Data"),
        os.path.join(local, r"pnpm-store"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_pip_cache(min_age_days: int = 0) -> ScanResult:
    """pip download cache and wheel cache in all locations."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"pip\cache"),
        os.path.join(appdata, r"pip\cache"),
        os.path.join(local, r"pip\wheels"),
        os.path.join(appdata, r"pip\wheels"),
        os.path.join(local, r"pip\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_nuget_cache(min_age_days: int = 0) -> ScanResult:
    """NuGet global packages folder and HTTP cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(home, r".nuget\packages"),
        os.path.join(local, r"nuget\cache"),
        os.path.join(local, r"nuget\v3-cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_backup_files(min_age_days: int = 0) -> ScanResult:
    """Common backup file patterns: .bak, .tmp, ~, .old left behind after updates."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    temp = os.environ.get("TEMP", "")
    targets = [
        os.path.join(windir, r"*.bak"),
        os.path.join(windir, r"*.old"),
        os.path.join(windir, r"*.tmp"),
        os.path.join(windir, r"Installer\*.bak"),
        os.path.join(local, r"Microsoft\Windows\*.bak"),
        os.path.join(local, r"Microsoft\Windows\*.old"),
    ]
    for t in targets:
        dir_path, pattern = os.path.split(t)
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, pattern)):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    # Also scan Windows\Downloaded Program Files (orphaned installs)
    dpfs = os.path.join(windir, r"Downloaded Program Files")
    item = _make_item(dpfs, safety="caution", min_age_days=min_age_days)
    if item and item.size > 0:
        result.items.append(item)
        result.total_size += item.size
    return result


def scan_install_temp(min_age_days: int = 0) -> ScanResult:
    """Windows installation temp files and $INPLACE.~BT/~TT folders."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"$inplace.trinidad"),
        os.path.join(windir, r"$WINDOWS.~BT"),
        os.path.join(windir, r"$WINDOWS.~LS"),
        os.path.join(windir, r"DownloadedInstallations"),
        os.path.join(windir, r"Panther\*-ms"),
    ]
    for t in targets:
        if not os.path.isdir(t) and not os.path.isfile(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_search_index(min_age_days: int = 0) -> ScanResult:
    """Windows Search index database files and temp rebuilding data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Search\Data\Applications"),
        os.path.join(local, r"Microsoft\Search\Data\Temp"),
        os.path.join(local, r"Microsoft\Search\Data\UsageEvents"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_diagnostic_data(min_age_days: int = 0) -> ScanResult:
    """Windows Diagnostic Data Viewer staged data and queued data files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\DiagnosticDataViewer"),
        os.path.join(progdata, r"Microsoft\Windows\DiagnosticsDataViewer"),
        os.path.join(local, r"Microsoft\Windows\Feedback\FeedbackHub"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_powershell_logs(min_age_days: int = 0) -> ScanResult:
    """PowerShell transcription, module logging, and script execution logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(local, r"Microsoft\Windows\PowerShell\PSReadLine"),
        os.path.join(local, r"Microsoft\Windows\PowerShell\TranscriptLogs"),
        os.path.join(windir, r"System32\WindowsPowerShell\v1.0\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_group_policy_logs(min_age_days: int = 0) -> ScanResult:
    """Group Policy client-side extension logs and results."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(windir, r"Debug"),
        os.path.join(windir, r"Logs\GroupPolicy"),
        os.path.join(local, r"GroupPolicy\logs"),
        os.path.join(windir, r"System32\winevt\Logs\Microsoft-Windows-GroupPolicy%4Operational.evtx"),
    ]
    for t in targets:
        if not os.path.isfile(t):
            if not os.path.isdir(t):
                continue
        item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sysprep_logs(min_age_days: int = 0) -> ScanResult:
    """Sysprep (Windows generalization) logs and setup logs."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Panther"),
        os.path.join(windir, r"Logs\CBS\CBS.log"),
        os.path.join(windir, r"INF\setupapi.log"),
        os.path.join(windir, r"Panther\UnattendGC\setupact.log"),
        os.path.join(windir, r"Panther\UnattendGC\setuperr.log"),
    ]
    for t in targets:
        if not os.path.exists(t):
            continue
        if os.path.isfile(t):
            item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
        else:
            item = _make_item(t, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_windows_installer_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Installer download cache and patch removal queue."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\Installer"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        try:
            for entry in os.scandir(t):
                if entry.name.endswith('.msi') or entry.name.endswith('.msp'):
                    fpath = entry.path
                    try:
                        size = os.path.getsize(fpath)
                        if min_age_days > 0:
                            mtime = os.path.getmtime(fpath)
                            if (time.time() - mtime) < min_age_days * 86400:
                                continue
                        result.items.append(ScanItem(path=fpath, size=size, is_dir=False, safety="caution"))
                        result.total_size += size
                    except OSError:
                        pass
        except OSError:
            pass
    return result


def scan_wmi_logs(min_age_days: int = 0) -> ScanResult:
    """WMI (Windows Management Instrumentation) logs and permanent event consumers."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\wbem\Logs"),
        os.path.join(windir, r"System32\wbem\Repository\FS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_print_nightmare_logs(min_age_days: int = 0) -> ScanResult:
    """Print spooler transaction logs and spooling queue residuals."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\spool\PRINTERS"),
        os.path.join(windir, r"System32\spool\SERVERS"),
        os.path.join(windir, r"System32\spool\drivers"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_msi_logs(min_age_days: int = 0) -> ScanResult:
    r"""MSI installer verbose logs in Windows\Logs\MSI and Temp."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    temp = os.environ.get("TEMP", "")
    targets = [
        os.path.join(windir, r"Logs\MSI"),
        os.path.join(windir, r"Logs\WindowsUpdate"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        for f in glob.glob(os.path.join(t, "*.log")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
        for f in glob.glob(os.path.join(t, "*.etl")):
            item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_windows_backup_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Server Backup logs and System Protection shadow copy logs."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Logs\WindowsServerBackup"),
        os.path.join(windir, r"Logs\SIH"),
        os.path.join(windir, r"System32\Tasks\Microsoft\Windows\SystemRestore"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_appx_logs(min_age_days: int = 0) -> ScanResult:
    """AppX/MSIX package installation logs and staging data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\AppxPackages"),
        os.path.join(local, r"Microsoft\Windows\PackageManagement"),
        os.path.join(local, r"Microsoft\Windows\RemotePackages"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_defender_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Defender operational logs, scan logs, and threat remediation logs."""
    result = ScanResult()
    progdata = os.environ.get("PROGRAMDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(progdata, r"Microsoft\Windows Defender\Logs"),
        os.path.join(progdata, r"Microsoft\Windows Defender\Support"),
        os.path.join(local, r"Microsoft\Windows Defender\Scans\History"),
        os.path.join(local, r"Microsoft\Windows Defender\Quarantine\Items"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sfc_logs(min_age_days: int = 0) -> ScanResult:
    """System File Checker (sfc) and Deployment Image Servicing logs. NOT WinSxS internals."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Logs\CBS\CBS.log"),
        os.path.join(windir, r"Logs\DISM\dism.log"),
    ]
    for t in targets:
        if not os.path.exists(t):
            continue
        item = _make_item_with_age(t, safety="caution", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_recycle_bin_drive(min_age_days: int = 0) -> ScanResult:
    """Recycle bin for each fixed drive — empties all user-deleted files."""
    result = ScanResult()
    for drive in string.ascii_uppercase:
        rb = f"{drive}:\\$Recycle.Bin"
        if os.path.exists(rb):
            item = _make_item(rb, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_thumbnail_cache_central(min_age_days: int = 0) -> ScanResult:
    """Windows Explorer centralized thumbnail cache (thumbcache_*.db files)."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    thumb_dir = os.path.join(local, r"Microsoft\Windows\Explorer")
    for f in glob.glob(os.path.join(thumb_dir, "thumbcache_*.db")):
        item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    for f in glob.glob(os.path.join(thumb_dir, "iconcache_*.db")):
        item = _make_item_with_age(f, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Cloud Storage ──────────────────────────────────────────────────────────────

def scan_dropbox_cache(min_age_days: int = 0) -> ScanResult:
    """Dropbox cache, cache.db, and blob metadata — keeps account data intact."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Dropbox\cache"),
        os.path.join(local, r"Dropbox\blob_store"),
        os.path.join(local, r"Dropbox\instance1"),
        os.path.join(appdata, r"Dropbox\cache"),
        os.path.join(appdata, r"Dropbox\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
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


def scan_mega_cache(min_age_days: int = 0) -> ScanResult:
    """MEGAsync cache, temp files, and sync database."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"MEGA Limited\MEGAsync\temp"),
        os.path.join(local, r"MEGA Limited\MEGAsync\logs"),
        os.path.join(appdata, r"MEGAsync\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_pcloud_cache(min_age_days: int = 0) -> ScanResult:
    """pCloud cache and temp sync data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"pCloud\Cache"),
        os.path.join(local, r"pCloud\temp"),
        os.path.join(local, r"pCloud\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_icloud_cache(min_age_days: int = 0) -> ScanResult:
    """iCloud for Windows cache and download staging. NOT cookies or accounts."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Apple Computer\iCloud\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_box_cache(min_age_days: int = 0) -> ScanResult:
    """Box Drive cache and sync staging data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Box\Box\cache"),
        os.path.join(local, r"Box\Box\data"),
        os.path.join(local, r"Box\Box\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_tresorit_cache(min_age_days: int = 0) -> ScanResult:
    """Tresorit sync cache and temp files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Tresorit\Cache"),
        os.path.join(appdata, r"Tresorit\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_onedrive_cache(min_age_days: int = 0) -> ScanResult:
    """OneDrive known folder mask and sync conflict files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\OneDrive\logs"),
        os.path.join(local, r"Microsoft\OneDrive\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Virtualization & Containers ────────────────────────────────────────────────

def scan_docker_desktop_cache(min_age_days: int = 0) -> ScanResult:
    """Docker Desktop VM disk image, build cache, and container logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Docker\Wsl"),
        os.path.join(local, r"Docker\containers"),
        os.path.join(local, r"docker"),
        os.path.join(local, r"Kubernetes"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_virtualbox_cache(min_age_days: int = 0) -> ScanResult:
    """VirtualBox hard disk images (.vdi/.vhd), snapshots, and logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"VirtualBox"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"VirtualBox VMs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vmware_cache(min_age_days: int = 0) -> ScanResult:
    """VMware player/workstation/fusion VM virtual disks, snapshots, and logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"VMware"),
        os.path.join(local, r"VMware"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"Virtual Machines"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wsl2_cache(min_age_days: int = 0) -> ScanResult:
    """WSL2 ext4.vhdx virtual disk and WSL config/logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\CanonicalGroupLimited.UbuntuonWindows_*\LocalState"),
        os.path.join(local, r"Packages\CanonicalGroupLimited.Ubuntu_*\LocalState"),
        os.path.join(local, r"Microsoft\Windows\Containers"),
        os.path.join(local, r"Lxss"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_hyperv_cache(min_age_days: int = 0) -> ScanResult:
    """Hyper-V virtual machines, checkpoints (snapshots), and VM configuration files."""
    result = ScanResult()
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(progdata, r"Microsoft\Windows\Hyper-V"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"Documents\Hyper-V\Virtual Hard Disks"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_parallels_cache(min_age_days: int = 0) -> ScanResult:
    """Parallels virtual machines and shared applications cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Parallels"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"Parallels"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Media Production ───────────────────────────────────────────────────────────

def scan_obs_cache(min_age_days: int = 0) -> ScanResult:
    """OBS Studio recording temp, replay buffer, and encoder logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"OBS\logs"),
        os.path.join(appdata, r"obs-studio\logs"),
        os.path.join(local, r"OBS\crashreports"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_handbrake_cache(min_age_days: int = 0) -> ScanResult:
    """HandBrake encode log and preset import cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"HandBrake\logs"),
        os.path.join(appdata, r"HandBrake\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ffmpeg_cache(min_age_days: int = 0) -> ScanResult:
    """FFmpeg temp encoding output and stream dump files."""
    result = ScanResult()
    temp = os.environ.get("TEMP", "")
    targets = [
        os.path.join(temp, r"ffmpeg"),
        os.path.join(temp, r"MediaFire"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_audacity_cache(min_age_days: int = 0) -> ScanResult:
    """Audacity peak files, audacity temp dir, and waveform cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Audacity\peak"),
        os.path.join(local, r"Audacity\Temp"),
        os.path.join(appdata, r"Audacity\ audacity.cfg"),
    ]
    for t in targets:
        if not os.path.exists(t):
            continue
        if os.path.isfile(t):
            item = _make_item_with_age(t, safety="safe", min_age_days=min_age_days)
        else:
            item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_davinci_cache(min_age_days: int = 0) -> ScanResult:
    """DaVinci Resolve render cache, media cache, and database temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"DaVinciResolve\logs"),
        os.path.join(local, r"DaVinci Resolve\CacheClip"),
        os.path.join(local, r"DaVinci Resolve\OptimizedMedia"),
        os.path.join(local, r"DaVinci Resolve\Render Cache"),
        os.path.join(local, r"DaVinci Resolve\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_blender_cache(min_age_days: int = 0) -> ScanResult:
    """Blender render output temp and autosave files."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Blender Foundation\Blender\*\cache"),
        os.path.join(local, r"Blender Foundation\Blender\*\render"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_premiere_cache(min_age_days: int = 0) -> ScanResult:
    """Adobe Premiere Pro media cache, peak files, and auto-save."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Adobe\Common\Media Cache Files"),
        os.path.join(appdata, r"Adobe\Common\Peak Files"),
        os.path.join(local, r"Adobe\Common\Media Cache Files"),
        os.path.join(local, r"Adobe\Common\Peak Files"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_aftereffects_cache(min_age_days: int = 0) -> ScanResult:
    """Adobe After Effects disk cache and media cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Adobe\Common\Media Cache Files"),
        os.path.join(local, r"Adobe\Common\Media Cache Files"),
        os.path.join(local, r"Adobe\After Effects*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_photoshop_cache(min_age_days: int = 0) -> ScanResult:
    """Adobe Photoshop scratch disk, history, and plugins cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Adobe\Photoshop\*\Cache"),
        os.path.join(appdata, r"Adobe\Photoshop\*\Cache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_illustrator_cache(min_age_days: int = 0) -> ScanResult:
    """Adobe Illustrator cache and saved恢复了工作进度文件恢复."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Adobe\Illustrator*\Cache"),
        os.path.join(appdata, r"Adobe\Illustrator*\Temp"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_unity_hub_cache(min_age_days: int = 0) -> ScanResult:
    """Unity Hub cache, downloaded editor installs, and logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Unity Hub\logs"),
        os.path.join(local, r"Unity Hub\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_capture_one_cache(min_age_days: int = 0) -> ScanResult:
    """Capture One session cache, preview files, and catalog thumbnails."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Capture One\Cache"),
        os.path.join(appdata, r"Capture One\Logs"),
        os.path.join(local, r"Capture One\Thumbnails"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Development Tools ──────────────────────────────────────────────────────────

def scan_jetbrains_cache(min_age_days: int = 0) -> ScanResult:
    """JetBrains IDE caches, logs, and index data — all products."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\IntelliJIdea*\logs"),
        os.path.join(appdata, r"JetBrains\IntelliJIdea*\caches"),
        os.path.join(appdata, r"JetBrains\PyCharm*\logs"),
        os.path.join(appdata, r"JetBrains\PyCharm*\caches"),
        os.path.join(appdata, r"JetBrains\WebStorm*\logs"),
        os.path.join(appdata, r"JetBrains\WebStorm*\caches"),
        os.path.join(appdata, r"JetBrains\PhpStorm*\logs"),
        os.path.join(appdata, r"JetBrains\PhpStorm*\caches"),
        os.path.join(appdata, r"JetBrains\GoLand*\logs"),
        os.path.join(appdata, r"JetBrains\GoLand*\caches"),
        os.path.join(appdata, r"JetBrains\CLion*\logs"),
        os.path.join(appdata, r"JetBrains\CLion*\caches"),
        os.path.join(appdata, r"JetBrains\Rider*\logs"),
        os.path.join(appdata, r"JetBrains\Rider*\caches"),
        os.path.join(appdata, r"JetBrains\DataGrip*\logs"),
        os.path.join(appdata, r"JetBrains\DataGrip*\caches"),
        os.path.join(appdata, r"JetBrains\AndroidStudio*\logs"),
        os.path.join(appdata, r"JetBrains\AndroidStudio*\caches"),
        os.path.join(local, r"JetBrains\IntelliJIdea*"),
        os.path.join(local, r"JetBrains\PyCharm*"),
        os.path.join(local, r"JetBrains\WebStorm*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_eclipse_cache(min_age_days: int = 0) -> ScanResult:
    """Eclipse IDE logs, workspace metadata, and Maven local repo."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    home = os.path.expanduser("~")
    targets = [
        os.path.join(appdata, r"Eclipse"),
        os.path.join(home, r".eclipse"),
        os.path.join(home, r".m2\repository"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_netbeans_cache(min_age_days: int = 0) -> ScanResult:
    """NetBeans IDE var/log, cache, and temp folders."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"NetBeans\**\var\log"),
        os.path.join(appdata, r"NetBeans\**\cache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_git_lfs_cache(min_age_days: int = 0) -> ScanResult:
    """Git LFS local cache and objects store — DANGER: deleting removes actual repo files."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".git-lfs\objects"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="danger", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_cocoapods_cache(min_age_days: int = 0) -> ScanResult:
    """CocoaPods trunk specs repo and pod cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".cocoapods"),
        os.path.join(home, r"Library\Caches\CocoaPods"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ruby_gems_cache(min_age_days: int = 0) -> ScanResult:
    """RubyGems cache, bundler gems, and Gemfile.lock backups."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".gem\gems"),
        os.path.join(home, r".bundle"),
        os.path.join(home, r".gem\specifications"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_composer_cache(min_age_days: int = 0) -> ScanResult:
    """PHP Composer vendor cache and global packages."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".composer\vendor"),
        os.path.join(home, r".composer\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_bundler_cache(min_age_days: int = 0) -> ScanResult:
    """Bundler gem cache for Ruby projects."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".bundle\specifications"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_apt_cache(min_age_days: int = 0) -> ScanResult:
    """APT package cache (WSL Ubuntu/Debian) and apt lists."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".apt"),
        os.path.join(home, r"var\cache\apt"),
        os.path.join(home, r"var\lib\apt\lists"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Package Managers ────────────────────────────────────────────────────────────

def scan_chocolatey_cache(min_age_days: int = 0) -> ScanResult:
    """Chocolatey package download cache and lib/bad packages."""
    result = ScanResult()
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(progdata, r"chocolatey\cache"),
        os.path.join(progdata, r"chocolatey\lib-bad"),
        os.path.join(progdata, r"chocolatey\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_scoop_cache(min_age_days: int = 0) -> ScanResult:
    """Scoop bucket cache, downloads, and app versions."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"scoop\cache"),
        os.path.join(home, r"scoop\buckets"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_winget_cache(min_age_days: int = 0) -> ScanResult:
    """winget source cache and package metadata."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\winget\cache"),
        os.path.join(local, r"Microsoft\winget\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Game Launchers ─────────────────────────────────────────────────────────────

def scan_battlenet_cache(min_age_days: int = 0) -> ScanResult:
    """Battle.net cache, webcache, and agent logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Blizzard\Battle.net\Cache"),
        os.path.join(appdata, r"Blizzard\Battle.net\WebCache"),
        os.path.join(appdata, r"Blizzard\Battle.net\logs"),
        os.path.join(local, r"Blizzard\Battle.net\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_rockstar_cache(min_age_days: int = 0) -> ScanResult:
    """Rockstar Games Launcher cache, Social Club cache, and update downloads."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Rockstar Games\Launcher\logs"),
        os.path.join(appdata, r"Rockstar Games\Social Club"),
        os.path.join(local, r"Rockstar Games\Social Club"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_paradox_cache(min_age_days: int = 0) -> ScanResult:
    """Paradox Interactive launcher cache, mods, and save game staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Paradox Interactive\common\apps"),
        os.path.join(local, r"Paradox Interactive\mods"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_lutris_cache(min_age_days: int = 0) -> ScanResult:
    """Lutris wine prefix staging and runner install cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".lutris\wine"),
        os.path.join(home, r".lutris\runners"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_minedrive_cache(min_age_days: int = 0) -> ScanResult:
    """Minesweeper and casual game app caches."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Minesweeper"),
        os.path.join(local, r"Microsoft\YourPhone"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steamCMD_cache(min_age_days: int = 0) -> ScanResult:
    """steamcmd downloaded game content and workshop staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"steamcmd"),
        os.path.join(local, r"steam-console"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Communication Apps ─────────────────────────────────────────────────────────

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


# ── Productivity Apps ──────────────────────────────────────────────────────────

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


def scan_foobar_cache(min_age_days: int = 0) -> ScanResult:
    """foobar2000 cache, thumbs, and album art staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"foobar2000\cache"),
        os.path.join(appdata, r"id3"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More Browsers ──────────────────────────────────────────────────────────────

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


# ── More Game Caches ───────────────────────────────────────────────────────────

def scan_minecraft_cache(min_age_days: int = 0) -> ScanResult:
    """Minecraft (Java + Bedrock) shader cache, resource packs staging, and logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r".minecraft\logs"),
        os.path.join(appdata, r".minecraft\shaderpacks"),
        os.path.join(local, r"Packages\Microsoft.MinecraftUWP*"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_roblox_cache(min_age_days: int = 0) -> ScanResult:
    """Roblox player cache, shader cache, and logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Roblox\logs"),
        os.path.join(local, r"Roblox\_downloads"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_lol_cache(min_age_days: int = 0) -> ScanResult:
    """League of Legends replay cache, logs, and Riot crash reports."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Riot Games\League of Legends\logs"),
        os.path.join(appdata, r"Riot Games\League of Legends\replays"),
        os.path.join(local, r"Riot Games\League of Legends\Config"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_valorant_cache(min_age_days: int = 0) -> ScanResult:
    """Valorant game logs and Riot Vanguard logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Riot Games\Valheim"),
        os.path.join(appdata, r"Riot Games\Valorant\logs"),
        os.path.join(appdata, r"Riot Games\Signip\Saved\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_fortnite_cache(min_age_days: int = 0) -> ScanResult:
    """Fortnite Epic Games cache, D3D shader cache, and reports."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"FortniteGame\Saved\D3DCache"),
        os.path.join(local, r"Frostbite\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_csgo_cache(min_age_days: int = 0) -> ScanResult:
    """CS2/CS:GO shader cache, demo temp, and console logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Steam\steamapps\common\Counter-Strike Global Offensive\csgo\local\cfg"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_apex_cache(min_age_days: int = 0) -> ScanResult:
    """Apex Legends shader preload and Respawn log files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Respawn\Apex\logs"),
        os.path.join(local, r"Respawn\Apex\local"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_rust_game_cache(min_age_days: int = 0) -> ScanResult:
    """Rust game logs, crash dumps, and shader cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Facepunch Studios\Rust\logs"),
        os.path.join(appdata, r"Facepunch Studios\Rust\crash-reports"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_pubg_cache(min_age_days: int = 0) -> ScanResult:
    """PUBG lite/cache files and TslGame logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"TslGame\Saved\Logs"),
        os.path.join(local, r"TslGame\Saved\CrashReportClient"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_warcraft_cache(min_age_days: int = 0) -> ScanResult:
    """World of Warcraft, Diablo, Hearthstone logs and cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Blizzard\World of Warcraft\Logs"),
        os.path.join(appdata, r"Blizzard\Diablo III\Logs"),
        os.path.join(appdata, r"Blizzard\Hearthstone\Logs"),
        os.path.join(local, r"Blizzard\World of Warcraft\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_overwatch_cache(min_age_days: int = 0) -> ScanResult:
    """Overwatch 2 hero profile cache and Blizzard internal logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Blizzard\Overwatch\Logs"),
        os.path.join(appdata, r"Blizzard\Overwatch\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_eso_cache(min_age_days: int = 0) -> ScanResult:
    """Elder Scrolls Online logs, audio cache, and shader staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"ZeniMax Online\gamepadcache"),
        os.path.join(local, r"Documents\Elder Scrolls Online\live\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_path_of_exile_cache(min_age_days: int = 0) -> ScanResult:
    """Path of Exile log files and shader cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Grinding Gear Games\Path of Exile\logs"),
        os.path.join(appdata, r"Grinding Gear Games\Path of Exile\shaderCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── System & Windows ───────────────────────────────────────────────────────────

def scan_old_restore_points(min_age_days: int = 0) -> ScanResult:
    """Old System Restore snapshots and shadow storage."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\config\systemprofile\AppData\Local\Microsoft\Windows\WinX"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_iso_vhd_files(min_age_days: int = 0) -> ScanResult:
    """Orphaned .iso and .vhd files in common download folders."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"Downloads\*.iso"),
        os.path.join(home, r"Downloads\*.vhd"),
        os.path.join(home, r"Downloads\*.vhdx"),
    ]
    for t in targets:
        dir_path, pattern = os.path.split(t)
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, pattern)):
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_msp_patches(min_age_days: int = 0) -> ScanResult:
    """Orphaned Windows Installer .msp patch files."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Installer\*.msp"),
    ]
    for t in targets:
        dir_path, pattern = os.path.split(t)
        if not os.path.isdir(dir_path):
            continue
        for f in glob.glob(os.path.join(dir_path, pattern)):
            item = _make_item_with_age(f, safety="caution", min_age_days=min_age_days)
            if item:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_font_files_temp(min_age_days: int = 0) -> ScanResult:
    """Windows Font loader temp staging and fontinstaller temp files."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    temp = os.environ.get("TEMP", "")
    targets = [
        os.path.join(windir, r"ServiceProfiles\LocalService\AppData\Local\FontDrivers"),
        os.path.join(temp, r"Font*"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_language_packs(min_age_days: int = 0) -> ScanResult:
    """Windows language pack cab files and MUI temp cache."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\MUI"),
        os.path.join(windir, r"System32\en-US"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_optional_features(min_age_days: int = 0) -> ScanResult:
    """Windows optional features manifests backup (danger) and install temp (safe)."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        (os.path.join(windir, r"WinSxS\ManifestBackup"), "danger"),
        (os.path.join(windir, r"WinSxS\InstallTemp"), "safe"),
    ]
    for t, safety in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety=safety, min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_printer_driver_cache(min_age_days: int = 0) -> ScanResult:
    """Orphaned printer driver files and print capture archives."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\spool\drivers"),
        os.path.join(windir, r"System32\spool\PRINTERS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_dns_cache(min_age_days: int = 0) -> ScanResult:
    """Flush DNS resolver cache — safe operation, no file deletion needed."""
    result = ScanResult()
    return result


def scan_network_adapter_cache(min_age_days: int = 0) -> ScanResult:
    """Network-level DNS and NetBIOS cached entries."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\drivers\etc\hosts"),
    ]
    for t in targets:
        if not os.path.isfile(t):
            continue
        item = _make_item_with_age(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── IIS & SQL Server ───────────────────────────────────────────────────────────

def scan_iis_logs(min_age_days: int = 0) -> ScanResult:
    """IIS HTTP logs, Failed Request logs, and IIS Express logs."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\LogFiles\HTTPERR"),
        os.path.join(windir, r"System32\inetsrv\LogFiles"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"Documents\IISExpress"),
        os.path.join(os.environ.get("USERPROFILE", ""), r"Documents\My Web Sites"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sql_server_logs(min_age_days: int = 0) -> ScanResult:
    """SQL Server error logs, agent logs, and FTData catalog files."""
    result = ScanResult()
    targets = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), r"Microsoft SQL Server\MSSQL*\LOG"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), r"Microsoft SQL Server\MSSQL*\MSSQL\DATA"),
        os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), r"Microsoft SQL Server"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_mysql_logs(min_age_days: int = 0) -> ScanResult:
    """MySQL general query log, slow query log, and error log files."""
    result = ScanResult()
    targets = [
        os.path.join(os.environ.get("PROGRAMFILES", ""), r"MySQL\MySQL Server*\Data"),
        os.path.join(os.environ.get("PROGRAMFILES", ""), r"MySQL\MySQL Server*\logs"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_postgres_logs(min_age_days: int = 0) -> ScanResult:
    """PostgreSQL pg_log and pg_xlog archive files."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"AppData\Local\PostgreSQL\logs"),
        os.path.join(home, r"AppData\Roaming\PostgreSQL\pg_log"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Backup & Security Software ─────────────────────────────────────────────────

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


def scan_old_av_quarantine(min_age_days: int = 0) -> ScanResult:
    """Old antivirus quarantine files from expired/uninstalled AV products."""
    result = ScanResult()
    progdata = os.environ.get("PROGRAMDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(progdata, r"Avast\ quarantine"),
        os.path.join(progdata, r"AVG\ quarantine"),
        os.path.join(progdata, r"Malwarebytes\ quarantine"),
        os.path.join(local, r"Microsoft Windows Defender\Quarantine"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Email Clients ──────────────────────────────────────────────────────────────

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


# ── Autodesk & BIM ─────────────────────────────────────────────────────────────

def scan_autocad_cache(min_age_days: int = 0) -> ScanResult:
    """AutoCAD plot logs, cache, and error reporting files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Autodesk\AutoCAD\*\R*\Cache"),
        os.path.join(local, r"Autodesk\AutoCAD\*\R*\Temp"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_revitable_cache(min_age_days: int = 0) -> ScanResult:
    """Revit family cache, Dynamo cache, and BIM 360 sync logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Autodesk\Revit\Autodesk Revit*\FamilyCache"),
        os.path.join(appdata, r"Autodesk\Revit\Autodesk Revit*\Logs"),
        os.path.join(local, r"Autodesk\Revit\Autodesk Revit*\UI\Cache"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_sketchup_cache(min_age_days: int = 0) -> ScanResult:
    """SketchUp shadow cache, style caches, and import logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"SketchUp\SketchUp*\Logs"),
        os.path.join(local, r"SketchUp\SketchUp*\SketchUp"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_blender_full_cache(min_age_days: int = 0) -> ScanResult:
    """Blender vertex cache, render stamp, and geometry nodes staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Blender Foundation\Blender\*\cache"),
        os.path.join(local, r"Blender Foundation\Blender\*\render"),
        os.path.join(local, r"Blender Foundation\Blender\*\tmp"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


# ── CD/DVD Images ─────────────────────────────────────────────────────────────

def scan_virtual_drives(min_age_days: int = 0) -> ScanResult:
    """Daemon Tools, Alcohol 120%, and WinCDEmu virtual drive images and cfg files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"DaemonBuilder\ImageCache"),
        os.path.join(appdata, r"DAEMON Tools Lite\ImageCache"),
        os.path.join(local, r"WinCDEmu"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── USB & Portable Apps ────────────────────────────────────────────────────────

def scan_usb_shadow_copies(min_age_days: int = 0) -> ScanResult:
    """USB device shadow copies and ReadyBoost cache."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\config\systemprofile\AppData\Local\Low\Microsoft\CryptnetUrlCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Microsoft 365 & SharePoint ────────────────────────────────────────────────

def scan_sharepoint_cache(min_age_days: int = 0) -> ScanResult:
    """SharePoint/OneDrive sync client Known folder mask and local cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Office\OfficeFileCache"),
        os.path.join(local, r"Microsoft\Office\OfficeFileCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_onedrive_full_cache(min_age_days: int = 0) -> ScanResult:
    """OneDrive sync conflict files, redirected folder cache, and thumbnail staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\OneDrive\logs"),
        os.path.join(local, r"Microsoft\OneDrive\cache"),
        os.path.join(local, r"Microsoft\OneDrive\ACSBackup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More Network & Sysinternals ────────────────────────────────────────────────

def scan_sysinternals_logs(min_age_days: int = 0) -> ScanResult:
    """Sysinternals (Procmon, PsExec, etc.) log and database files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Sysinternals"),
        os.path.join(appdata, r"Sysinternals"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_network_debug_logs(min_age_days: int = 0) -> ScanResult:
    """Network diagnostic ETL traces and packet capture log files."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(windir, r"System32\LogFiles\Nettettl"),
        os.path.join(local, r"Microsoft\Windows\Network Diagnostics"),
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


def scan_wsl_installer_cache(min_age_days: int = 0) -> ScanResult:
    """WSL distro installer staging and downloaded package cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\CanonicalGroupLimited.WSL_*\LocalState"),
        os.path.join(local, r"Packages\CanonicalGroupLimited.UbuntuonWindows_*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_powershell_modules_cache(min_age_days: int = 0) -> ScanResult:
    """PowerShell module telemetry, PSModulePath download cache, and transcript logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"PowerShell\DownloadedModules"),
        os.path.join(local, r"Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt"),
    ]
    for t in targets:
        if not os.path.exists(t):
            continue
        if os.path.isfile(t):
            item = _make_item_with_age(t, safety="safe", min_age_days=min_age_days)
        else:
            item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_nvidia_geforce_cache(min_age_days: int = 0) -> ScanResult:
    """NVIDIA GeForce Experience logs, driver download cache, and screenshot folder."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"NVIDIA\GeForce Experience\logs"),
        os.path.join(local, r"NVIDIA\GeForce Experience\logs"),
        os.path.join(local, r"NVIDIA\GeForce Experience\UpdateTemp"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_amd_radeon_cache(min_age_days: int = 0) -> ScanResult:
    """AMD Radeon Software logs, driver cache, and relodge temp files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"AMD\AGESA\logs"),
        os.path.join(local, r"AMD\ Radeon\Logs"),
        os.path.join(local, r"AMD\CN"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_intel_graphics_cache(min_age_days: int = 0) -> ScanResult:
    """Intel Graphics Command Center cache, driver logs, and shader cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Intel\Graphics\Logs"),
        os.path.join(local, r"Intel\Graphics\Logs"),
        os.path.join(local, r"Intel\Graphics\ShaderCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steam_full_cache(min_age_days: int = 0) -> ScanResult:
    """Steam download manifest cache, workshop staging, and shader pre-caching."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Programs\Steam\logs"),
        os.path.join(local, r"Programs\Steam\htmlcache"),
        os.path.join(local, r"Programs\Steam\shadercache"),
        os.path.join(local, r"Programs\Steam\downloads"),
        os.path.join(appdata, r"Steam\htmlcache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_xbox_live_cache(min_age_days: int = 0) -> ScanResult:
    """Xbox Live device info cache, achievements staging, and gaming services logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\XboxLiveDeviceInfo"),
        os.path.join(local, r"MicrosoftGameBar\logs"),
        os.path.join(progdata, r"XboxLiveDeviceInfo"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_insider_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Insider feedback hub diagnostic bundles and telemetry staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\FeedbackHub\data"),
        os.path.join(local, r"Microsoft\Windows\FeedbackHub\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_driver_store(min_age_days: int = 0) -> ScanResult:
    """Windows Driver Store backup .inf files for uninstalled drivers (DANGER — can break hardware)."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\DriverStore\FileRepository"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="danger", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_winSxS_temp(min_age_days: int = 0) -> ScanResult:
    """WinSxS pending file rename operations and install temp."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"WinSxS\InstallTemp"),
        os.path.join(windir, r"WinSxS\Temp"),
        os.path.join(windir, r"WinSxS\pisi.graph"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_userprofile_temp(min_age_days: int = 0) -> ScanResult:
    r"""Per-user profile temp files scattered across AppData\Local\Temp."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    temp = os.environ.get("TEMP", "")
    targets = [
        os.path.join(local, r"Temp"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        if t == temp:
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_downloads_folder_old(min_age_days: int = 0) -> ScanResult:
    """Old files in the Downloads folder (recursive) older than min_age_days."""
    result = ScanResult()
    home = os.path.expanduser("~")
    dl = os.path.join(home, "Downloads")
    if not os.path.isdir(dl):
        return result
    for entry in os.scandir(dl):
        try:
            if entry.is_file():
                if min_age_days > 0:
                    mtime = os.path.getmtime(entry.path)
                    if (time.time() - mtime) < min_age_days * 86400:
                        continue
                size = os.path.getsize(entry.path)
                result.items.append(ScanItem(path=entry.path, size=size, is_dir=False, safety="caution"))
                result.total_size += size
        except OSError:
            pass
    return result


# ── RDP & Remote Access ─────────────────────────────────────────────────────────

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


# ── VPN Clients ─────────────────────────────────────────────────────────────────

def scan_openvpn_cache(min_age_days: int = 0) -> ScanResult:
    """OpenVPN client logs, script temp, and unifiedpushtoken cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"OpenVPN"),
        os.path.join(appdata, r"OpenVPN Connect"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wireguard_cache(min_age_days: int = 0) -> ScanResult:
    """WireGuard interface logs and adapter state cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"WireGuard"),
        os.path.join(local, r"WireGuard"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_nordvpn_cache(min_age_days: int = 0) -> ScanResult:
    """NordVPN connection logs and settings cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"NordVPN"),
        os.path.join(appdata, r"Roaming\ClientConfig"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_expressvpn_cache(min_age_days: int = 0) -> ScanResult:
    """ExpressVPN diagnostic logs and split-tunneling config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"ExpressVPN"),
        os.path.join(appdata, r"ExpressVPN Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Version Control Tools ────────────────────────────────────────────────────────

def scan_sourcetree_cache(min_age_days: int = 0) -> ScanResult:
    """Atlassian SourceTree logs, SSH keys, and Mercurial cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Atlassian\SourceTree"),
        os.path.join(appdata, r"Atlassian\SourceTree"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gitkraken_cache(min_age_days: int = 0) -> ScanResult:
    """GitKraken logs, keychain cache, and Git analytics data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"GitKraken"),
        os.path.join(local, r"GitKraken"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_fork_cache(min_age_days: int = 0) -> ScanResult:
    """Fork git client logs and diff cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Fork"),
        os.path.join(appdata, r"ForkLogs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_smartgit_cache(min_age_days: int = 0) -> ScanResult:
    """SmartGit logs and repository metadata cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"SmartGit"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_mercurial_cache(min_age_days: int = 0) -> ScanResult:
    """Mercurial revlog cache and bundle staging area."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".hg"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_subversion_cache(min_age_days: int = 0) -> ScanResult:
    """Subversion (SVN) working copy pristine text and property cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".subversion"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More Code Editors ──────────────────────────────────────────────────────────

def scan_sublime_cache(min_age_days: int = 0) -> ScanResult:
    """Sublime Text cache, index data, and syntax cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Sublime Text\Cache"),
        os.path.join(appdata, r"Sublime Text\Index"),
        os.path.join(appdata, r"Sublime Text\Log"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_atom_cache(min_age_days: int = 0) -> ScanResult:
    """Atom editor cache, node_modules, and compile cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Atom\Cache"),
        os.path.join(appdata, r"Atom\blob_storage"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_brackets_cache(min_age_days: int = 0) -> ScanResult:
    """Adobe Brackets extract folder, cache, and extension temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Brackets\ext"),
        os.path.join(appdata, r"Brackets\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vscodium_cache(min_age_days: int = 0) -> ScanResult:
    """VSCodium cache, extensions, and log files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"VSCodium\UserData"),
        os.path.join(local, r"VSCodium"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_novatrons_cache(min_age_days: int = 0) -> ScanResult:
    """Nova launcher cache and extension data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Novatrons"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_qt_creator_cache(min_age_days: int = 0) -> ScanResult:
    """Qt Creator analysis cache, autocomplete data, and build logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"QtProject\QtCreator"),
        os.path.join(appdata, r"QtProject\QtCreator"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_lazarus_cache(min_age_days: int = 0) -> ScanResult:
    """Lazarus IDE compiler temp and objectPAL cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Lazarus"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_codeblocks_cache(min_age_days: int = 0) -> ScanResult:
    """Code::Blocks default and global variable paths cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"CodeBlocks\default"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_npp_cache(min_age_days: int = 0) -> ScanResult:
    """Notepad++ backup, session, and plugin config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Notepad++\backup"),
        os.path.join(appdata, r"Notepad++\plugins\config"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vim_cache(min_age_days: int = 0) -> ScanResult:
    """Vim undo files, swap files, and viminfo (safe to clean)."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".vim\undo"),
        os.path.join(home, r".vim\swap"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_emacs_cache(min_age_days: int = 0) -> ScanResult:
    """Emacs auto-save, backup, and elpa package cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".emacs.d\auto-save-list"),
        os.path.join(home, r".emacs.d\elpa"),
        os.path.join(home, r".emacs.d\var"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_zed_cache(min_age_days: int = 0) -> ScanResult:
    """Zed editor logs, LSP cache, and extension data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Zed"),
        os.path.join(appdata, r"Zed\rustup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Database Tools ───────────────────────────────────────────────────────────────

def scan_dbeaver_cache(min_age_days: int = 0) -> ScanResult:
    """DBeaver workspace cache, SQL scripts, and driver cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"DBeaver"),
        os.path.join(appdata, r"DBeaverData"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_heidisql_cache(min_age_days: int = 0) -> ScanResult:
    """HeidiSQL session logs and query history cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"HeidiSQL"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_workbench_cache(min_age_days: int = 0) -> ScanResult:
    """MySQL Workbench connection history and SQL editor cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"MySQL\Workbench"),
        os.path.join(local, r"MySQL\Workbench"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_navicat_cache(min_age_days: int = 0) -> ScanResult:
    """Navicat Premium connection settings backup and query result cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Navicat"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sqlitebrowser_cache(min_age_days: int = 0) -> ScanResult:
    """SQLiteBrowser recent database history and export cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"SQLiteBrowser"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Cloud CLIs ─────────────────────────────────────────────────────────────────

def scan_aws_cli_cache(min_age_days: int = 0) -> ScanResult:
    """AWS CLI cache, config, and SSM session cache. NOT credentials file."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".aws\cli\cache"),
        os.path.join(home, r".aws\sso\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_azure_cli_cache(min_age_days: int = 0) -> ScanResult:
    """Azure CLI access token cache, cloud shell, and arm cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".azure"),
        os.path.join(home, r".cloudshell"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gcp_sdk_cache(min_age_days: int = 0) -> ScanResult:
    """Google Cloud SDK credentials, bq cache, and gcloud config."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"AppData\Roaming\gcloud"),
        os.path.join(home, r"AppData\Local\gcloud"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_kubernetes_cache(min_age_days: int = 0) -> ScanResult:
    """kubectl config, Helm cache, and K9s database."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".kube\cache"),
        os.path.join(home, r".helm"),
        os.path.join(home, r".config\k9s"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_minikube_cache(min_age_days: int = 0) -> ScanResult:
    """minikube cluster data, addons config, and cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".minikube"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_kind_cache(min_age_days: int = 0) -> ScanResult:
    """kind (Kubernetes in Docker) cluster config and image tar cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".kind"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_terraform_cache(min_age_days: int = 0) -> ScanResult:
    """Terraform provider plugin cache, .terraform directory, and plan cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".terraform.d\plugin-cache"),
        os.path.join(home, r".terraform\providers"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_pulumi_cache(min_age_days: int = 0) -> ScanResult:
    """Pulumi stack logs and resource escape hatch cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Pulumi"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ansible_cache(min_age_days: int = 0) -> ScanResult:
    """Ansible vault password file, collections cache, and role cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".ansible\collections"),
        os.path.join(home, r".ansible\tmp"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_packer_cache(min_age_days: int = 0) -> ScanResult:
    """Packer plugin cache and output artifact staging."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".packer.d\plugin-cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Password Managers ────────────────────────────────────────────────────────────

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


# ── More Games ─────────────────────────────────────────────────────────────────

def scan_destiny2_cache(min_age_days: int = 0) -> ScanResult:
    """Destiny 2 shader preload, logs, and Bungie.net manifest cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Bungie\DestinyActivityFeed"),
        os.path.join(local, r"Bungie\Destiny2"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_warframe_cache(min_age_days: int = 0) -> ScanResult:
    """Warframe shader cache, relay logs, and update staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Warframe"),
        os.path.join(appdata, r"Digital Extremes\Warframe"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_beamng_cache(min_age_days: int = 0) -> ScanResult:
    """BeamNG.drive logs, replay cache, and crash reports."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"BeamNG\logs"),
        os.path.join(local, r"BeamNG.drive"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_forza_cache(min_age_days: int = 0) -> ScanResult:
    """Forza Horizon / Motorsport logs, clips, and capture gallery."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"ForzaHorizon*"),
        os.path.join(local, r"ForzaHorizon*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_steamvr_cache(min_age_days: int = 0) -> ScanResult:
    """SteamVR logs, compositor cache, and tracked device config."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"SteamVR"),
        os.path.join(appdata, r"Steam\config"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_oculus_cache(min_age_days: int = 0) -> ScanResult:
    """Meta/Oculus home environment cache and manifest staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Software\Microsoft\Windows\CurrentVersion\Shell\Oculus"),
        os.path.join(local, r"Oculus"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gta_v_cache(min_age_days: int = 0) -> ScanResult:
    """GTA V shader cache, social club cache, and crash handler logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Rockstar Games\GTA V"),
        os.path.join(local, r"Rockstar Games\GTA V"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_arma_cache(min_age_days: int = 0) -> ScanResult:
    """Arma 3 profile logs, mission temp, and BattlEye filter cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Arma 3"),
        os.path.join(local, r"Arma 3"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Streaming ──────────────────────────────────────────────────────────────────

def scan_spotify_full_cache(min_age_days: int = 0) -> ScanResult:
    """Spotify full cache: data, thumbs, users — keeps login/settings."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Spotify\Data"),
        os.path.join(local, r"Spotify\Cache"),
        os.path.join(local, r"Spotify\thumbs"),
        os.path.join(local, r"Spotify\Users"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_tidal_cache(min_age_days: int = 0) -> ScanResult:
    """Tidal music cache and thumbnail staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Tidal"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_deezer_cache(min_age_days: int = 0) -> ScanResult:
    """Deezer music cache and waveform staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Deezer"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_qobuz_cache(min_age_days: int = 0) -> ScanResult:
    """Qobuz download cache and offline tracks."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Qobuz"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Video Editors & Screen Recording ────────────────────────────────────────────

def scan_vegas_cache(min_age_days: int = 0) -> ScanResult:
    """Vegas Pro autosave, GPU render cache, and proxy files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"VEGASTemp"),
        os.path.join(appdata, r"VEGAS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_filmora_cache(min_age_days: int = 0) -> ScanResult:
    """Filmora9/10 preview cache and export temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Wondershare\Filmora*"),
        os.path.join(appdata, r"Wondershare\Filmora*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_camtasia_cache(min_age_days: int = 0) -> ScanResult:
    """Camtasia recording cache and editor temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Techsmith\CamtasiaStudio"),
        os.path.join(appdata, r"Techsmith\Camtasia"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sharex_cache(min_age_days: int = 0) -> ScanResult:
    """ShareX screenshot history, image history, and upload logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"ShareX"),
        os.path.join(appdata, r"ShareX\Screenshots"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_lightshot_cache(min_age_days: int = 0) -> ScanResult:
    """Lightshot saved screenshots and upload history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Lightshot"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_greenshot_cache(min_age_days: int = 0) -> ScanResult:
    """Greenshot screenshot output and plugin cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Greenshot"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_snagit_cache(min_age_days: int = 0) -> ScanResult:
    """TechSmith Snagit editor cache and captured library thumbnails."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"TechSmith\Snagit"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Audio Plugins & VST ─────────────────────────────────────────────────────────

def scan_vst_cache(min_age_days: int = 0) -> ScanResult:
    """VST plugin preset cache, VST3 cache, and CLAP cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Common Files\VST3"),
        os.path.join(local, r"Common Files\VST3"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_kontakt_cache(min_age_days: int = 0) -> ScanResult:
    """Kontakt sample library database cache and preload cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Native Instruments\Service Center"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_reaper_cache(min_age_days: int = 0) -> ScanResult:
    """REAPER backup files, peak data, and waveform cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"REAPER"),
        os.path.join(local, r"REAPER"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_flstudio_cache(min_age_days: int = 0) -> ScanResult:
    """FL Studio slicex, directwave, and autosave cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Image-Line\FL Studio\FL64"),
        os.path.join(appdata, r"Image-Line\FL Studio"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ableton_cache(min_age_days: int = 0) -> ScanResult:
    """Ableton Live audio engine temp and clip deformation cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Ableton"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_logic_pro_cache(min_age_days: int = 0) -> ScanResult:
    """Logic Pro for Windows (if installed) media cache and project backups."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Logic Pro"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_cubase_cache(min_age_days: int = 0) -> ScanResult:
    """Steinberg Cubase VST3 plugin cache and project archive staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Steinberg"),
        os.path.join(local, r"Steinberg"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Disk & System Monitoring Tools ──────────────────────────────────────────────

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


# ── OCR & AI Tools ─────────────────────────────────────────────────────────────

def scan_tesseract_cache(min_age_days: int = 0) -> ScanResult:
    """Tesseract OCR trained data and tessdata cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Tesseract"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_whisper_cache(min_age_days: int = 0) -> ScanResult:
    """Whisper.cpp model cache and transcription temp files."""
    result = ScanResult()
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(home, r".whisper"),
        os.path.join(local, r"whisper"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_curl_cfgs_cache(min_age_days: int = 0) -> ScanResult:
    """curl config (~/.curlrc) and cookie jar cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".curlrc"),
    ]
    for t in targets:
        if not os.path.isfile(t):
            continue
        item = _make_item_with_age(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wget_cache(min_age_days: int = 0) -> ScanResult:
    """wgetrc config file and HSTS database cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".wgetrc"),
        os.path.join(home, r".wget-hsts"),
    ]
    for t in targets:
        if not os.path.isfile(t):
            continue
        item = _make_item_with_age(t, safety="safe", min_age_days=min_age_days)
        if item:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_maven_repo_cache(min_age_days: int = 0) -> ScanResult:
    """Apache Maven local repository (~/.m2/repository)."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".m2\repository"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gradle_caches_cache(min_age_days: int = 0) -> ScanResult:
    """Gradle daemon logs, wrapper distributions, and build cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".gradle\caches"),
        os.path.join(home, r".gradle\daemon"),
        os.path.join(home, r".gradle\wrapper"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_nvm_caches(min_age_days: int = 0) -> ScanResult:
    """nvm (Node Version Manager) downloaded node versions and cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"nvm"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_pyenv_cache(min_age_days: int = 0) -> ScanResult:
    """pyenv Python builds and cache of downloaded Python versions."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".pyenv\cache"),
        os.path.join(home, r".pyenv\versions"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_venv_cache(min_age_days: int = 0) -> ScanResult:
    """Python virtualenv src and egg-link source cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".venv"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wineprefix_cache(min_age_days: int = 0) -> ScanResult:
    """Wine/PlayOnLinux prefix cache and Winetricks download staging."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".wine"),
        os.path.join(home, r".PlayOnLinux"),
        os.path.join(home, r".winetricks"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_lutris_runs_cache(min_age_days: int = 0) -> ScanResult:
    """Lutris wine runners, DXVK cache, and runtime environment."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".lutris\runners"),
        os.path.join(home, r".lutris\wine"),
        os.path.join(home, r".local\share\lutris"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steam_proton_cache(min_age_days: int = 0) -> ScanResult:
    """Steam Proton (Linux game compatibility layer) prefix cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"steamapps\compatdata"),
        os.path.join(local, r"Steam\steamapps\compatdata"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_nvidia_display_cache(min_age_days: int = 0) -> ScanResult:
    """NVIDIA Display Driver container, DRS database, and telemetry cache."""
    result = ScanResult()
    progdata = os.environ.get("PROGRAMDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(progdata, r"NVIDIA\Display.NvCate"),
        os.path.join(local, r"NVIDIA\DXCache"),
        os.path.join(local, r"NVIDIA\GLCache"),
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


def scan_bazaar_cache(min_age_days: int = 0) -> ScanResult:
    """Bazaar version control shared repository and branch cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".bazaar"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_darcs_cache(min_age_days: int = 0) -> ScanResult:
    """Darcs version control pristine and patches cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".darcs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_perforce_cache(min_age_days: int = 0) -> ScanResult:
    """Perforce Helix Core p4cache and workspace metadata."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"P4"),
        os.path.join(appdata, r"P4"),
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


def scan_logitech_g_hub_cache(min_age_days: int = 0) -> ScanResult:
    """Logitech G HUB profiles, LED sync cache, and game detection logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"LGHUB"),
        os.path.join(local, r"LGHUB"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steam_cloud_sync_cache(min_age_days: int = 0) -> ScanResult:
    """Steam Cloud sync conflict backups and pending upload staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"steamapps\backups"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vcredist_cache(min_age_days: int = 0) -> ScanResult:
    """Visual C++ Redistributable merge modules and manifest cache."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Installer\VC_redist"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_net_framework_cache(min_age_days: int = 0) -> ScanResult:
    """.NET Framework download cache and NGEN assembly binary cache."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"Microsoft.NET\Framework\*\NGEN"),
        os.path.join(windir, r"Microsoft.NET\Framework64\*\NGEN"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_net_sdk_cache(min_age_days: int = 0) -> ScanResult:
    """.NET SDK NuGet package cache and build MSBuild task inputs cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".nuget\packages"),
        os.path.join(home, r"\.dotnet"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_directx_shader_cache(min_age_days: int = 0) -> ScanResult:
    """DirectX 11/12 shader cache, D3DSCache, and AMD/NVIDIA/Intel shader disks."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"D3DSCache"),
        os.path.join(local, r"NVIDIA\DXCache"),
        os.path.join(local, r"NVIDIA\GLCache"),
        os.path.join(local, r"AMD\DXCache"),
        os.path.join(local, r"AMD\VulkanCache"),
        os.path.join(local, r"Intel\GraphicsCache"),
        os.path.join(local, r"Intel\GLCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_inbox_apps_cache(min_age_days: int = 0) -> ScanResult:
    """Inbox Windows app data (Calculator, Photos, Mail) temp and sync cache. NOT cookies/history."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Local\Microsoft\Windows\IEDebar"),
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


def scan_windows_insider_preview_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Insider flight data, build staging, and reset packages."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"TEMP\WindowsInsider.Upgrade"),
        os.path.join(local, r"Microsoft\Windows\WindowsInsider"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_recovery_env_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Recovery Environment (WinRE) diagnostics and ReAgentc log staging."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\LogFiles\SM"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_photoscan_cache(min_age_days: int = 0) -> ScanResult:
    """Microsoft Photos scan/3D objects cache and video editing temp."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.Windows.Photos*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_maps_offline_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Maps offline map tiles and navigation history cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.BingMaps*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_nuget_global_packages(min_age_days: int = 0) -> ScanResult:
    """NuGet global packages folder with all cached .nupkg files."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".nuget\packages"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wu_history_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Update download history and temporary rollback files."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"SoftwareDistribution\Download"),
        os.path.join(windir, r"SoftwareDistribution\Backup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_delivery_optimization_do(min_age_days: int = 0) -> ScanResult:
    """Delivery Optimization download session state and blob container cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\DeliveryOptimization\Cache"),
        os.path.join(local, r"Microsoft\Windows\DeliveryOptimization\Logs"),
        os.path.join(progdata, r"Microsoft\Windows\DeliveryOptimization\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More Streaming & Media ───────────────────────────────────────────────────────

def scan_peertube_cache(min_age_days: int = 0) -> ScanResult:
    """PeerTube cache and download staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"PeerTube")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_plex_cache(min_age_days: int = 0) -> ScanResult:
    """Plex Media Server transcoding cache and thumbnail staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Plex Media Server"),
        os.path.join(appdata, r"Plex"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_jellyfin_cache(min_age_days: int = 0) -> ScanResult:
    """Jellyfin transcoding cache, metadata, and plugin data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Jellyfin\cache"),
        os.path.join(local, r"Jellyfin\metadata"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_emby_cache(min_age_days: int = 0) -> ScanResult:
    """Emby Server transcoding cache and dashboard temp."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"EmbyServer\cache"),
        os.path.join(local, r"EmbyServer\transcoding"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_kodi_cache(min_age_days: int = 0) -> ScanResult:
    """Kodi texture cache, thumbnails, and log files."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Kodi\cache"),
        os.path.join(appdata, r"Kodi\thumbnails"),
        os.path.join(local, r"Kodi"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vlc_cache(min_age_days: int = 0) -> ScanResult:
    """VLC media player cache, interface extensions, and recent media history."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"vlc"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_mpc_cache(min_age_days: int = 0) -> ScanResult:
    """MPC-HC / MPC-BE cache and shader settings."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"MPC")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_potplayer_cache(min_age_days: int = 0) -> ScanResult:
    """PotPlayer cache, thumbnail previews, and broadcast cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Daum")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_mpv_cache(min_age_days: int = 0) -> ScanResult:
    """mpv player watch later, settings, and script opts cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"mpv"),
        os.path.join(local, r"mpv"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_infuse_cache(min_age_days: int = 0) -> ScanResult:
    """Infuse video player metadata cache and stream session data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Firecore")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_stremio_cache_full(min_age_days: int = 0) -> ScanResult:
    """Stremio torrent cache, player data, and add-on config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Stremio"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More Communication ─────────────────────────────────────────────────────────

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


# ── Game Launchers (More) ─────────────────────────────────────────────────────

def scan_epic_games_cache(min_age_days: int = 0) -> ScanResult:
    """Epic Games Store shader compiler staging and manifest data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"EpicGamesLauncher\Data\Portal\Cache"),
        os.path.join(local, r"EpicGamesLauncher\Saved\logs"),
        os.path.join(local, r"EpicGamesLauncher\Saved\webcache"),
        os.path.join(appdata, r"Epic\EpicGamesLauncher\Data\Manifests"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gog_galaxy2_cache(min_age_days: int = 0) -> ScanResult:
    """GOG Galaxy 2.0 game manager cache, web cache, and sync data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"GOG.com\Galaxy\Cache"),
        os.path.join(appdata, r"GOG.com\Galaxy\WebCache"),
        os.path.join(appdata, r"GOG.com\Galaxy\logs"),
        os.path.join(local, r"GOG.com\Galaxy\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_humble_choice_cache(min_age_days: int = 0) -> ScanResult:
    """Humble App download cache, installer staging, and choice metadata."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Humble Bundle\Humble App\Cache"),
        os.path.join(local, r"Humble Bundle\Humble App\logs"),
        os.path.join(appdata, r"HumbleBundle\Humble App\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_itch_app_cache(min_age_days: int = 0) -> ScanResult:
    """itch.io app cache, downloads, and community data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"itch\apps"),
        os.path.join(local, r"itch\buckets"),
        os.path.join(local, r"itch\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_kongregate_cache(min_age_days: int = 0) -> ScanResult:
    """Kongregate game launcher cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [os.path.join(local, r"Kongregate")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gamejolt_cache(min_age_days: int = 0) -> ScanResult:
    """GameJolt client cache and game data staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"GameJolt")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_bsd_wine_cache(min_age_days: int = 0) -> ScanResult:
    """Battle.net Desktop App (new) cache and Blizzard update staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Blizzard\Battle.net\Cache"),
        os.path.join(appdata, r"Blizzard\Battle.net\WebCache"),
        os.path.join(local, r"Blizzard\Battle.net\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ea_desktop_full_cache(min_age_days: int = 0) -> ScanResult:
    """EA app (new) download cache, web cache, and game content staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"EA Desktop\Cache"),
        os.path.join(appdata, r"EA Desktop\logs"),
        os.path.join(local, r"EA Desktop\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ubisoft_connect_cache(min_age_days: int = 0) -> ScanResult:
    """Ubisoft Connect cache, download, and shader cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Ubisoft\Connect\cache"),
        os.path.join(appdata, r"Ubisoft\Connect\downloads"),
        os.path.join(appdata, r"Ubisoft\Connect\logs"),
        os.path.join(appdata, r"Ubisoft\Connect\shader-cache"),
        os.path.join(local, r"Ubisoft\Connect\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More Dev Tools ────────────────────────────────────────────────────────────

def scan_rider_cache(min_age_days: int = 0) -> ScanResult:
    """JetBrains Rider logs, caches, andresharper data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\Rider*\logs"),
        os.path.join(appdata, r"JetBrains\Rider*\caches"),
        os.path.join(local, r"JetBrains\Rider*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_datagrip_cache(min_age_days: int = 0) -> ScanResult:
    """JetBrains DataGrip schema cache and result set cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\DataGrip*\logs"),
        os.path.join(appdata, r"JetBrains\DataGrip*\caches"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_clion_cache(min_age_days: int = 0) -> ScanResult:
    """CLion CMake, compilation database, and debugger symbol cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\CLion*\logs"),
        os.path.join(appdata, r"JetBrains\CLion*\caches"),
        os.path.join(local, r"JetBrains\CLion*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_goland_cache(min_age_days: int = 0) -> ScanResult:
    """GoLand caches, Go modules proxy cache, and test runner cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\GoLand*\logs"),
        os.path.join(appdata, r"JetBrains\GoLand*\caches"),
        os.path.join(local, r"JetBrains\GoLand*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_phpstorm_cache(min_age_days: int = 0) -> ScanResult:
    """PHPStorm caches, composer PHP binary cache, and xdebug trace cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\PhpStorm*\logs"),
        os.path.join(appdata, r"JetBrains\PhpStorm*\caches"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_rubymine_cache(min_age_days: int = 0) -> ScanResult:
    """RubyMine gem cache, bundler lock cache, and Rails asset pipeline cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\RubyMine*\logs"),
        os.path.join(appdata, r"JetBrains\RubyMine*\caches"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_pycharm_cache(min_age_days: int = 0) -> ScanResult:
    """PyCharm caches, Python bytecode cache, and pytest result cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\PyCharm*\logs"),
        os.path.join(appdata, r"JetBrains\PyCharm*\caches"),
        os.path.join(local, r"JetBrains\PyCharm*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_webstorm_cache(min_age_days: int = 0) -> ScanResult:
    """WebStorm caches, npm resolution cache, and TypeScript project cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\WebStorm*\logs"),
        os.path.join(appdata, r"JetBrains\WebStorm*\caches"),
        os.path.join(local, r"JetBrains\WebStorm*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_intellij_cache(min_age_days: int = 0) -> ScanResult:
    """IntelliJ IDEA caches, workspace layout cache, and task result cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"JetBrains\IntelliJIdea*\logs"),
        os.path.join(appdata, r"JetBrains\IntelliJIdea*\caches"),
        os.path.join(local, r"JetBrains\IntelliJIdea*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_resharper_cache(min_age_days: int = 0) -> ScanResult:
    """ReSharper cache, symbol server data, and extension host cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"JetBrains\Unoble\ReSharperHost")]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_android_studio_cache(min_age_days: int = 0) -> ScanResult:
    """Android Studio build cache, emulator HAXM logs, and SDK manager temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Google\AndroidStudio*\logs"),
        os.path.join(appdata, r"Google\AndroidStudio*\caches"),
        os.path.join(local, r"Google\AndroidStudio*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_aws_toolkit_cache(min_age_days: int = 0) -> ScanResult:
    """AWS Toolkit for VS Code cache and SAM CLI build cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"AWStoolkit"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vscode_settings_sync(min_age_days: int = 0) -> ScanResult:
    """VS Code settings sync log and workspace storage cache only — NOT user settings."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Code\User\log"),
        os.path.join(appdata, r"Code\User\workspaceStorage"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── More System & Windows ─────────────────────────────────────────────────────

def scan_windows_backup_catalog(min_age_days: int = 0) -> ScanResult:
    """Windows Backup catalog and shadow copy history logs."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\Tasks\Microsoft\Windows\SystemRestore"),
        os.path.join(windir, r"Logs\WindowsServerBackup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_reliability_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Reliability Monitor data and problem step recorder logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\Reliability"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_setup_diags(min_age_days: int = 0) -> ScanResult:
    """Windows SetupDiag verbose logs and migration data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(local, r"Microsoft\Windows\Setup\Diag"),
        os.path.join(windir, r"Panther"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_bitlocker_logs(min_age_days: int = 0) -> ScanResult:
    """BitLocker management logs and FVE reconfiguration history."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\LogFiles\BitLocker"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_nvidia_shadowplay_cache(min_age_days: int = 0) -> ScanResult:
    """NVIDIA ShadowPlay / GeForce Experience recorded gameplay cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"NVIDIA\GeForce Experience\Capture"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
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


def scan_matlab_cache(min_age_days: int = 0) -> ScanResult:
    """MATLAB preferences, editor temp, and toolbox cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"MathWorks"),
        os.path.join(local, r"MathWorks"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_stata_cache(min_age_days: int = 0) -> ScanResult:
    """Stata ado-file download cache and temporary dataset staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Stata")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_spss_cache(min_age_days: int = 0) -> ScanResult:
    """IBM SPSS Statistics output cache and custom dialog cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"IBM\SPSS")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sas_cache(min_age_days: int = 0) -> ScanResult:
    """SAS temp work library staging and output cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"SAS")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_3dsmax_cache(min_age_days: int = 0) -> ScanResult:
    """3ds Max scene explorer cache, Arnold render cache, and scene backup."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Autodesk\3dsMax"),
        os.path.join(local, r"Autodesk\3dsMax"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_maya_cache(min_age_days: int = 0) -> ScanResult:
    """Maya scene temp, Bifrost cache, and render output staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Autodesk\Maya*"),
        os.path.join(local, r"Autodesk\Maya*"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_zbrush_cache(min_age_days: int = 0) -> ScanResult:
    """ZBrush ztools, thumbnails, and autosave staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Maxon"),
        os.path.join(local, r"Maxon"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_cinema4d_cache(min_age_days: int = 0) -> ScanResult:
    """Cinema 4D render cache, preview staging, and project backups."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Maxon")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_fusion360_cache(min_age_days: int = 0) -> ScanResult:
    """Autodesk Fusion 360 cloud sync cache and simulation result cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Autodesk\Fusion 360"),
        os.path.join(local, r"Autodesk\Fusion 360"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_onedrive_commercial_cache(min_age_days: int = 0) -> ScanResult:
    """OneDrive for Business (MSOnline) sync conflict logs and local cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\OneDrive\logs"),
        os.path.join(local, r"Microsoft\OneDrive\cache"),
        os.path.join(local, r"Microsoft\OneDrive\ACSBackup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sharepoint_desktop_cache(min_age_days: int = 0) -> ScanResult:
    """SharePoint Designer workflow cache and Office document cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Office\OfficeFileCache"),
        os.path.join(local, r"Microsoft\Office\OfficeFileCache"),
    ]
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


def scan_windows_terminal_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Terminal cache, JS runtime heap, and display scaling cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows Terminal"),
        os.path.join(local, r"Microsoft\WindowsTerminal"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_powershell_ise_cache(min_age_days: int = 0) -> ScanResult:
    """PowerShell ISE saved scripts and IntelliSense cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Microsoft\WindowsPowerShell\ISE")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_terminal_settings_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Terminal settings JSON cache and theme cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [os.path.join(local, r"Microsoft\WindowsTerminal")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wsl2_distro_cache(min_age_days: int = 0) -> ScanResult:
    """WSL2 distribution ext4.vhdx and per-distro logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\CanonicalGroupLimited.Ubuntu*"),
        os.path.join(local, r"Packages\CanonicalGroupLimited.WSL*"),
        os.path.join(local, r"Lxss"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_hyperv_vmstate_cache(min_age_days: int = 0) -> ScanResult:
    """Hyper-V saved VM state (.vsv) files and checkpoint differencing disks."""
    result = ScanResult()
    progdata = os.environ.get("PROGRAMDATA", "")
    targets = [
        os.path.join(progdata, r"Microsoft\Windows\Hyper-V"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_sandbox_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Sandbox base image staging and writable layer cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.Windows.Sandbox_*\LocalState"),
    ]
    for t in targets:
        for found in glob.glob(t):
            item = _make_item(found, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_windows_printer_migration_cache(min_age_days: int = 0) -> ScanResult:
    """Printer migration XML backup files from printmanagement snapshots."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"System32\spool\PRINTERS"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_application_manifest_cache(min_age_days: int = 0) -> ScanResult:
    """Side-by-side (WinSxS) assembly manifest and policy XML cache — DANGER, system-critical."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"WinSxS\Manifests"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="danger", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_dotnet_native_cache(min_age_days: int = 0) -> ScanResult:
    """.NET Native AOT compilation cache and NGEN image service blob."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"SystemRuntime\Files"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
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


def scan_steam_deck_cache(min_age_days: int = 0) -> ScanResult:
    """Steam Deck game mode logs, Proton prefix cache, and shader staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"steamapps\common"),
        os.path.join(local, r"steamdeck"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_game_bar_widget_cache(min_age_days: int = 0) -> ScanResult:
    """Xbox Game Bar widget logs and performance overlay cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\GameBar"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_xbox_app_cache(min_age_days: int = 0) -> ScanResult:
    """Xbox app full cache: achievements, game clips, and social data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.GamingServices_*\LocalCache"),
        os.path.join(local, r"Packages\Microsoft.XboxGamingOverlay_*\LocalCache"),
        os.path.join(local, r"MicrosoftGameBar"),
    ]
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


def scan_battle_net_auth_cache(min_age_days: int = 0) -> ScanResult:
    """Battle.net authentication ticket cache and launcher webcache data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Blizzard\Battle.net\Cache"),
        os.path.join(appdata, r"Blizzard\Battle.net\WebCache"),
        os.path.join(local, r"Blizzard\Battle.net\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_blizzard_downloads_cache(min_age_days: int = 0) -> ScanResult:
    """Blizzard games downloaded patch staging and content manifest cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Blizzard\Battle.net\logs"),
        os.path.join(appdata, r"Blizzard\Diablo III\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steam_download_cache(min_age_days: int = 0) -> ScanResult:
    """Steam downloaded game content and workshop item download staging."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Programs\Steam\downloads"),
        os.path.join(local, r"Programs\Steam\steamapps"),
        os.path.join(appdata, r"Steam\htmlcache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steam_shader_cache(min_age_days: int = 0) -> ScanResult:
    """Steam per-game shader pre-caching and dx9shader cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Programs\Steam\shadercache"),
        os.path.join(local, r"Programs\Steam\htmlcache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_epic_manifest_cache(min_age_days: int = 0) -> ScanResult:
    """Epic Games Launcher manifest data and download URL redirect cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"EpicGamesLauncher\Data\Manifests"),
        os.path.join(local, r"EpicGamesLauncher\Saved\logs"),
        os.path.join(appdata, r"Epic\EpicGamesLauncher\Data\Manifests"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_gog_offline_cache(min_age_days: int = 0) -> ScanResult:
    """GOG Galaxy offline installer cache and game backup metadata."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"GOG.com\Galaxy\Cache"),
        os.path.join(appdata, r"GOG.com\Galaxy\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_minecraft_launcher_cache(min_age_days: int = 0) -> ScanResult:
    """Minecraft Launcher game logs, crash reports, and resourcepack staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r".minecraft\logs"),
        os.path.join(appdata, r".minecraft\crash-reports"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_warcraft_3_cache(min_age_days: int = 0) -> ScanResult:
    """Warcraft III replay cache, ladder save data, and custom map staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Warcraft III"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_diablo4_cache(min_age_days: int = 0) -> ScanResult:
    """Diablo IV shader cache and Blizzard Battle.net game session logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Blizzard\Diablo IV\Logs"),
        os.path.join(local, r"Blizzard\Diablo IV\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ck3_cache(min_age_days: int = 0) -> ScanResult:
    """Crusader Kings III autosave staging and Paradox Launcher logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Paradox Interactive\Crusader Kings III\logs"),
        os.path.join(local, r"Paradox Interactive\Crusader Kings III"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_eu4_cache(min_age_days: int = 0) -> ScanResult:
    """Europa Universalis IV autosave cache and Paradox mod staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Paradox Interactive\Europa Universalis IV\logs"),
        os.path.join(local, r"Paradox Interactive\Europa Universalis IV"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_hoi4_cache(min_age_days: int = 0) -> ScanResult:
    """Hearts of Iron IV replay cache and DX12 diagnostic logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Paradox Interactive\Hearts of Iron IV\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_stellaris_cache(min_age_days: int = 0) -> ScanResult:
    """Stellaris game save staging and Paradox launcher update cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Paradox Interactive\Stellaris\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_rimworld_cache(min_age_days: int = 0) -> ScanResult:
    """RimWorld mod staging and Ludeon Studio debug logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Ludeon Studios\RimWorld by Ludeon Studios")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_factorio_cache(min_age_days: int = 0) -> ScanResult:
    """Factorio script output, save game, and factorio-data cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Factorio")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_terraria_cache(min_age_days: int = 0) -> ScanResult:
    """Terraria player backup files and Re-Logic game logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Re-Logic")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_stardew_cache(min_age_days: int = 0) -> ScanResult:
    """Stardew Valley save backup and ConcernedApe mod config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"StardewValley")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ck2_cache(min_age_days: int = 0) -> ScanResult:
    """Crusader Kings II replay cache and DLC download staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Paradox Interactive\Crusader Kings II\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_cities_skylines_cache(min_age_days: int = 0) -> ScanResult:
    """Cities: Skylines savegame backup and Colossal Order mod staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"Colossal Order\Cities Skylines\logs"),
        os.path.join(local, r"Colossal Order\Cities Skylines"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_snowrunner_cache(min_age_days: int = 0) -> ScanResult:
    """Snowrunner save backups and rendered truck config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r" Snowrunner")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Final Batch: Misc Apps & Utilities ─────────────────────────────────────────

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


def scan_wolfram_cache(min_age_days: int = 0) -> ScanResult:
    """Wolfram Mathematica temp evaluation and paclet download cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Wolfram")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_maple_cache(min_age_days: int = 0) -> ScanResult:
    """Maple session logs and library update cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Maplesoft")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_matlab_full_cache(min_age_days: int = 0) -> ScanResult:
    """MATLAB preferences, live script temp, and toolbox cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"MathWorks\MATLAB"),
        os.path.join(local, r"MathWorks\MATLAB"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_qgis_cache(min_age_days: int = 0) -> ScanResult:
    """QGIS active project thumbnail cache,QGis, and processing algorithm cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"QGIS")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_arcgis_cache(min_age_days: int = 0) -> ScanResult:
    """ArcGIS Pro tile cache, geodatabase temp, and geoanalytics staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"ESRI")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_unity_hub_full_cache(min_age_days: int = 0) -> ScanResult:
    """Unity Hub downloaded editors, module cache, and logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Unity Hub\logs"),
        os.path.join(local, r"Unity Hub\Cache"),
        os.path.join(local, r"Unity Hub\editors"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_godot_cache(min_age_days: int = 0) -> ScanResult:
    """Godot Engine editor cache, import, and remote debug temp."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Godot")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_cmake_cache(min_age_days: int = 0) -> ScanResult:
    """CMake generated Ninja/Makefiles and compiler output cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".cmake"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_meson_cache(min_age_days: int = 0) -> ScanResult:
    """Meson build directory and introspection data cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".cache\meson"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_conan_cache(min_age_days: int = 0) -> ScanResult:
    """Conan C++ package manager downloads and recipe cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".conan"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vcpkg_cache(min_age_days: int = 0) -> ScanResult:
    """vcpkg downloaded archives and built triplet staging."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"source\repos\vcpkg"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_scoop_bucket_cache(min_age_days: int = 0) -> ScanResult:
    """Scoop bucket cache and downloaded app staging."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r"scoop\buckets"),
        os.path.join(home, r"scoop\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_flatpak_cache(min_age_days: int = 0) -> ScanResult:
    """Flatpak remote repo metadata and downloaded bundle staging."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".local\share\flatpak"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_sdkman_cache(min_age_days: int = 0) -> ScanResult:
    """SDKMAN! SDK candidate downloads and version staging."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".sdkman\candidates"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_heroku_cli_cache(min_age_days: int = 0) -> ScanResult:
    """Heroku CLI config, plugins, and run dyno logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Heroku")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vercel_cache(min_age_days: int = 0) -> ScanResult:
    """Vercel CLI build output and now dev server cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"vercel")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_netlify_cache(min_age_days: int = 0) -> ScanResult:
    """Netlify CLI deploy cache and functions build output."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"netlify")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_supabase_cache(min_age_days: int = 0) -> ScanResult:
    """Supabase CLI local dev data and migration staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Supabase")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_firebase_cache(min_age_days: int = 0) -> ScanResult:
    """Firebase CLI token cache and emulator local data staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"firebase")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_planetscale_cache(min_age_days: int = 0) -> ScanResult:
    """Planetscale CLI branch data and query result staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"planetscale")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_stripe_cache(min_age_days: int = 0) -> ScanResult:
    """Stripe CLI logs and webhook event staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"stripe")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ngrok_cache(min_age_days: int = 0) -> ScanResult:
    """ngrok tunnel session logs and authtoken cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"ngrok")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_cloudflare_warp_cache(min_age_days: int = 0) -> ScanResult:
    """Cloudflare WARP client logs and WireGuard config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Cloudflare")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_mullvad_cache(min_age_days: int = 0) -> ScanResult:
    """Mullvad VPN tunnel logs and exit node config cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Mullvad VPN")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_protonvpn_cache(min_age_days: int = 0) -> ScanResult:
    """Proton VPN session logs and Network Lock cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"ProtonVPN")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_ipvanish_cache(min_age_days: int = 0) -> ScanResult:
    """IPVanish VPN client logs and connection profile cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"IPVanish")]
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


def scan_tailscale_cache(min_age_days: int = 0) -> ScanResult:
    """Tailscale SSH session logs and subnet router cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Tailscale")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_wg_easy_cache(min_age_days: int = 0) -> ScanResult:
    """WireGuard Easy config backups and peer connection staging."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"wg-easy")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
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


def scan_metamask_cache(min_age_days: int = 0) -> ScanResult:
    """MetaMask extension cache, vault data, and provider cache."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"MetaMask"),
        os.path.join(local, r"MetaMask"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_coinbase_cache(min_age_days: int = 0) -> ScanResult:
    """Coinbase wallet extension cache and tx relay data."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Coinbase Wallet")]
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


def scan_ndis_cache(min_age_days: int = 0) -> ScanResult:
    """Network adapter configuration and protocol binding cache (NDIS intermediate drivers)."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\NetworkConnections"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windowsupdate_orch_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Update Orchestrator scan results and pending install state."""
    result = ScanResult()
    windir = os.environ.get("windir", r"C:\Windows")
    targets = [
        os.path.join(windir, r"SoftwareDistribution\Download"),
        os.path.join(windir, r"SoftwareDistribution\Backup"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="caution", min_age_days=min_age_days)
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


def scan_triumph_cache(min_age_days: int = 0) -> ScanResult:
    """Triumph! 2 CAD cache and calculation log."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [os.path.join(appdata, r"Triumph")]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Large File Finder ───────────────────────────────────────────────────────────

def scan_large_files(min_age_days: int = 0, min_size_mb: int = 100) -> ScanResult:
    """Find files larger than min_size_mb across common user directories.

    Targets: Downloads, Documents, Videos, Desktop, and common app data folders.
    Uses os.scandir() for performance — does NOT follow symlinks.
    """
    result = ScanResult()
    home = os.path.expanduser("~")
    min_bytes = min_size_mb * 1024 * 1024
    # Use scandir for performance, walk for depth
    scan_dirs = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Videos"),
        os.path.join(home, "Desktop"),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.path.join(os.environ.get("PROGRAMFILES(x86)", r"C:\Program Files (x86)"), "Steam", "steamapps", "common"),
    ]
    _scan_large_recursive(result, scan_dirs, min_bytes, min_age_days, depth=5)
    return result


def _scan_large_recursive(result: ScanResult, dirs: list, min_bytes: int, min_age_days: int, depth: int = 5):
    """Internal recursive scanner for large files."""
    if depth <= 0:
        return
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in (".git", "node_modules", "__pycache__", ".venv", "venv"):
                                continue  # skip known huge dirs that aren't our target
                            _scan_large_recursive(result, [entry.path], min_bytes, min_age_days, depth - 1)
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                size = entry.stat().st_size
                                if size < min_bytes:
                                    continue
                                mtime = entry.stat().st_mtime
                                if min_age_days > 0 and (time.time() - mtime) < min_age_days * 86400:
                                    continue
                                result.items.append(ScanItem(
                                    path=entry.path,
                                    size=size,
                                    is_dir=False,
                                    selected=False,  # user selects which to delete
                                    safety="caution",
                                ))
                                result.total_size += size
                            except OSError:
                                pass
                    except OSError:
                        pass
        except OSError:
            pass


# ── Duplicate File Finder ─────────────────────────────────────────────────────────

def scan_duplicate_files(min_age_days: int = 0, min_size_kb: int = 100, max_depth_dirs: int = 3) -> ScanResult:
    """Find duplicate files by grouping by size then hashing.

    Phase 1: Group files by size (fast)
    Phase 2: Hash files with matching sizes (accurate)
    Only scans user directories to avoid system files.
    """
    result = ScanResult()
    home = os.path.expanduser("~")
    scan_dirs = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
    ]
    min_bytes = min_size_kb * 1024

    # Phase 1: Group by size
    size_groups: dict[int, list[str]] = {}
    for directory in scan_dirs:
        if not os.path.isdir(directory):
            continue
        _group_by_size_recursive(directory, size_groups, min_bytes, max_depth_dirs)

    # Phase 2: Hash groups with 2+ files
    import hashlib
    for size, paths in size_groups.items():
        if len(paths) < 2:
            continue
        hash_groups: dict[str, list[str]] = {}
        for path in paths:
            try:
                file_hash = _hash_file_fast(path)
                if file_hash:
                    hash_groups.setdefault(file_hash, []).append(path)
            except OSError:
                pass

        for file_hash, dup_paths in hash_groups.items():
            if len(dup_paths) < 2:
                continue
            wasted = size * (len(dup_paths) - 1)
            # Create one item per duplicate set — path is the group name
            result.items.append(ScanItem(
                path=f"[{len(dup_paths)} duplicates] {dup_paths[0]}",
                size=wasted,
                is_dir=True,
                selected=False,
                safety="caution",
            ))
            result.total_size += wasted

    return result


def _group_by_size_recursive(directory: str, size_groups: dict, min_bytes: int, depth: int):
    """Phase 1: collect files and group by size."""
    if depth <= 0:
        return
    try:
        with os.scandir(directory) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        _group_by_size_recursive(entry.path, size_groups, min_bytes, depth - 1)
                    elif entry.is_file(follow_symlinks=False):
                        size = entry.stat().st_size
                        if size >= min_bytes:
                            size_groups.setdefault(size, []).append(entry.path)
                except OSError:
                    pass
    except OSError:
        pass


def _hash_file_fast(path: str, chunk_size: int = 8192) -> Optional[str]:
    """Fast hash: only hash first 64KB + last 64KB + file size for speed."""
    import hashlib
    try:
        size = os.path.getsize(path)
        h = hashlib.md5()
        h.update(str(size).encode())
        with open(path, "rb") as f:
            h.update(f.read(chunk_size))
            if size > chunk_size * 2:
                f.seek(-chunk_size, 2)
                h.update(f.read(chunk_size))
        return h.hexdigest()
    except OSError:
        return None


# ── Empty Folder Finder ─────────────────────────────────────────────────────────

def scan_empty_folders(min_age_days: int = 0, min_depth: int = 2, max_depth: int = 10) -> ScanResult:
    """Find completely empty directories (no files, no subdirs with content).

    Scans user directories recursively between min_depth and max_depth levels.
    """
    result = ScanResult()
    home = os.path.expanduser("~")
    scan_dirs = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Pictures"),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    _find_empty_folders(result, scan_dirs, min_depth, max_depth)
    return result


def _find_empty_folders(result: ScanResult, dirs: list, min_depth: int, max_depth: int, current_depth: int = 0):
    """Recursively find and report empty folders."""
    if current_depth > max_depth:
        return
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        try:
            is_empty = True
            subdirs = []
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            subdirs.append(entry.path)
                            is_empty = False
                        elif entry.is_file(follow_symlinks=False):
                            is_empty = False
                    except OSError:
                        pass
            if is_empty and current_depth >= min_depth:
                # Check if it still exists and is empty (race condition guard)
                if os.path.isdir(directory) and not any(True for _ in os.scandir(directory)):
                    size = get_dir_size(directory)
                    result.items.append(ScanItem(
                        path=directory,
                        size=size,
                        is_dir=True,
                        selected=False,
                        safety="safe",
                    ))
                    result.total_size += size
            for subdir in subdirs:
                _find_empty_folders(result, [subdir], min_depth, max_depth, current_depth + 1)
        except OSError:
            pass


# ── Old Files Finder ───────────────────────────────────────────────────────────

def scan_old_files(min_age_days: int = 0, min_age_months: int = 6) -> ScanResult:
    """Find files not modified in min_age_months across user directories.

    Uses mtime (last modified) — Windows atime is unreliable so mtime is more practical.
    """
    result = ScanResult()
    home = os.path.expanduser("~")
    min_age_seconds = min_age_months * 30 * 86400
    scan_dirs = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
        os.path.join(home, "Music"),
    ]
    _scan_old_recursive(result, scan_dirs, min_age_seconds, depth=4)
    return result


def _scan_old_recursive(result: ScanResult, dirs: list, min_age_seconds: float, depth: int = 4):
    """Recursively find files not modified within age threshold (uses mtime, not atime)."""
    if depth <= 0:
        return
    cutoff = time.time() - min_age_seconds
    for directory in dirs:
        if not os.path.isdir(directory):
            continue
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            _scan_old_recursive(result, [entry.path], min_age_seconds, depth - 1)
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                mtime = entry.stat().st_mtime
                                if mtime < cutoff:
                                    size = entry.stat().st_size
                                    result.items.append(ScanItem(
                                        path=entry.path,
                                        size=size,
                                        is_dir=False,
                                        selected=False,
                                        safety="caution",
                                    ))
                                    result.total_size += size
                            except OSError:
                                pass
                    except OSError:
                        pass
        except OSError:
            pass


# ── PC-Specific Scanners (auto-discovered) ──────────────────────────────────────

def scan_vscode_cached_extensions(min_age_days: int = 0) -> ScanResult:
    """VS Code downloaded extension .vsix files — safe to remove (auto-reinstalled)."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Code\CachedExtensionVSIXs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vscode_dawn_cache(min_age_days: int = 0) -> ScanResult:
    """VS Code Dawn WebGPU and Graphite shader caches."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Code\DawnGraphiteCache"),
        os.path.join(appdata, r"Code\DawnWebGPUCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vscode_webstorage(min_age_days: int = 0) -> ScanResult:
    """VS Code WebStorage cache — extension web content."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Code\WebStorage"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_vscode_cached_data(min_age_days: int = 0) -> ScanResult:
    """VS Code cached data (CachedData, CachedProfilesData)."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Code\CachedData"),
        os.path.join(appdata, r"Code\CachedProfilesData"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_project_ascension_logs(min_age_days: int = 0) -> ScanResult:
    """Project Ascension launcher logs and cache — safe to clear."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(appdata, r"projectascension\Cache"),
        os.path.join(local, r"ProjectAscension\Logs"),
        r"C:\Program Files\Ascension Launcher\logs",
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_lm_studio_cache(min_age_days: int = 0) -> ScanResult:
    """LM Studio AI model cache and logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"LM Studio\Cache"),
        os.path.join(appdata, r"LM Studio\logs"),
    ]
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


def scan_windows_tweaker_logs(min_age_days: int = 0) -> ScanResult:
    """WindowsTweaker application logs."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"WindowsTweaker\logs"),
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


def scan_windows_shell_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Shell Experience Host cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.Windows.ShellExperienceHost*\LocalCache"),
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


def scan_windows_terminal_cache(min_age_days: int = 0) -> ScanResult:
    """Windows Terminal UWP local cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Packages\Microsoft.WindowsTerminal*\LocalCache"),
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


def scan_dbg_logs(min_age_days: int = 0) -> ScanResult:
    """Debug-logged application data from various dev tools."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"dbg\Logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_claude_cli_cache(min_age_days: int = 0) -> ScanResult:
    """Claude CLI Node.js cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"claude-cli-nodejs\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_microsoft_templates(min_age_days: int = 0) -> ScanResult:
    """Microsoft Office/Windows cached document templates."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Microsoft\Templates"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_uwp_all_apps_cache(min_age_days: int = 0) -> ScanResult:
    """All UWP apps LocalCache folders (aggregate scanner)."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    packages = os.path.join(local, r"Packages")
    if not os.path.isdir(packages):
        return result
    import glob as _glob
    for cache_dir in _glob.glob(os.path.join(packages, "*", "LocalCache")):
        item = _make_item(cache_dir, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Extended Browser Paths (PC-specific) ──────────────────────────────────────

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


# ── Steam Specific ─────────────────────────────────────────────────────────────

def scan_steam_logs(min_age_days: int = 0) -> ScanResult:
    """Steam client logs — safe to clear."""
    result = ScanResult()
    program_files = os.environ.get("PROGRAMFILES(x86)", r"C:\Program Files (x86)")
    targets = [
        os.path.join(program_files, r"Steam\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_steam_webhelper_cache(min_age_days: int = 0) -> ScanResult:
    """Steam WebHelper browser cache (htmlcache folder)."""
    result = ScanResult()
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(appdata, r"Steam\htmlcache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


# ── Extended System ─────────────────────────────────────────────────────────────

def scan_windows_cbs_logs(min_age_days: int = 0) -> ScanResult:
    """Windows CBS (Component Based Servicing) logs."""
    result = ScanResult()
    targets = [
        r"C:\Windows\Logs\CBS",
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_panther_logs(min_age_days: int = 0) -> ScanResult:
    """Windows Panther (setup) logs — unattend and diagnostic."""
    result = ScanResult()
    targets = [
        r"C:\Windows\Panther",
        r"C:\Windows\Panther\Tmp",
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
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


def scan_windows_installer_rollback(min_age_days: int = 0) -> ScanResult:
    """Windows Installer rollback/backout files (caution — may be needed)."""
    result = ScanResult()
    targets = [
        r"C:\Windows\Installer\Patch",
        r"C:\Windows\Installer\001",
    ]
    import glob as _glob
    for pattern in targets:
        for t in _glob.glob(pattern):
            if not os.path.isdir(t):
                continue
            item = _make_item(t, safety="caution", min_age_days=min_age_days)
            if item and item.size > 0:
                result.items.append(item)
                result.total_size += item.size
    return result


def scan_nvidia_experience_cache(min_age_days: int = 0) -> ScanResult:
    """NVIDIA GeForce Experience cache and logs."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"NVIDIA\GeForceExperience"),
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


def scan_ms_store_cache(min_age_days: int = 0) -> ScanResult:
    """Microsoft Store cache and downloaded packages."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows Store\Cache"),
        os.path.join(local, r"Packages\Microsoft.WindowsStore*\LocalCache"),
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


def scan_windows_app_extensions_cache(min_age_days: int = 0) -> ScanResult:
    """Windows App Extensions cache database."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\AppExtensionDatabase"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_connected_accounts_cache(min_age_days: int = 0) -> ScanResult:
    """Connected accounts (email, Azure AD) cached tokens and identity data."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\IdentityOLTCache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_game_bar_cache(min_age_days: int = 0) -> ScanResult:
    """Xbox Game Bar and BarSvc cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"XboxLive"),
        os.path.join(local, r"Packages\Microsoft.XboxGameOverlay*\LocalCache"),
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


def scan_notifications_cache(min_age_days: int = 0) -> ScanResult:
    """Windows notification history and toast cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\Notifications"),
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


def scan_spotify_app_cache(min_age_days: int = 0) -> ScanResult:
    """Spotify Desktop app cache and logs folders."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    targets = [
        os.path.join(local, r"Spotify\Data"),
        os.path.join(appdata, r"Spotify\Cache"),
        os.path.join(appdata, r"Spotify\logs"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_winehq_cache(min_age_days: int = 0) -> ScanResult:
    """WineHQ (Linux compatibility layer) prefix cache and logs."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".wine\drive_c\windows\temp"),
        os.path.join(home, r".cache\wine"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_msix_cache(min_age_days: int = 0) -> ScanResult:
    """MSIX package staging and expansion cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\PackageManager"),
        os.path.join(local, r"Packages\_staging"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_clang_cache(min_age_days: int = 0) -> ScanResult:
    """LLVM/Clang precompiled headers and modules cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".cache\clang"),
        os.path.join(home, r"AppData\Local\clang\Cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
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


def scan_pnpm_cache(min_age_days: int = 0) -> ScanResult:
    """pnpm package manager cache."""
    result = ScanResult()
    home = os.path.expanduser("~")
    targets = [
        os.path.join(home, r".pnpm-store"),
        os.path.join(home, r".local\share\npm\cache"),
    ]
    for t in targets:
        if not os.path.isdir(t):
            continue
        item = _make_item(t, safety="safe", min_age_days=min_age_days)
        if item and item.size > 0:
            result.items.append(item)
            result.total_size += item.size
    return result


def scan_windows_compatibility_cache(min_age_days: int = 0) -> ScanResult:
    """Windows compatibility fixer's database cache."""
    result = ScanResult()
    local = os.environ.get("LOCALAPPDATA", "")
    targets = [
        os.path.join(local, r"Microsoft\Windows\CompatibilityExperience"),
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
            except Exception as e:
                logger.warning("Failed to stop service %s: %s", self.name, e)

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self._stopped:
                try:
                    import win32serviceutil
                    win32serviceutil.StartService(self.name)
                except Exception as e:
                    logger.warning("Failed to start service %s: %s", self.name, e)
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
