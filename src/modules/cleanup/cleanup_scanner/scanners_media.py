"""Cleanup scanners: media category (auto-split from cleanup_scanner.py)."""
import logging
import os
import glob

from modules.cleanup.cleanup_scanner._common import (
    ScanResult, _make_item, _make_item_with_age,
)

logger = logging.getLogger(__name__)

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
            logger.debug("Ignored OSError", exc_info=True)
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

__all__ = ['scan_ableton_cache', 'scan_aftereffects_cache', 'scan_amd_radeon_cache', 'scan_audacity_cache', 'scan_blender_cache', 'scan_blender_full_cache', 'scan_camtasia_cache', 'scan_capture_one_cache', 'scan_cubase_cache', 'scan_davinci_cache', 'scan_deezer_cache', 'scan_emby_cache', 'scan_ffmpeg_cache', 'scan_filmora_cache', 'scan_flstudio_cache', 'scan_foobar_cache', 'scan_greenshot_cache', 'scan_handbrake_cache', 'scan_illustrator_cache', 'scan_infuse_cache', 'scan_intel_graphics_cache', 'scan_jellyfin_cache', 'scan_kodi_cache', 'scan_kontakt_cache', 'scan_lightshot_cache', 'scan_logic_pro_cache', 'scan_mpc_cache', 'scan_mpv_cache', 'scan_nvidia_display_cache', 'scan_nvidia_experience_cache', 'scan_nvidia_geforce_cache', 'scan_nvidia_shadowplay_cache', 'scan_obs_cache', 'scan_peertube_cache', 'scan_photoshop_cache', 'scan_plex_cache', 'scan_potplayer_cache', 'scan_premiere_cache', 'scan_qobuz_cache', 'scan_reaper_cache', 'scan_sharex_cache', 'scan_snagit_cache', 'scan_spotify_app_cache', 'scan_spotify_cache', 'scan_spotify_full_cache', 'scan_stremio_cache', 'scan_stremio_cache_full', 'scan_tidal_cache', 'scan_vegas_cache', 'scan_vlc_cache', 'scan_vst_cache']
