import ctypes
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_SW_SHOWNORMAL = 1

#: ShellExecuteW returns a value <= 32 to mean failure. It is a legacy API:
#: the "success" value is a fake instance handle, not a status code.
_SHELL_EXECUTE_MIN_SUCCESS = 32


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def _shell_execute(hwnd, verb: str, file: str, params: str, directory, show: int) -> int:
    """Thin wrapper over ShellExecuteW, so tests can substitute it.

    Calling the real one in a test would put a UAC prompt on the screen and
    relaunch the test runner elevated.
    """
    return ctypes.windll.shell32.ShellExecuteW(hwnd, verb, file, params, directory, show)


def get_restart_as_admin_command() -> dict:
    return {"executable": sys.executable, "args": list(sys.argv)}


def restart_as_admin() -> None:
    r"""Relaunch this process elevated.

    The arguments are quoted with `subprocess.list2cmdline`, not joined on a
    space. Joining broke on the first path containing one, and both
    `C:\Program Files\...` and a two-word user profile are entirely ordinary
    — the child then parsed a different set of arguments from the ones it
    was sent, with nothing logged either side. The same reasoning, and the
    same fix, is written up in
    `modules/security_dashboard/elevated_helper.py`, which names this
    function as the one that still had the bug.
    """
    info = get_restart_as_admin_command()
    arguments = subprocess.list2cmdline(info["args"])
    result = _shell_execute(None, "runas", info["executable"], arguments,
                            None, _SW_SHOWNORMAL)

    # The commonest failure by far is the user declining the UAC prompt.
    # That is not an error, and it must not exit — closing the application
    # because someone said No to elevating it is its own bug.
    if result is None or int(result) <= _SHELL_EXECUTE_MIN_SUCCESS:
        logger.info("elevated relaunch was not started (ShellExecuteW returned %s)",
                    result)
        return

    sys.exit(0)
