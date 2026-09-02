# src/core/windows_utils.py
import logging
import os
import winreg

logger = logging.getLogger(__name__)


def ps_quote(value: str) -> str:
    """Escape a value for a PowerShell single-quoted string literal.

    PowerShell treats two adjacent quotes inside a single-quoted string as a
    literal quote ('it''s'), so doubling the quote is the whole escape. Every
    package/service/identifier that ends up interpolated into a
    ``powershell -Command "... '{value}' ..."`` line should go through this.
    """
    return str(value).replace("'", "''")


def is_reboot_pending() -> bool:
    """Check all three Windows reboot-pending indicators."""
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager",
         "PendingFileRenameOperations"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing",
         "RebootPending"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update",
         "RebootRequired"),
    ]
    for hive, path, value in keys:
        try:
            with winreg.OpenKey(hive, path) as k:
                winreg.QueryValueEx(k, value)
                return True
        except OSError:
            logger.debug("is_reboot_pending: skipping an item that could not be read", exc_info=True)
            continue
    return False


# ── Well-known directories ─────────────────────────────────────────────
#
# Windows does not have to be on C:. It usually is, which is exactly why
# hardcoding it survives: the scanner that assumes C:\Windows finds nothing
# on a machine where Windows is on D:, reports "0 B to clean", and never
# says it looked in the wrong place. There were 136 such literals when this
# was written.
#
# The fallbacks are the conventional locations, used only when the variable
# is missing entirely — which on a healthy Windows install it is not.

def system_root() -> str:
    r"""The Windows directory, e.g. C:\Windows."""
    return os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"


def system_drive() -> str:
    r"""The drive Windows is installed on, e.g. C:."""
    return os.environ.get("SystemDrive") or os.path.splitdrive(system_root())[0] or "C:"


def program_files(x86: bool = False) -> str:
    r"""Program Files, or Program Files (x86) when `x86` is set."""
    if x86:
        return (os.environ.get("ProgramFiles(x86)")
                or os.path.join(system_drive() + os.sep, "Program Files (x86)"))
    return (os.environ.get("ProgramFiles")
            or os.path.join(system_drive() + os.sep, "Program Files"))


def program_data() -> str:
    r"""The all-users application data directory, e.g. C:\ProgramData."""
    return (os.environ.get("ProgramData")
            or os.environ.get("ALLUSERSPROFILE")
            or os.path.join(system_drive() + os.sep, "ProgramData"))


def system32() -> str:
    r"""The 64-bit system directory, e.g. C:\Windows\System32."""
    return os.path.join(system_root(), "System32")
