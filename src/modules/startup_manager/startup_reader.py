import logging
import os
import glob
import json
import winreg
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

ENABLED_BYTES = bytes([0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
DISABLED_BYTES = bytes([0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])


@dataclass
class StartupEntry:
    name: str
    command: str
    enabled: bool
    source: str  # "registry_run" | "startup_folder" | "task" | "service" | "browser_ext"
    extra: str = ""  # publisher, service name, etc.


def get_registry_entries() -> List[StartupEntry]:
    entries = []
    run_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    approved_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    disabled_names = set()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, approved_key) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                    if isinstance(data, bytes) and len(data) >= 1 and data[0] == 0x03:
                        disabled_names.add(name)
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                    entries.append(StartupEntry(
                        name=name,
                        command=str(data),
                        enabled=(name not in disabled_names),
                        source="registry_run",
                    ))
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return entries


def set_registry_entry_enabled(name: str, enabled: bool) -> None:
    approved_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
    value = ENABLED_BYTES if enabled else DISABLED_BYTES
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, approved_key,
        0, winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY
    ) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, value)


def get_startup_folder_entries() -> List[StartupEntry]:
    entries = []
    folder = os.path.join(
        os.environ.get("APPDATA", ""),
        r"Microsoft\Windows\Start Menu\Programs\Startup",
    )
    approved_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
    disabled_names = set()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, approved_key) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                    if isinstance(data, bytes) and len(data) >= 1 and data[0] == 0x03:
                        disabled_names.add(name)
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            if f.lower().endswith((".lnk", ".url", ".bat", ".cmd", ".exe")):
                entries.append(StartupEntry(
                    name=f,
                    command=os.path.join(folder, f),
                    enabled=(f not in disabled_names),
                    source="startup_folder",
                ))
    return entries


def set_startup_folder_entry_enabled(name: str, enabled: bool) -> None:
    approved_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
    value = ENABLED_BYTES if enabled else DISABLED_BYTES
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, approved_key,
        0, winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY
    ) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, value)


def get_scheduled_task_entries() -> List[StartupEntry]:
    """Uses win32com Schedule.Service. Must be called from a COMWorker thread."""
    import win32com.client
    entries = []
    try:
        svc = win32com.client.Dispatch("Schedule.Service")
        svc.Connect()
        root = svc.GetFolder("\\")
        tasks = root.GetTasks(0)
        for i in range(tasks.Count):
            task = tasks.Item(i + 1)
            try:
                path = task.Definition.Actions.Item(1).Path \
                    if task.Definition.Actions.Count > 0 else ""
            except Exception:
                path = ""
            entries.append(StartupEntry(
                name=task.Name,
                command=path,
                enabled=task.Enabled,
                source="task",
                extra=f"Last: {str(task.LastRunTime)[:10]}",
            ))
    except Exception as e:
        logger.warning("Failed to load scheduled task entries: %s", e)
    return entries


def get_service_entries() -> List[StartupEntry]:
    """Get auto-start services."""
    import win32service
    entries = []
    try:
        scm = win32service.OpenSCManager(
            None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE
        )
        svcs = win32service.EnumServicesStatus(
            scm,
            win32service.SERVICE_WIN32,
            win32service.SERVICE_STATE_ALL,
        )
        for name, display_name, status in svcs:
            try:
                hs = win32service.OpenService(
                    scm, name, win32service.SERVICE_QUERY_CONFIG
                )
                config = win32service.QueryServiceConfig(hs)
                start_type = config[1]
                win32service.CloseServiceHandle(hs)
                if start_type in (
                    win32service.SERVICE_AUTO_START,
                    win32service.SERVICE_BOOT_START,
                ):
                    running = status[1] == win32service.SERVICE_RUNNING
                    entries.append(StartupEntry(
                        name=display_name,
                        command=name,
                        enabled=(start_type == win32service.SERVICE_AUTO_START),
                        source="service",
                        extra="Running" if running else "Stopped",
                    ))
            except Exception:
                continue
        win32service.CloseServiceHandle(scm)
    except Exception as e:
        logger.warning("Failed to load service entries: %s", e)
    return entries


def get_browser_extensions() -> List[StartupEntry]:
    """Read Chrome + Edge extensions from disk (read-only)."""
    entries = []
    local = os.environ.get("LOCALAPPDATA", "")
    browsers = [
        ("Chrome", os.path.join(local, r"Google\Chrome\User Data\Default\Extensions")),
        ("Edge", os.path.join(local, r"Microsoft\Edge\User Data\Default\Extensions")),
    ]
    for browser, ext_dir in browsers:
        if not os.path.isdir(ext_dir):
            continue
        for ext_id in os.listdir(ext_dir):
            ext_path = os.path.join(ext_dir, ext_id)
            if not os.path.isdir(ext_path):
                continue
            # Find manifest.json in version subfolder first, then root
            manifests = glob.glob(os.path.join(ext_path, "*", "manifest.json"))
            if not manifests:
                manifests = glob.glob(os.path.join(ext_path, "manifest.json"))
            for manifest_path in manifests[:1]:
                try:
                    with open(manifest_path, encoding="utf-8", errors="replace") as f:
                        manifest = json.load(f)
                    name = manifest.get("name", ext_id)
                    version = manifest.get("version", "")
                    entries.append(StartupEntry(
                        name=name,
                        command=ext_id,
                        enabled=True,
                        source="browser_ext",
                        extra=f"{browser} v{version}",
                    ))
                    break
                except Exception:
                    continue
    return entries
