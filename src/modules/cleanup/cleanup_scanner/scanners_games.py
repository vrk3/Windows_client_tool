"""Cleanup scanners: games category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanItem, ScanResult, get_dir_size, _make_item,
)

logger = logging.getLogger(__name__)

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
            logger.debug("Ignored OSError", exc_info=True)
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

__all__ = ['scan_apex_cache', 'scan_arma_cache', 'scan_battle_net_auth_cache', 'scan_battlenet_cache', 'scan_beamng_cache', 'scan_blizzard_downloads_cache', 'scan_bsd_wine_cache', 'scan_cities_skylines_cache', 'scan_ck2_cache', 'scan_ck3_cache', 'scan_csgo_cache', 'scan_destiny2_cache', 'scan_diablo4_cache', 'scan_ea_app_cache', 'scan_ea_desktop_full_cache', 'scan_epic_games_cache', 'scan_epic_launcher_cache', 'scan_epic_manifest_cache', 'scan_eso_cache', 'scan_eu4_cache', 'scan_factorio_cache', 'scan_fortnite_cache', 'scan_forza_cache', 'scan_game_bar_widget_cache', 'scan_gamejolt_cache', 'scan_gamepass_cache', 'scan_godot_cache', 'scan_gog_cache', 'scan_gog_galaxy2_cache', 'scan_gog_offline_cache', 'scan_gta_v_cache', 'scan_hoi4_cache', 'scan_humble_cache', 'scan_humble_choice_cache', 'scan_itch_app_cache', 'scan_itch_cache', 'scan_kongregate_cache', 'scan_lol_cache', 'scan_lutris_cache', 'scan_lutris_runs_cache', 'scan_minecraft_cache', 'scan_minecraft_launcher_cache', 'scan_minedrive_cache', 'scan_oculus_cache', 'scan_overwatch_cache', 'scan_paradox_cache', 'scan_path_of_exile_cache', 'scan_protonvpn_cache', 'scan_pubg_cache', 'scan_rimworld_cache', 'scan_roblox_cache', 'scan_rockstar_cache', 'scan_rust_game_cache', 'scan_snowrunner_cache', 'scan_stardew_cache', 'scan_steamCMD_cache', 'scan_steam_cache', 'scan_steam_cloud_sync_cache', 'scan_steam_deck_cache', 'scan_steam_download_cache', 'scan_steam_full_cache', 'scan_steam_logs', 'scan_steam_proton_cache', 'scan_steam_shader_cache', 'scan_steam_webhelper_cache', 'scan_steamvr_cache', 'scan_stellaris_cache', 'scan_terraria_cache', 'scan_ubisoft_cache', 'scan_ubisoft_connect_cache', 'scan_unity_cache', 'scan_unity_hub_cache', 'scan_unity_hub_full_cache', 'scan_unreal_cache', 'scan_valorant_cache', 'scan_warcraft_3_cache', 'scan_warcraft_cache', 'scan_warframe_cache', 'scan_windows_game_bar_cache', 'scan_winehq_cache', 'scan_wineprefix_cache', 'scan_xbox_app_cache', 'scan_xbox_cache', 'scan_xbox_live_cache']
