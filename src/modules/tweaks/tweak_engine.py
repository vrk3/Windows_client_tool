# src/modules/tweaks/tweak_engine.py
import json
import logging
import os
import subprocess
import winreg
from typing import Any, Callable, Dict, List, Optional

from core.backup_service import BackupService, StepRecord

logger = logging.getLogger(__name__)

_START_TYPE_MAP = {
    "boot": 0, "system": 1, "automatic": 2, "manual": 3, "disabled": 4,
}
_HIVE_MAP = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKU":  winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
}
_KIND_MAP = {
    "DWORD":     winreg.REG_DWORD,
    "QWORD":     winreg.REG_QWORD,
    "SZ":        winreg.REG_SZ,
    "EXPAND_SZ": winreg.REG_EXPAND_SZ,
    "BINARY":    winreg.REG_BINARY,
    "MULTI_SZ":  winreg.REG_MULTI_SZ,
}


def _parse_key(full_key: str):
    parts = full_key.split("\\", 1)
    hive = _HIVE_MAP.get(parts[0].upper(), winreg.HKEY_LOCAL_MACHINE)
    sub = parts[1] if len(parts) > 1 else ""
    return hive, sub


class TweakEngine:
    """Applies and detects tweak definitions (JSON step lists).

    BackupService is the sole undo mechanism — no undo_steps in the JSON.
    """

    def __init__(self, backup_service: BackupService):
        self._backup = backup_service

    def apply_tweak(
        self,
        tweak: Dict,
        rp_id: str,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Apply all steps. Backs up state first, records steps on success.
        Returns True if all steps succeeded."""
        steps_applied: List[StepRecord] = []
        success = True
        for step in tweak.get("steps", []):
            try:
                record = self._apply_step(step, rp_id)
                if record:
                    steps_applied.append(record)
            except Exception as e:
                key_info = step.get("key", step.get("name", step.get("cmd", "")))
                msg = f"Step failed ({step.get('type')} {key_info}): {e}"
                logger.error(msg)
                if on_error:
                    on_error(msg)
                success = False

        if steps_applied:
            self._backup.record_steps(tweak["id"], steps_applied, rp_id)
        return success

    def _apply_step(self, step: Dict, rp_id: str) -> Optional[StepRecord]:
        step_type = step["type"]
        if step_type == "registry":
            return self._apply_registry(step, rp_id)
        elif step_type == "service":
            return self._apply_service(step, rp_id)
        elif step_type == "command":
            return self._apply_command(step)
        elif step_type == "appx":
            return self._apply_appx(step, rp_id)
        elif step_type == "scheduled_task":
            return self._apply_scheduled_task(step, rp_id)
        elif step_type == "script":
            return self._apply_script(step)
        logger.warning("Unknown step type: %s", step_type)
        return None

    def _apply_registry(self, step: Dict, rp_id: str) -> StepRecord:
        full_key = step["key"]
        value_name = step.get("value", "")
        data = step["data"]
        kind = _KIND_MAP.get(step.get("kind", "DWORD"), winreg.REG_DWORD)
        hive, sub = _parse_key(full_key)

        before = None
        try:
            with winreg.OpenKey(hive, sub) as k:
                before, _ = winreg.QueryValueEx(k, value_name)
        except OSError:
            pass

        self._backup.backup_registry_key(full_key, rp_id)

        if kind == winreg.REG_BINARY and isinstance(data, str):
            data = bytes.fromhex(data)

        with winreg.CreateKeyEx(hive, sub, access=winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, value_name, 0, kind, data)

        return StepRecord("registry", full_key, before, data)

    def _apply_service(self, step: Dict, rp_id: str) -> StepRecord:
        import win32service
        import pywintypes
        name = step["name"]
        _st = step.get("start_type", "manual")
        new_start = int(_st) if isinstance(_st, int) else _START_TYPE_MAP.get(str(_st).lower(), 3)

        try:
            self._backup.backup_service_state(name, rp_id)
        except Exception as e:
            logger.warning("backup_service_state failed for %s: %s", name, e)

        before = None
        hscm = None
        hs = None
        try:
            hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            hs = win32service.OpenService(
                hscm, name,
                win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_CHANGE_CONFIG)
            config = win32service.QueryServiceConfig(hs)
            before = config[1]
            win32service.ChangeServiceConfig(
                hs, win32service.SERVICE_NO_CHANGE,
                new_start, win32service.SERVICE_NO_CHANGE,
                None, None, False, None, None, None, None)
        finally:
            if hs:
                win32service.CloseServiceHandle(hs)
            if hscm:
                win32service.CloseServiceHandle(hscm)

        return StepRecord("service", name, before, new_start)

    def _apply_command(self, step: Dict) -> StepRecord:
        cmd = step["cmd"]
        subprocess.run(
            cmd, shell=True, check=False, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return StepRecord("command", cmd, None, None)

    def _apply_script(self, step: Dict) -> StepRecord:
        cmd = step.get("command", step.get("cmd", ""))
        subprocess.run(
            cmd, shell=True, check=False, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        revert_cmd = step.get("revert_command")
        return StepRecord("script", cmd, None, None, revert_command=revert_cmd)

    def _apply_appx(self, step: Dict, rp_id: str) -> StepRecord:
        pkg = step["package"]
        self._backup.backup_appx_package(pkg, rp_id)
        subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Get-AppxPackage '{pkg}' | Remove-AppxPackage"],
            check=False, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return StepRecord("appx", pkg, pkg, None)

    def _apply_scheduled_task(self, step: Dict, rp_id: str) -> StepRecord:
        """Disable a scheduled task. Records the current state for revert."""
        task_name = step["task_name"]
        before = "Unknown"
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
                capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in result.stdout.splitlines():
                if line.startswith("Status:"):
                    before = line.split(":", 1)[1].strip()
                    break
        except Exception as e:
            logger.debug("Could not query scheduled task status for %s: %s", task_name, e)
        subprocess.run(
            ["schtasks", "/change", "/tn", task_name, "/disable"],
            check=False, capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return StepRecord("scheduled_task", task_name, before, "Disabled")

    def detect_status(self, tweak: Dict) -> str:
        """Return 'applied' | 'not_applied' | 'unknown' from first step."""
        steps = tweak.get("steps", [])
        if not steps:
            return "unknown"
        step = steps[0]
        try:
            if step["type"] == "registry":
                hive, sub = _parse_key(step["key"])
                with winreg.OpenKey(hive, sub) as k:
                    val, _ = winreg.QueryValueEx(k, step.get("value", ""))
                return "applied" if val == step["data"] else "not_applied"
            elif step["type"] == "service":
                import win32service
                hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
                try:
                    hs = win32service.OpenService(hscm, step["name"],
                                                  win32service.SERVICE_QUERY_CONFIG)
                    try:
                        config = win32service.QueryServiceConfig(hs)
                        current = config[1]
                    finally:
                        win32service.CloseServiceHandle(hs)
                finally:
                    win32service.CloseServiceHandle(hscm)
                _st = step.get("start_type", "")
                expected = int(_st) if isinstance(_st, int) else _START_TYPE_MAP.get(str(_st).lower(), -1)
                return "applied" if current == expected else "not_applied"
            elif step["type"] == "appx":
                pkg = step["package"]
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"Get-AppxPackage '{pkg}' -ErrorAction SilentlyContinue | Select-Object -First 1 Name"],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return "not_applied" if result.stdout.strip() else "applied"
            elif step["type"] == "scheduled_task":
                task_name = step["task_name"]
                result = subprocess.run(
                    ["schtasks", "/query", "/tn", task_name, "/fo", "LIST"],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.splitlines():
                    if line.startswith("Status:"):
                        state = line.split(":", 1)[1].strip()
                        return "applied" if state == "Disabled" else "not_applied"
                return "unknown"
            elif step["type"] == "script":
                # Scripts can't be reliably detected without side effects
                return "unknown"
        except OSError:
            return "unknown"
        except Exception:
            return "unknown"
        return "unknown"

    @staticmethod
    def load_definitions(json_path: str) -> List[Dict]:
        """Load a list of tweak definitions from a JSON file."""
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
