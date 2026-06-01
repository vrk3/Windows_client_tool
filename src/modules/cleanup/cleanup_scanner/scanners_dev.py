"""Cleanup scanners: dev category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item, _make_item_with_age,
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
            item = _make_item(found, safety="safe", min_age_days=min_age_days)
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

__all__ = ['scan_3dsmax_cache', 'scan_android_studio_cache', 'scan_ansible_cache', 'scan_apt_cache', 'scan_arcgis_cache', 'scan_atom_cache', 'scan_autocad_cache', 'scan_bazaar_cache', 'scan_bundler_cache', 'scan_chocolatey_cache', 'scan_cinema4d_cache', 'scan_clang_cache', 'scan_claude_cli_cache', 'scan_clion_cache', 'scan_cmake_cache', 'scan_cocoapods_cache', 'scan_codeblocks_cache', 'scan_composer_cache', 'scan_conan_cache', 'scan_curl_cfgs_cache', 'scan_darcs_cache', 'scan_datagrip_cache', 'scan_dbeaver_cache', 'scan_docker_desktop_cache', 'scan_dotnet_native_cache', 'scan_eclipse_cache', 'scan_emacs_cache', 'scan_flatpak_cache', 'scan_fork_cache', 'scan_fusion360_cache', 'scan_git_lfs_cache', 'scan_gitkraken_cache', 'scan_goland_cache', 'scan_golang_cache', 'scan_gradle_caches_cache', 'scan_heidisql_cache', 'scan_hyperv_cache', 'scan_hyperv_vmstate_cache', 'scan_intellij_cache', 'scan_java_cache', 'scan_jetbrains_cache', 'scan_kind_cache', 'scan_kubernetes_cache', 'scan_lazarus_cache', 'scan_lm_studio_cache', 'scan_logitech_g_hub_cache', 'scan_maple_cache', 'scan_matlab_cache', 'scan_matlab_full_cache', 'scan_maven_repo_cache', 'scan_maya_cache', 'scan_mercurial_cache', 'scan_meson_cache', 'scan_minikube_cache', 'scan_msix_cache', 'scan_mysql_logs', 'scan_navicat_cache', 'scan_net_framework_cache', 'scan_net_sdk_cache', 'scan_netbeans_cache', 'scan_npm_cache', 'scan_npp_cache', 'scan_nuget_cache', 'scan_nuget_global_packages', 'scan_nvm_caches', 'scan_packer_cache', 'scan_parallels_cache', 'scan_perforce_cache', 'scan_phpstorm_cache', 'scan_pip_cache', 'scan_pnpm_cache', 'scan_postgres_logs', 'scan_pulumi_cache', 'scan_pycharm_cache', 'scan_pyenv_cache', 'scan_qgis_cache', 'scan_qt_creator_cache', 'scan_resharper_cache', 'scan_revitable_cache', 'scan_rider_cache', 'scan_ruby_gems_cache', 'scan_rubymine_cache', 'scan_rust_cache', 'scan_sas_cache', 'scan_scoop_bucket_cache', 'scan_scoop_cache', 'scan_sdkman_cache', 'scan_sketchup_cache', 'scan_smartgit_cache', 'scan_sourcetree_cache', 'scan_spss_cache', 'scan_sql_server_logs', 'scan_sqlitebrowser_cache', 'scan_stata_cache', 'scan_sublime_cache', 'scan_subversion_cache', 'scan_terraform_cache', 'scan_tesseract_cache', 'scan_vcpkg_cache', 'scan_vcredist_cache', 'scan_venv_cache', 'scan_vim_cache', 'scan_vmware_cache', 'scan_vscode_cache', 'scan_vscode_cached_data', 'scan_vscode_cached_extensions', 'scan_vscode_dawn_cache', 'scan_vscode_settings_sync', 'scan_vscode_webstorage', 'scan_vscodium_cache', 'scan_webstorm_cache', 'scan_wget_cache', 'scan_whisper_cache', 'scan_winget_cache', 'scan_winget_packages', 'scan_wolfram_cache', 'scan_workbench_cache', 'scan_wsl2_cache', 'scan_wsl2_distro_cache', 'scan_wsl_installer_cache', 'scan_yarn_cache', 'scan_zbrush_cache', 'scan_zed_cache']
