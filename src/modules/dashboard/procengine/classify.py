r"""What KIND of process this is -- the facts Process Explorer colours rows by.

Process Explorer tints its tree by category: own processes, services,
suspended, immersive (packaged), .NET, and packed images. Services and
suspension already come from the bulk syscall and the snapshot; the three
here each need their own read, and they are not remotely equal in cost or
in trustworthiness. Measured on this machine, 271 processes:

| Fact | Source | Cost each | Found | Refused |
|---|---|---|---|---|
| immersive | `GetPackageFamilyName` | **0.01 ms** | 42 | 2 |
| .NET | `EnumProcessModulesEx` | **1.69 ms** | 15 | 21 |
| packed | PE section entropy | **4.11 ms** | 35 | 0 |

Three things that decision rests on:

**The cheap source for .NET is wrong.** The `.NET CLR Memory` performance
counter set enumerates in 140 ms for the whole machine rather than 1.69 ms
per process, which is tempting -- but it lists **4** processes where the
module scan finds **15**. Only apps that publish the legacy CLR counters
appear, which .NET Core and .NET 5+ do not by default. It is not a faster
way to get this answer; it is a faster way to get a different, wrong one.
Its instance names are also bare process names, so two `powershell` rows
cannot be told apart.

**Packed is a HEURISTIC and is labelled as one.** It is section entropy,
the same signal Process Explorer uses, and on this machine it flags
OneNote, the Command Palette and this very tool -- none of which are
packed. High entropy is ordinary in .NET assemblies, embedded certificates
and compressed resources. `PackedGuess` therefore carries the entropy it
measured rather than only a boolean, so a caller can say "looks packed"
instead of "is packed". It is also the most expensive check here, so it is
**off unless asked for**: at 4.11 ms it would triple the cost of resolving
a new process.

**A refusal is `None`, not `False`.** Twenty-one processes refuse the
module scan outright. "Not .NET" and "we were not allowed to look" are
different answers, and a row coloured as plain-native because we were
refused is a lie told in colour.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
import math
import struct
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_psapi = ctypes.WinDLL("psapi", use_last_error=True)

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
#: `GetPackageFamilyName` says this when the process has no package
#: identity, which is the ordinary answer for a desktop program.
APPMODEL_ERROR_NO_PACKAGE = 15700
LIST_MODULES_ALL = 0x03

#: Shannon entropy above which a section looks compressed or encrypted.
#: Process Explorer's own threshold. See the module docstring: this flags
#: plenty of perfectly ordinary Microsoft binaries.
PACKED_ENTROPY = 7.0

#: The CLR itself, under every name the RUNTIME has shipped as.
#:
#: `mscoree.dll` and `mscoreei.dll` are deliberately NOT here. They are the
#: shim, not the runtime, and merely touching a .NET API loads them into a
#: process that never runs managed code. Measured: asking PDH for the
#: `.NET CLR Memory` counter set loads `mscoree.dll` into the ASKING
#: process, after which a shim-based detector reports itself as .NET
#: forever. That is a second, sharper reason not to take the counter route
#: -- it is not only a wrong answer, it contaminates whoever asks.
_CLR_MODULES = frozenset({
    "clr.dll", "coreclr.dll", "mscorwks.dll",
})

_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                  wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetPackageFamilyName.restype = wintypes.LONG
_kernel32.GetPackageFamilyName.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(ctypes.c_uint32), wintypes.LPWSTR]

# An HMODULE is a POINTER, and both of these must be declared. Undeclared,
# ctypes marshals the array element as a C int and a 64-bit module base
# raises OverflowError -- which is the lucky outcome; details.py records the
# same trap silently TRUNCATING a returned pointer and killing the process
# with an access violation.
_psapi.EnumProcessModulesEx.restype = wintypes.BOOL
_psapi.EnumProcessModulesEx.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
_psapi.GetModuleBaseNameW.restype = wintypes.DWORD
_psapi.GetModuleBaseNameW.argtypes = [
    wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]


@dataclass(frozen=True, slots=True)
class PackedGuess:
    """How compressed the image LOOKS, and the number behind the guess.

    Not a bare boolean on purpose. This is entropy, not evidence: the
    caller should be able to show the figure and hedge the word.
    """

    looks_packed: bool
    entropy: Optional[float] = None
    reason: Optional[str] = None


@dataclass(frozen=True, slots=True)
class Classification:
    """The category facts for one process. `None` means we could not look."""

    pid: int
    immersive: Optional[bool] = None
    package_family: Optional[str] = None
    dotnet: Optional[bool] = None
    packed: Optional[PackedGuess] = None
    #: Why a field above is None, keyed by field name.
    unavailable: Dict[str, str] = None

    def __post_init__(self):
        if self.unavailable is None:
            object.__setattr__(self, "unavailable", {})


def _open(pid: int, access: int = PROCESS_QUERY_LIMITED_INFORMATION):
    handle = _kernel32.OpenProcess(access, False, pid)
    return handle or None


# ---- immersive ----------------------------------------------------------

def package_family_name(pid: int) -> Tuple[Optional[str], Optional[str]]:
    """The process's AppX package family, `""` if it has none, or a reason.

    Having a package identity is what "immersive" means -- it is how
    Windows itself distinguishes a Store/packaged app from a desktop one,
    and it costs 0.01 ms.
    """
    handle = _open(pid)
    if handle is None:
        return None, _reason()
    try:
        length = ctypes.c_uint32(0)
        code = _kernel32.GetPackageFamilyName(handle, ctypes.byref(length),
                                              None)
        if code == APPMODEL_ERROR_NO_PACKAGE:
            return "", None           # a definite "not packaged"
        buffer = ctypes.create_unicode_buffer(max(length.value, 1))
        code = _kernel32.GetPackageFamilyName(handle, ctypes.byref(length),
                                              buffer)
        if code != 0:
            return None, f"GetPackageFamilyName failed with {code}"
        return buffer.value, None
    finally:
        _kernel32.CloseHandle(handle)


# ---- .NET ---------------------------------------------------------------

def loaded_modules(pid: int) -> Optional[List[str]]:
    """Base names of everything loaded in `pid`, or `None` if refused."""
    handle = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ)
    if handle is None:
        return None
    try:
        needed = wintypes.DWORD(0)
        slots = 1024
        array = (wintypes.HMODULE * slots)()
        ok = _psapi.EnumProcessModulesEx(
            handle, ctypes.cast(array, ctypes.POINTER(wintypes.HMODULE)),
            ctypes.sizeof(array), ctypes.byref(needed), LIST_MODULES_ALL)
        if not ok:
            return None
        count = min(needed.value // ctypes.sizeof(wintypes.HMODULE), slots)
        names = []
        buffer = ctypes.create_unicode_buffer(260)
        for index in range(count):
            if _psapi.GetModuleBaseNameW(handle, array[index], buffer, 260):
                names.append(buffer.value)
        return names
    finally:
        _kernel32.CloseHandle(handle)


def is_dotnet(pid: int) -> Tuple[Optional[bool], Optional[str]]:
    """Whether the CLR is loaded in `pid`, or a reason we cannot say.

    By loaded module, not by the `.NET CLR Memory` counters -- those miss
    every .NET Core process (4 found against this scan's 15).
    """
    modules = loaded_modules(pid)
    if modules is None:
        return None, _reason()
    return any(name.lower() in _CLR_MODULES for name in modules), None


# ---- packed -------------------------------------------------------------

def shannon_entropy(data: bytes) -> float:
    """Bits of entropy per byte, 0..8."""
    if not data:
        return 0.0
    counts = [0] * 256
    for byte in data:
        counts[byte] += 1
    total = len(data)
    return -sum((count / total) * math.log2(count / total)
                for count in counts if count)


#: How much of each section to weigh. Whole images are tens of megabytes
#: and entropy converges long before that; 64 KB per section keeps this at
#: ~4 ms rather than ~40.
SECTION_SAMPLE = 65536
#: Sections smaller than this are skipped -- entropy over a few hundred
#: bytes is noise, and a tiny section is not what packing produces.
MIN_SECTION = 4096


def packed_guess(path: Optional[str]) -> PackedGuess:
    """Whether `path` LOOKS packed, from its highest section entropy.

    A guess, and named one. See the module docstring for what it gets
    wrong -- which on this machine is OneNote, the Command Palette and
    this tool itself.
    """
    if not path:
        return PackedGuess(False, None, "the image path is not known")
    try:
        best = _max_section_entropy(path)
    except OSError as error:
        return PackedGuess(False, None, f"could not read the image: {error}")
    except (struct.error, ValueError) as error:
        return PackedGuess(False, None, f"not a readable PE image: {error}")
    if best is None:
        return PackedGuess(False, None, "no section was large enough to weigh")
    return PackedGuess(best >= PACKED_ENTROPY, best, None)


def _max_section_entropy(path: str) -> Optional[float]:
    """The highest entropy of any sizeable section in the PE at `path`."""
    with open(path, "rb") as image:
        head = image.read(0x40)
        if head[:2] != b"MZ":
            raise ValueError("no MZ signature")
        pe_offset = struct.unpack_from("<I", head, 0x3C)[0]
        image.seek(pe_offset)
        if image.read(4) != b"PE\0\0":
            raise ValueError("no PE signature")

        coff = image.read(20)
        sections = struct.unpack_from("<H", coff, 2)[0]
        optional_size = struct.unpack_from("<H", coff, 16)[0]
        image.seek(pe_offset + 24 + optional_size)

        best = None
        for _ in range(min(sections, 96)):
            header = image.read(40)
            if len(header) < 40:
                break
            raw_size, raw_pointer = struct.unpack_from("<II", header, 16)
            if raw_size < MIN_SECTION or raw_pointer == 0:
                continue
            resume = image.tell()
            image.seek(raw_pointer)
            measured = shannon_entropy(image.read(min(raw_size,
                                                      SECTION_SAMPLE)))
            image.seek(resume)
            best = measured if best is None else max(best, measured)
        return best


# ---- the whole classification, cached -----------------------------------

def classify(pid: int, path: Optional[str] = None,
             want_packed: bool = False) -> Classification:
    """Every category fact for one process.

    `want_packed` is off by default because it is the expensive one: at
    4.11 ms it costs more than the other two together and more than half
    of a full cold detail resolution, for the least trustworthy answer.
    """
    unavailable: Dict[str, str] = {}

    family, family_error = package_family_name(pid)
    if family is None:
        immersive = None
        unavailable["immersive"] = family_error or "could not be read"
    else:
        immersive = bool(family)

    dotnet, dotnet_error = is_dotnet(pid)
    if dotnet is None:
        unavailable["dotnet"] = dotnet_error or "could not be read"

    packed = None
    if want_packed:
        packed = packed_guess(path)
        if packed.reason:
            unavailable["packed"] = packed.reason

    return Classification(
        pid=pid,
        immersive=immersive,
        package_family=family or None,
        dotnet=dotnet,
        packed=packed,
        unavailable=unavailable)


class ClassifyCache:
    """`classify` once per process, then never again.

    Keyed by `(pid, create_time)` for the reason `DetailCache` is: without
    the create time a reused pid serves the dead process's answer, and
    "this is a .NET process" is exactly the sort of claim that looks fine
    while being about something else entirely.
    """

    def __init__(self, want_packed: bool = False) -> None:
        self._entries: Dict[Tuple[int, int], Classification] = {}
        self._want_packed = want_packed

    def tracked(self) -> int:
        return len(self._entries)

    def get(self, pid: int, create_time: int, path: Optional[str] = None,
            budget: Optional[List[int]] = None) -> Classification:
        """The classification for one process, resolving it if needed.

        `budget` works exactly as `DetailCache.get`'s does -- a one-element
        mutable counter, and at zero this returns an unresolved record
        without caching it, so the next sweep tries again. The module scan
        is 1.69 ms a process, so an unbounded first sweep of 271 of them is
        most of half a second.
        """
        key = (pid, create_time)
        found = self._entries.get(key)
        if found is not None:
            return found
        if budget is not None:
            if budget[0] <= 0:
                return Classification(pid=pid)
            budget[0] -= 1
        found = classify(pid, path, self._want_packed)
        self._entries[key] = found
        return found

    def retain(self, live_pids: Set[int]) -> None:
        self._entries = {key: value for key, value in self._entries.items()
                         if key[0] in live_pids}


def service_pids() -> Optional[Set[int]]:
    """Which pids currently host a Windows service, or `None` if refused.

    `EnumServicesStatusEx` answers with the hosting pid for every running
    service -- 300 services in **1.3 ms** on this machine, 114 of them with
    a pid. Cheap enough to re-ask every tick, which it has to be: services
    start and stop, and a set captured once goes stale in exactly the way
    that makes a process list lie.

    This is the mapping `SnapshotSource.set_service_pids` was built for. It
    matters because the alternative -- matching a process's NAME against
    the list of service names -- essentially never hits: services are named
    `wuauserv` and `Winmgmt`, the processes hosting them are all called
    `svchost.exe`. Measured on this machine, the name match found 0 of 114.
    """
    try:
        import win32service
    except ImportError:  # pragma: no cover - pywin32 is a hard dependency
        return None
    handle = None
    try:
        handle = win32service.OpenSCManager(
            None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
        entries = win32service.EnumServicesStatusEx(
            handle, win32service.SERVICE_WIN32,
            win32service.SERVICE_STATE_ALL)
    except Exception as error:  # noqa: BLE001
        logger.debug("Could not enumerate services: %s", error)
        return None
    finally:
        if handle is not None:
            try:
                win32service.CloseServiceHandle(handle)
            except Exception:  # noqa: BLE001
                logger.debug("Closing the SCM handle failed", exc_info=True)
    return {entry["ProcessId"] for entry in entries if entry.get("ProcessId")}


def _reason() -> str:
    from modules.dashboard.procengine.details import _reason as describe

    return describe(ctypes.get_last_error())
