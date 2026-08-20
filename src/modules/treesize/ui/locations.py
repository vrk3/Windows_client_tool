"""Quick scan locations for the Home tab's target dropdown.

Explorer offers a short list of places rather than making you type a path
every time. These are the equivalent for a disk-space tool, so the list is
weighted towards where the space actually goes: the Windows Update download
cache, the MSI installer cache, IIS logs on a server.

**Everything resolves from the ENVIRONMENT, never from a hardcoded `C:`.**
Windows is not always on C: -- least of all on the servers half these entries
are aimed at -- and a hardcoded path does not fail loudly, it silently scans
the wrong place or nothing at all.

Locations that do not exist on this machine are dropped. Most of the server
entries are absent on a laptop, and a menu item whose only possible outcome is
an error is worse than no menu item.

No Qt here, so the resolution rules are testable without a display.
"""
import os
from dataclasses import dataclass

PLACES = "Places"
TEMP = "Temp & caches"
LOGS = "Logs & dumps"


@dataclass(frozen=True)
class Location:
    label: str
    path: str


@dataclass(frozen=True)
class Group:
    name: str
    items: tuple


def _drive_root(value: str) -> str:
    r"""A drive as an ABSOLUTE root.

    `os.path.join("D:", "Users")` is `"D:Users"` -- a drive-RELATIVE path
    meaning "Users, relative to whatever the current directory on D: happens
    to be". It raises nothing and looks right in a log. The trailing separator
    is what makes it absolute.
    """
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.endswith(("\\", "/")) else value + "\\"


def _join(base: str, *parts: str) -> str:
    """Join under `base`, or return "" if the base is unknown.

    A missing environment variable must drop the one entry that needed it,
    not produce a path rooted at "\\" that scans something unrelated.
    """
    if not base:
        return ""
    return os.path.join(base, *parts) if parts else base


#: Desktop, Documents and Downloads can be REDIRECTED -- OneDrive's Known
#: Folder Move does it by default on a modern Windows install, and roaming
#: profiles do it on a domain. Guessing `%USERPROFILE%\Desktop` is not a
#: near-miss: on this very machine Desktop lives in OneDrive and the profile
#: copy does not exist, while a stale empty `%USERPROFILE%\Documents` DOES
#: exist, so the guess silently offers the wrong folder. Only the shell knows.
_REDIRECTABLE = {
    "Desktop": "FOLDERID_Desktop",
    "Documents": "FOLDERID_Documents",
    "Downloads": "FOLDERID_Downloads",
}


def shell_folder(name: str) -> str:
    """A known folder's real path, or "" if the shell cannot say.

    Falls back to nothing rather than to a guess: the caller then uses its
    profile-relative candidate, which is right on a machine with no
    redirection and is all that is available without pywin32.
    """
    folder_id = _REDIRECTABLE.get(name)
    if folder_id is None:
        return ""
    try:
        from win32com.shell import shell as _shell

        guid = getattr(_shell, folder_id, None)
        if guid is None:
            return ""
        return _shell.SHGetKnownFolderPath(guid, 0, 0) or ""
    except Exception:                               # noqa: BLE001
        # No pywin32, or a folder this Windows does not define. Not worth an
        # exception: the profile-relative fallback is usable.
        return ""


def _candidates(environ, resolve) -> list:
    system_drive = _drive_root(environ.get("SystemDrive", ""))
    system_root = environ.get("SystemRoot", "")
    profile = environ.get("USERPROFILE", "")
    local = environ.get("LOCALAPPDATA", "")
    program_data = environ.get("ProgramData", "")
    user_temp = environ.get("TEMP", "")

    return [
        (PLACES, (
            # The shell's answer wins; the profile-relative path is only the
            # fallback for a machine with no redirection and no pywin32.
            ("Desktop", resolve("Desktop") or _join(profile, "Desktop")),
            ("Documents", resolve("Documents") or _join(profile, "Documents")),
            ("Downloads", resolve("Downloads") or _join(profile, "Downloads")),
            ("Current user", _join(profile)),
            ("Users", _join(system_drive, "Users")),
        )),
        (TEMP, (
            ("Windows Temp", _join(system_root, "Temp")),
            ("User Temp", _join(user_temp)),
            # Windows Update keeps every downloaded package here and is
            # routinely the largest single folder on a neglected server.
            ("Windows Update cache",
             _join(system_root, "SoftwareDistribution", "Download")),
            # Cached MSIs for repair/uninstall. Grows without bound and must
            # never be deleted wholesale, which is exactly why seeing it helps.
            ("Installer cache", _join(system_root, "Installer")),
            ("Package Cache", _join(program_data, "Package Cache")),
            ("Error reports",
             _join(program_data, "Microsoft", "Windows", "WER")),
        )),
        (LOGS, (
            ("Windows Logs", _join(system_root, "Logs")),
            ("System log files", _join(system_root, "System32", "LogFiles")),
            ("IIS logs", _join(system_drive, "inetpub", "logs")),
            ("Minidump", _join(system_root, "Minidump")),
            ("Crash dumps", _join(local, "CrashDumps")),
        )),
    ]


def known_locations(environ=None, exists=None, resolve=None) -> list:
    """The groups to show, with absent locations and empty groups removed.

    `environ`, `exists` and `resolve` are injected so the resolution rules can
    be tested against a redirected D: install without one being available.
    """
    environ = os.environ if environ is None else environ
    exists = os.path.isdir if exists is None else exists
    resolve = shell_folder if resolve is None else resolve

    groups = []
    seen = set()
    for name, entries in _candidates(environ, resolve):
        items = []
        for label, path in entries:
            if not path:
                continue                    # its environment variable is unset
            key = os.path.normcase(os.path.normpath(path))
            if key in seen:
                # TEMP can point at the Windows temp folder. One place should
                # not appear twice under two names.
                continue
            if not exists(path):
                continue
            seen.add(key)
            items.append(Location(label, path))
        if items:
            groups.append(Group(name, tuple(items)))
    return groups
