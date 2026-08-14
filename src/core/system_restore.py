"""Real Windows System Restore checkpoint creation (Checkpoint-Computer).

This is distinct from BackupService.create_restore_point (this app's own
SQLite-backed tweak-revert log) — it creates an actual OS-level restore point.
Synchronous; callers must run this inside a Worker/COMWorker, never on the
Qt main thread.
"""
import logging
import subprocess
from typing import Tuple

logger = logging.getLogger(__name__)


def create_restore_point(description: str, timeout: int = 60) -> Tuple[bool, str]:
    """Create a Windows System Restore point.

    Enables System Restore on C:\\, bypasses the "one restore point per 24h"
    throttle for this call (SystemRestorePointCreationFrequency=0), then runs
    Checkpoint-Computer. Returns (success, output_or_error_message).
    """
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Enable-ComputerRestore -Drive 'C:\\'"],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        logger.warning("Enable-ComputerRestore failed", exc_info=True)

    try:
        import winreg

        key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SystemRestore"
        with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            winreg.SetValueEx(key, "SystemRestorePointCreationFrequency", 0, winreg.REG_DWORD, 0)
    except Exception:
        logger.warning("Could not bypass restore-point frequency throttle", exc_info=True)

    try:
        safe_desc = description.replace("'", "''")
        result = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                f"Checkpoint-Computer -Description '{safe_desc}' -RestorePointType 'MODIFY_SETTINGS'",
            ],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output
    except Exception as e:
        return False, str(e)
