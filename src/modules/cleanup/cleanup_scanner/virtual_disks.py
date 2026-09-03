r"""Which virtual disk images still belong to something.

`scan_virtual_disk_images` reports a large .vhd/.vhdx/.vdi/.vmdk as
`danger` and never pre-selects it, on the reasoning that the space is real
but reclaiming it means COMPACTING the image — deleting one destroys a VM.

That reasoning assumes there is still a VM. On the machine this was
written for there was not:

    E:\VMs\Ubuntu\Ubuntu.vdi   11.05 GB, dated Feb 2026
    HKLM\SOFTWARE\Oracle       does not exist
    ~\.VirtualBox              does not exist
    ~\VirtualBox VMs           does not exist
    VBoxManage.exe             not on PATH, not in either Program Files

VirtualBox was uninstalled and left 11 GB behind. Nothing on that machine
can open the file, there is no VM to destroy, and no compaction tool
exists to shrink it — so "compact, do not delete" is exactly the wrong
advice. Saying "nothing here can open this" is the whole value.

The check for each hypervisor is deliberately for the THING ITSELF, never
for a file Windows ships anyway. `wsl.exe` is present on every Windows 11
install whether or not WSL is: treating it as proof would be the same
mistake as treating a refused read as an answer.
"""
from __future__ import annotations

import functools
import logging
import os
import subprocess
from typing import Optional, Set

logger = logging.getLogger(__name__)

CREATE_NO_WINDOW = 0x08000000

#: Which product opens which image format. `.vhd`/`.vhdx` are shared by
#: Hyper-V and WSL2, so either being installed keeps the image in use.
FORMAT_OWNERS = {
    ".vdi": ("virtualbox",),
    ".vmdk": ("vmware",),
    ".qcow2": ("qemu",),
    ".vhd": ("hyperv", "wsl"),
    ".vhdx": ("hyperv", "wsl"),
}


def hypervisor_for(path: str) -> Optional[str]:
    """The product that opens this image format, or None if unrecognised.

    For a format with more than one owner, the first is returned — callers
    wanting the full set use `owners_for`.
    """
    owners = owners_for(path)
    return owners[0] if owners else None


def owners_for(path: str) -> tuple:
    return FORMAT_OWNERS.get(os.path.splitext(path)[1].lower(), ())


def _program_files_candidates(*relative: str):
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        if base:
            yield os.path.join(base, *relative)


def _on_path(executable: str) -> bool:
    from shutil import which
    return which(executable) is not None


def _virtualbox_installed() -> bool:
    if _on_path("VBoxManage.exe"):
        return True
    if any(os.path.exists(p) for p in
           _program_files_candidates("Oracle", "VirtualBox", "VBoxManage.exe")):
        return True
    return _registry_key_exists(r"SOFTWARE\Oracle\VirtualBox")


def _vmware_installed() -> bool:
    if _on_path("vmware-vdiskmanager.exe") or _on_path("vmware.exe"):
        return True
    return any(os.path.exists(p) for p in _program_files_candidates(
        "VMware", "VMware Workstation", "vmware-vdiskmanager.exe"))


def _qemu_installed() -> bool:
    return _on_path("qemu-img.exe")


def _hyperv_installed() -> bool:
    """The Hyper-V management service, not the .vhdx handling every Windows
    has. `vmms.exe` is only present once the feature is enabled."""
    windir = os.environ.get("windir", r"C:\Windows")
    return os.path.exists(os.path.join(windir, "System32", "vmms.exe"))


def _wsl_has_distros() -> bool:
    r"""True only if WSL is really installed AND has a distribution.

    `wsl.exe` ships with Windows 11 regardless, and on a machine without
    the feature it answers "The Windows Subsystem for Linux is not
    installed" — while exiting in a way that is not worth trusting on its
    own. The output is what settles it.
    """
    if not _on_path("wsl.exe"):
        return False
    try:
        proc = subprocess.run(
            ["wsl.exe", "--list", "--quiet"],
            capture_output=True, timeout=15,
            creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        logger.debug("wsl --list did not run", exc_info=True)
        return False

    # wsl.exe writes UTF-16 to a pipe.
    text = proc.stdout.decode("utf-16-le", errors="replace")
    if "\x00" in text:                       # not UTF-16 after all
        text = proc.stdout.decode("utf-8", errors="replace")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    if any("is not installed" in line.lower()
           or "no installed distributions" in line.lower() for line in lines):
        return False
    return True


_CHECKS = {
    "virtualbox": _virtualbox_installed,
    "vmware": _vmware_installed,
    "qemu": _qemu_installed,
    "hyperv": _hyperv_installed,
    "wsl": _wsl_has_distros,
}


def _registry_key_exists(subkey: str) -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey):
            return True
    except OSError:
        return False


@functools.lru_cache(maxsize=1)
def _installed_cached() -> frozenset:
    found = set()
    for name, check in _CHECKS.items():
        try:
            if check():
                found.add(name)
        except Exception:                            # noqa: BLE001
            logger.warning("Could not tell whether %s is installed", name,
                           exc_info=True)
    logger.debug("Virtualisation products present: %s", sorted(found) or "none")
    return frozenset(found)


def installed_hypervisors() -> Set[str]:
    """Everything on this machine that can open a virtual disk image.

    Cached for the process: a hypervisor is not installed mid-sweep, and
    the WSL probe spawns a process.
    """
    return set(_installed_cached())


def reset_cache() -> None:
    """Forget what was detected. For tests."""
    _installed_cached.cache_clear()


def is_orphaned(path: str) -> bool:
    """True if nothing installed here can open this image.

    An unrecognised extension is never called orphaned — we do not know
    what opens it, and "we could not tell" must not read as "nothing
    needs this".
    """
    owners = owners_for(path)
    if not owners:
        return False
    installed = installed_hypervisors()
    return not any(owner in installed for owner in owners)
