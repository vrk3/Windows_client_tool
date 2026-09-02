# src/core/windows_utils.py
import logging
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
