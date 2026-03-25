import ctypes
import sys

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False

def get_restart_as_admin_command() -> dict:
    return {"executable": sys.executable, "args": sys.argv}

def restart_as_admin() -> None:
    info = get_restart_as_admin_command()
    ctypes.windll.shell32.ShellExecuteW(None, "runas", info["executable"], " ".join(info["args"]), None, 1)
    sys.exit(0)
