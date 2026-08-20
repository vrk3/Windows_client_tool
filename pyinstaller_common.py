"""Shared PyInstaller Analysis() inputs for all three .spec files
(WinClientTool.spec, WinClientTool-console.spec, WinClientTool-portable.spec).

Kept as plain data here instead of copy-pasted into each spec so the three
builds' datas/hiddenimports lists can't silently drift out of sync — the
folder/console/portable builds are meant to differ only in EXE/COLLECT
packaging options, not in what gets analyzed and bundled.

Each .spec file adds itself to sys.path (spec files aren't run as part of a
package) before importing this module — see any of the three for the pattern.
"""
import os


def get_main_script(project_root: str) -> str:
    return os.path.join(project_root, "src", "main.py")


def get_datas(project_root: str) -> list:
    return [
        (os.path.join(project_root, "config"), "config"),
        (os.path.join(project_root, "src", "ui", "styles"), "ui/styles"),
        (os.path.join(project_root, "src", "modules", "tweaks", "definitions"), "modules/tweaks/definitions"),
    ]


HIDDEN_IMPORTS = [
    "PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui",
    "pywin32", "pywin32_bootstrap",
    "win32api", "win32con", "win32gui", "win32process", "win32service", "win32evtlog",
    "win32com", "win32com.client",
    # TreeSize. All of these are imported lazily, inside functions, and
    # win32com.shell is loaded dynamically by pywin32 -- PyInstaller finds
    # none of them by static analysis. Without them the frozen build still
    # RUNS, which is the trap: IFileOperation silently drops to the ctypes
    # fallback (no per-item errors), the remote targets report themselves
    # unavailable, owners come back blank, and the Excel and PDF exports
    # vanish from the menu. Nothing looks broken; things are just quietly
    # missing.
    "win32com.server", "win32com.server.util", "win32com.server.policy",
    "win32com.shell", "win32com.shell.shell", "win32com.shell.shellcon",
    "pythoncom", "pywintypes", "win32security",
    "httpx", "paramiko",
    "openpyxl", "reportlab",
    "PIL", "PIL._imaging",
    "requests", "urllib3", "charset_normalizer", "idna",
    "numpy", "numpy.core", "numpy._core", "numpy._core.multiarray",
]
