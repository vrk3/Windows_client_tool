# src/modules/performance_tuner/perf_checks.py
"""
Performance check definitions.

Each check is a dict:
  id          : unique str
  name        : display name
  category    : str
  description : what it does
  reboot      : bool — whether applying requires a reboot
  detect      : callable() -> 'optimal' | 'suboptimal' | 'unknown'
  apply       : list of tweak-engine-compatible step dicts (registry / service / command)
"""
import logging
import os
import subprocess
import winreg

logger = logging.getLogger(__name__)


def _reg_get(hive, path: str, value: str):
    try:
        with winreg.OpenKey(hive, path) as k:
            data, _ = winreg.QueryValueEx(k, value)
            return data
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Detectors — Visual Effects
# ---------------------------------------------------------------------------

def _detect_visual_effects():
    """VisualFXSetting 2 = Adjust for best performance."""
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
        "VisualFXSetting",
    )
    if val == 2:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_transparency():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        "EnableTransparency",
    )
    if val == 0:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_animations():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
        "TaskbarAnimations",
    )
    if val == 0:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_menu_show_delay():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Control Panel\Desktop",
        "MenuShowDelay",
    )
    if val == "0":
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_aero_peek():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
        "DisablePreviewDesktop",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


# ---------------------------------------------------------------------------
# Detectors — Power
# ---------------------------------------------------------------------------

def _detect_high_perf_power():
    try:
        result = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        guid = result.stdout.lower()
        if "8c5e7fda" in guid or "e9a42b02" in guid:  # High Perf or Ultimate Perf
            return "optimal"
        return "suboptimal"
    except Exception:
        return "unknown"


def _detect_power_throttling():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
        "PowerThrottlingOff",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    # Key likely absent — throttling is on by default
    return "suboptimal"


def _detect_hibernate():
    if not os.path.exists(r"C:\hiberfil.sys"):
        return "optimal"
    return "suboptimal"


# ---------------------------------------------------------------------------
# Detectors — CPU / GPU
# ---------------------------------------------------------------------------

def _detect_hardware_gpu_scheduling():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
        "HwSchMode",
    )
    if val == 2:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "suboptimal"  # absent = HAGS disabled


def _detect_boost_cpu_priority():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\PriorityControl",
        "Win32PrioritySeparation",
    )
    if val == 38:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


# ---------------------------------------------------------------------------
# Detectors — Memory & Paging
# ---------------------------------------------------------------------------

def _detect_superfetch():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\SysMain",
        "Start",
    )
    if val == 4:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_prefetch():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
        "EnablePrefetcher",
    )
    if val == 0:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_keep_kernel_in_ram():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
        "DisablePagingExecutive",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "suboptimal"  # absent = paging enabled by default


# ---------------------------------------------------------------------------
# Detectors — Storage
# ---------------------------------------------------------------------------

def _detect_search_indexing():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\WSearch",
        "Start",
    )
    if val == 4:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_ntfs_last_access():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\FileSystem",
        "NtfsDisableLastAccessUpdate",
    )
    # bit 0 set = last access updates disabled (optimal)
    if val is not None and (val & 1) == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_ntfs_8dot3():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\FileSystem",
        "NtfsDisable8dot3NameCreation",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


# ---------------------------------------------------------------------------
# Detectors — Network
# ---------------------------------------------------------------------------

def _detect_network_throttling():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
        "NetworkThrottlingIndex",
    )
    if val == 4294967295:  # 0xFFFFFFFF
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "suboptimal"  # absent = throttling active (default 10)


def _detect_delivery_opt():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\DoSvc",
        "Start",
    )
    if val == 4:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


# ---------------------------------------------------------------------------
# Detectors — Gaming
# ---------------------------------------------------------------------------

def _detect_game_mode():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\GameBar",
        "AutoGameModeEnabled",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_game_dvr():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"System\GameConfigStore",
        "GameDVR_Enabled",
    )
    if val == 0:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


# ---------------------------------------------------------------------------
# Detectors — Background Services
# ---------------------------------------------------------------------------

def _detect_remote_registry():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\RemoteRegistry",
        "Start",
    )
    if val == 4:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_diagtrack():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\DiagTrack",
        "Start",
    )
    if val == 4:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_fax():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\Fax",
        "Start",
    )
    if val == 4:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_startup_delay():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize",
        "StartupDelayInMSec",
    )
    if val == 0:
        return "optimal"
    # key absent = Windows uses default ~10 second delay
    return "suboptimal"


def _detect_edge_preload():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Policies\Microsoft\MicrosoftEdge\Main",
        "AllowPrelaunch",
    )
    if val == 0:
        return "optimal"
    # absent or 1 = Edge may preload
    return "suboptimal"


def _detect_error_reporting():
    val = _reg_get(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\Windows Error Reporting",
        "Disabled",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


def _detect_background_apps():
    val = _reg_get(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
        "GlobalUserDisabled",
    )
    if val == 1:
        return "optimal"
    if val is not None:
        return "suboptimal"
    return "unknown"


# ---------------------------------------------------------------------------
# Check catalogue
# ---------------------------------------------------------------------------

PERF_CHECKS = [
    # ── Visual Effects ────────────────────────────────────────────────────
    {
        "id": "visual_effects_best_perf",
        "name": "Adjust Visual Effects for Best Performance",
        "category": "Visual Effects",
        "description": "Sets VisualFXSetting to 2 (best performance), disabling animations and shadows.",
        "reboot": False,
        "detect": _detect_visual_effects,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects",
                   "value": "VisualFXSetting", "data": 2, "kind": "DWORD"}],
    },
    {
        "id": "disable_transparency",
        "name": "Disable Transparency Effects",
        "category": "Visual Effects",
        "description": "Turns off window transparency to reduce GPU load.",
        "reboot": False,
        "detect": _detect_transparency,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                   "value": "EnableTransparency", "data": 0, "kind": "DWORD"}],
    },
    {
        "id": "disable_animations",
        "name": "Disable Taskbar Animations",
        "category": "Visual Effects",
        "description": "Disables taskbar button animations for snappier window switching.",
        "reboot": False,
        "detect": _detect_animations,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                   "value": "TaskbarAnimations", "data": 0, "kind": "DWORD"}],
    },
    {
        "id": "menu_show_delay",
        "name": "Instant Menu Response (0 ms delay)",
        "category": "Visual Effects",
        "description": "Sets MenuShowDelay to 0 so menus open instantly instead of after 400 ms.",
        "reboot": False,
        "detect": _detect_menu_show_delay,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Control Panel\Desktop",
                   "value": "MenuShowDelay", "data": "0", "kind": "SZ"}],
    },
    {
        "id": "disable_aero_peek",
        "name": "Disable Aero Peek (Desktop Preview)",
        "category": "Visual Effects",
        "description": "Turns off the desktop preview triggered by hovering the Show Desktop button.",
        "reboot": False,
        "detect": _detect_aero_peek,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                   "value": "DisablePreviewDesktop", "data": 1, "kind": "DWORD"}],
    },
    # ── Power ─────────────────────────────────────────────────────────────
    {
        "id": "high_perf_power_plan",
        "name": "Set High Performance Power Plan",
        "category": "Power",
        "description": "Activates the High Performance power plan for maximum CPU throughput.",
        "reboot": False,
        "detect": _detect_high_perf_power,
        "apply": [{"type": "command",
                   "cmd": "powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"}],
    },
    {
        "id": "disable_power_throttling",
        "name": "Disable CPU Power Throttling",
        "category": "Power",
        "description": "Prevents Windows from throttling background CPU processes for 'efficiency'.",
        "reboot": True,
        "detect": _detect_power_throttling,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling",
                   "value": "PowerThrottlingOff", "data": 1, "kind": "DWORD"}],
    },
    {
        "id": "disable_hibernate",
        "name": "Disable Hibernation",
        "category": "Power",
        "description": "Runs 'powercfg /hibernate off' to remove hiberfil.sys and free disk space.",
        "reboot": False,
        "detect": _detect_hibernate,
        "apply": [{"type": "command", "cmd": "powercfg /hibernate off"}],
    },
    # ── CPU / GPU ─────────────────────────────────────────────────────────
    {
        "id": "hardware_gpu_scheduling",
        "name": "Enable Hardware-Accelerated GPU Scheduling",
        "category": "CPU / GPU",
        "description": "Enables HAGS (HwSchMode=2) for lower GPU latency on supported hardware.",
        "reboot": True,
        "detect": _detect_hardware_gpu_scheduling,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers",
                   "value": "HwSchMode", "data": 2, "kind": "DWORD"}],
    },
    {
        "id": "boost_cpu_priority",
        "name": "Boost Foreground CPU Priority",
        "category": "CPU / GPU",
        "description": "Sets Win32PrioritySeparation=38 to give the active window maximum CPU time.",
        "reboot": False,
        "detect": _detect_boost_cpu_priority,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl",
                   "value": "Win32PrioritySeparation", "data": 38, "kind": "DWORD"}],
    },
    # ── Memory & Paging ───────────────────────────────────────────────────
    {
        "id": "disable_superfetch",
        "name": "Disable SysMain (SuperFetch)",
        "category": "Memory & Paging",
        "description": "Disables SysMain service. Recommended for SSDs — preloading is unnecessary.",
        "reboot": False,
        "detect": _detect_superfetch,
        "apply": [{"type": "service", "name": "SysMain", "start_type": "disabled"}],
    },
    {
        "id": "disable_prefetch",
        "name": "Disable Prefetch / ReadyBoost",
        "category": "Memory & Paging",
        "description": "Disables prefetching. Recommended for systems with fast NVMe SSDs.",
        "reboot": True,
        "detect": _detect_prefetch,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management\PrefetchParameters",
                   "value": "EnablePrefetcher", "data": 0, "kind": "DWORD"}],
    },
    {
        "id": "keep_kernel_in_ram",
        "name": "Keep Kernel in RAM (Disable Paging Executive)",
        "category": "Memory & Paging",
        "description": "Prevents the kernel from being paged to disk, reducing latency spikes.",
        "reboot": True,
        "detect": _detect_keep_kernel_in_ram,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management",
                   "value": "DisablePagingExecutive", "data": 1, "kind": "DWORD"}],
    },
    # ── Storage ───────────────────────────────────────────────────────────
    {
        "id": "disable_search_indexing",
        "name": "Disable Windows Search Indexing",
        "category": "Storage",
        "description": "Disables WSearch service to reduce disk I/O.",
        "reboot": False,
        "detect": _detect_search_indexing,
        "apply": [{"type": "service", "name": "WSearch", "start_type": "disabled"}],
    },
    {
        "id": "ntfs_disable_last_access",
        "name": "Disable NTFS Last Access Timestamps",
        "category": "Storage",
        "description": "Stops NTFS from updating the last-access timestamp on every file read.",
        "reboot": True,
        "detect": _detect_ntfs_last_access,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem",
                   "value": "NtfsDisableLastAccessUpdate", "data": 1, "kind": "DWORD"}],
    },
    {
        "id": "ntfs_disable_8dot3",
        "name": "Disable NTFS 8.3 Short Filename Generation",
        "category": "Storage",
        "description": "Stops creating legacy 8.3 short names, reducing directory scan overhead.",
        "reboot": True,
        "detect": _detect_ntfs_8dot3,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control\FileSystem",
                   "value": "NtfsDisable8dot3NameCreation", "data": 1, "kind": "DWORD"}],
    },
    # ── Network ───────────────────────────────────────────────────────────
    {
        "id": "remove_network_throttling",
        "name": "Remove Network Throttling Cap",
        "category": "Network",
        "description": "Sets NetworkThrottlingIndex to 0xFFFFFFFF to remove the 10 packets/ms limit.",
        "reboot": False,
        "detect": _detect_network_throttling,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
                   "value": "NetworkThrottlingIndex", "data": 4294967295, "kind": "DWORD"}],
    },
    {
        "id": "disable_delivery_optimization",
        "name": "Disable Delivery Optimization",
        "category": "Network",
        "description": "Stops Windows from using your bandwidth to distribute updates to other PCs.",
        "reboot": False,
        "detect": _detect_delivery_opt,
        "apply": [{"type": "service", "name": "DoSvc", "start_type": "disabled"}],
    },
    # ── Gaming ────────────────────────────────────────────────────────────
    {
        "id": "enable_game_mode",
        "name": "Enable Game Mode",
        "category": "Gaming",
        "description": "Enables Windows Game Mode to prioritise game processes and prevent updates.",
        "reboot": False,
        "detect": _detect_game_mode,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\GameBar",
                   "value": "AutoGameModeEnabled", "data": 1, "kind": "DWORD"}],
    },
    {
        "id": "disable_game_dvr",
        "name": "Disable Game DVR / Background Recording",
        "category": "Gaming",
        "description": "Disables background game capture which consumes GPU, CPU and disk resources.",
        "reboot": False,
        "detect": _detect_game_dvr,
        "apply": [{"type": "registry",
                   "key": r"HKCU\System\GameConfigStore",
                   "value": "GameDVR_Enabled", "data": 0, "kind": "DWORD"}],
    },
    # ── Background Services ───────────────────────────────────────────────
    {
        "id": "disable_remote_registry",
        "name": "Disable Remote Registry Service",
        "category": "Background Services",
        "description": "Stops the Remote Registry service — reduces attack surface.",
        "reboot": False,
        "detect": _detect_remote_registry,
        "apply": [{"type": "service", "name": "RemoteRegistry", "start_type": "disabled"}],
    },
    {
        "id": "disable_diagtrack",
        "name": "Disable Telemetry Service (DiagTrack)",
        "category": "Background Services",
        "description": "Disables the Connected User Experiences and Telemetry service.",
        "reboot": False,
        "detect": _detect_diagtrack,
        "apply": [{"type": "service", "name": "DiagTrack", "start_type": "disabled"}],
    },
    {
        "id": "disable_fax",
        "name": "Disable Fax Service",
        "category": "Background Services",
        "description": "Disables the Fax service — unused on most modern desktops.",
        "reboot": False,
        "detect": _detect_fax,
        "apply": [{"type": "service", "name": "Fax", "start_type": "disabled"}],
    },
    {
        "id": "disable_startup_delay",
        "name": "Remove Startup Application Delay",
        "category": "Background Services",
        "description": "Sets StartupDelayInMSec=0 to launch startup apps immediately after login.",
        "reboot": False,
        "detect": _detect_startup_delay,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize",
                   "value": "StartupDelayInMSec", "data": 0, "kind": "DWORD"}],
    },
    {
        "id": "disable_edge_preload",
        "name": "Disable Microsoft Edge Pre-launch",
        "category": "Background Services",
        "description": "Prevents Edge from preloading at startup to save RAM and CPU.",
        "reboot": False,
        "detect": _detect_edge_preload,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SOFTWARE\Policies\Microsoft\MicrosoftEdge\Main",
                   "value": "AllowPrelaunch", "data": 0, "kind": "DWORD"}],
    },
    {
        "id": "disable_error_reporting",
        "name": "Disable Windows Error Reporting",
        "category": "Background Services",
        "description": "Stops WER from collecting and sending crash telemetry to Microsoft.",
        "reboot": False,
        "detect": _detect_error_reporting,
        "apply": [{"type": "registry",
                   "key": r"HKLM\SOFTWARE\Microsoft\Windows\Windows Error Reporting",
                   "value": "Disabled", "data": 1, "kind": "DWORD"}],
    },
    {
        "id": "disable_background_apps",
        "name": "Disable Background App Access (Global)",
        "category": "Background Services",
        "description": "Globally prevents UWP apps from running and using resources in the background.",
        "reboot": False,
        "detect": _detect_background_apps,
        "apply": [{"type": "registry",
                   "key": r"HKCU\Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
                   "value": "GlobalUserDisabled", "data": 1, "kind": "DWORD"}],
    },
]
