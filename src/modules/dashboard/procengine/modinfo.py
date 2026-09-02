r"""The modules loaded in a process -- the lower pane's DLLs tab.

`EnumProcessModulesEx` plus `GetModuleInformation` gives the base address
and the real image size; the company and version come from the file's
version resource, which is a per-FILE fact rather than a per-process one
and is therefore cached across processes. A machine runs the same hundred
system DLLs in every process, so that cache is the difference between
reading `version.dll` resources a hundred times and once.

**A refusal is not an empty list.** A process we cannot open returns
`None` with a reason, never `[]` -- an empty DLL list reads as "this
process has loaded no libraries", which is impossible and therefore
misleading in the way that matters: it looks like an answer.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)
_version = ctypes.WinDLL("version", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
LIST_MODULES_ALL = 0x03


class _MODULEINFO(ctypes.Structure):
    _fields_ = [("lpBaseOfDll", ctypes.c_void_p),
                ("SizeOfImage", wintypes.DWORD),
                ("EntryPoint", ctypes.c_void_p)]


# Every prototype declared. An HMODULE is a pointer, and ctypes marshals an
# undeclared one as a C int -- which on x64 either raises OverflowError or,
# worse, truncates silently. details.py records the silent case killing the
# process with an access violation.
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                  wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_psapi.EnumProcessModulesEx.restype = wintypes.BOOL
_psapi.EnumProcessModulesEx.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
_psapi.GetModuleFileNameExW.restype = wintypes.DWORD
_psapi.GetModuleFileNameExW.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
_psapi.GetModuleInformation.restype = wintypes.BOOL
_psapi.GetModuleInformation.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, ctypes.POINTER(_MODULEINFO),
    wintypes.DWORD]


@dataclass(frozen=True, slots=True)
class LoadedModule:
    """One module mapped into a process."""

    name: str
    path: str
    base: int
    size: int
    company: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    #: The Authenticode signature status, filled by the DLL pane's worker
    #: via `signatures.verify_signature` -- per-file, so it is cached by
    #: path and never re-verified for every process that loads the file.
    #: None here means "not asked for", not "unsigned".
    signature: Optional[str] = None


#: path -> (company, version, description). A per-file fact, so it is
#: shared across every process that loads the file.
_VERSION_CACHE: Dict[str, Tuple[Optional[str], Optional[str],
                                Optional[str]]] = {}


def loaded_modules(pid: int, with_version: bool = True
                   ) -> Tuple[Optional[List[LoadedModule]], Optional[str]]:
    """`(modules, reason)` for one process.

    `modules` is `None` when the process could not be read -- never an
    empty list, which would claim it has loaded nothing.
    """
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        from .details import _reason

        return None, _reason(ctypes.get_last_error())
    try:
        needed = wintypes.DWORD(0)
        slots = 2048
        array = (wintypes.HMODULE * slots)()
        ok = _psapi.EnumProcessModulesEx(
            handle, ctypes.cast(array, ctypes.POINTER(wintypes.HMODULE)),
            ctypes.sizeof(array), ctypes.byref(needed), LIST_MODULES_ALL)
        if not ok:
            from .details import _reason

            return None, _reason(ctypes.get_last_error())

        count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), slots)
        out = []
        path_buffer = ctypes.create_unicode_buffer(32768)
        for index in range(count):
            module = array[index]
            if not _psapi.GetModuleFileNameExW(handle, module, path_buffer,
                                               32768):
                continue
            path = path_buffer.value
            info = _MODULEINFO()
            size = 0
            if _psapi.GetModuleInformation(handle, module, ctypes.byref(info),
                                           ctypes.sizeof(info)):
                size = int(info.SizeOfImage)
            company = version = description = None
            if with_version:
                company, version, description = version_info(path)
            out.append(LoadedModule(
                name=os.path.basename(path), path=path,
                base=int(module or 0), size=size,
                company=company, version=version, description=description))
        return out, None
    finally:
        _kernel32.CloseHandle(handle)


def version_info(path: str
                 ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """`(company, version, description)` from a file's version resource.

    Cached by path: a machine runs the same system DLLs in every process,
    so without this the pane re-reads `kernel32.dll`'s resource once per
    process that loaded it. Plenty of files carry no version resource at
    all, which is `None` -- not a blank.
    """
    if path in _VERSION_CACHE:
        return _VERSION_CACHE[path]
    found = (None, None, None)
    try:
        found = _read_version(path)
    except OSError as error:
        logger.debug("No version resource for %s: %s", path, error)
    _VERSION_CACHE[path] = found
    return found


def _read_version(path: str):
    size = _version.GetFileVersionInfoSizeW(path, None)
    if not size:
        return None, None, None
    block = ctypes.create_string_buffer(size)
    if not _version.GetFileVersionInfoW(path, 0, size, block):
        return None, None, None

    translations = ctypes.c_void_p()
    length = wintypes.UINT(0)
    if not _version.VerQueryValueW(block, r"\VarFileInfo\Translation",
                                   ctypes.byref(translations),
                                   ctypes.byref(length)) or not length.value:
        return None, None, None
    language, codepage = ctypes.cast(
        translations, ctypes.POINTER(wintypes.WORD * 2)).contents

    def field(name: str) -> Optional[str]:
        query = f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{name}"
        value = ctypes.c_void_p()
        chars = wintypes.UINT(0)
        if not _version.VerQueryValueW(block, query, ctypes.byref(value),
                                       ctypes.byref(chars)) or not chars.value:
            return None
        text = ctypes.wstring_at(value, chars.value).rstrip("\x00").strip()
        return text or None

    return field("CompanyName"), field("FileVersion"), field("FileDescription")
