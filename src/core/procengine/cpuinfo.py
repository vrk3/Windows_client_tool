r"""What the CPU is doing, per core, and what the CPU actually is.

Two halves, split the way the process engine is split:

- **Live** -- `NtQuerySystemInformation(SystemProcessorPerformanceInformation)`
  returns idle, kernel, user, DPC and interrupt time for every logical
  processor in one call. Same shape as the process query, same reason: Task
  Manager draws a graph per core and cannot afford a query per core.
- **Static** -- name, base speed, sockets, cores, logical processors and cache
  sizes, read once. None of it changes while the machine is running.

**KernelTime already includes IdleTime.** That is the trap in this API, and it
does not announce itself: subtract idle from kernel or the utilisation is
wrong by exactly the idle fraction, which on a quiet machine means reporting
100% busy. The tests pin it against a machine that is mostly idle.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

SystemProcessorPerformanceInformation = 8
STATUS_SUCCESS = 0
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

# Relationship values for GetLogicalProcessorInformationEx.
RelationProcessorCore = 0
RelationCache = 2
RelationProcessorPackage = 3

_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.restype = wintypes.LONG
_ntdll.NtQuerySystemInformation.argtypes = [
    wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG)]

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetTickCount64.restype = ctypes.c_ulonglong
_kernel32.GetLogicalProcessorInformationEx.restype = wintypes.BOOL
_kernel32.GetLogicalProcessorInformationEx.argtypes = [
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
_kernel32.IsProcessorFeaturePresent.restype = wintypes.BOOL
_kernel32.IsProcessorFeaturePresent.argtypes = [wintypes.DWORD]

#: PF_VIRT_FIRMWARE_ENABLED -- virtualisation turned on in firmware, which is
#: the line Task Manager labels "Virtualization".
PF_VIRT_FIRMWARE_ENABLED = 21


class _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("IdleTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
        ("UserTime", ctypes.c_longlong),
        ("DpcTime", ctypes.c_longlong),
        ("InterruptTime", ctypes.c_longlong),
        ("InterruptCount", wintypes.ULONG),
    ]


@dataclass(frozen=True, slots=True)
class CoreTimes:
    """One logical processor's counters at one instant, in 100ns ticks."""

    idle: int
    kernel: int          # INCLUDES idle; see the module docstring
    user: int
    dpc: int
    interrupt: int
    interrupt_count: int

    @property
    def total(self) -> int:
        """All time accounted for on this core, idle included."""
        return self.kernel + self.user


@dataclass(frozen=True, slots=True)
class CoreLoad:
    """One core's utilisation over an interval, as percentages."""

    total: float
    kernel: float
    user: float
    interrupt: float


@dataclass(frozen=True, slots=True)
class CpuStatic:
    """What the processor is. Read once; none of it changes at runtime.

    Anything we could not read is `None` rather than 0 or "", the same rule
    the rest of the engine follows.
    """

    name: Optional[str] = None
    base_speed_mhz: Optional[int] = None
    sockets: Optional[int] = None
    cores: Optional[int] = None
    logical: Optional[int] = None
    l1_cache: Optional[int] = None
    l2_cache: Optional[int] = None
    l3_cache: Optional[int] = None
    virtualisation: Optional[bool] = None


def processor_times() -> List[CoreTimes]:
    """Idle, kernel, user, DPC and interrupt time for every logical core."""
    logical = _logical_count()
    size = ctypes.sizeof(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION) * logical
    buffer = ctypes.create_string_buffer(size)
    returned = wintypes.ULONG(0)
    status = _ntdll.NtQuerySystemInformation(
        SystemProcessorPerformanceInformation, buffer, size,
        ctypes.byref(returned))
    if status != STATUS_SUCCESS:
        raise OSError("NtQuerySystemInformation(processor performance) "
                      f"failed: 0x{status & 0xFFFFFFFF:08X}")

    stride = ctypes.sizeof(_SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION)
    # Trust what was RETURNED rather than what was asked for: a machine with
    # more than 64 logical processors answers for one processor group.
    count = min(logical, returned.value // stride) or logical
    out = []
    for index in range(count):
        entry = _SYSTEM_PROCESSOR_PERFORMANCE_INFORMATION.from_buffer(
            buffer, index * stride)
        out.append(CoreTimes(
            idle=entry.IdleTime, kernel=entry.KernelTime,
            user=entry.UserTime, dpc=entry.DpcTime,
            interrupt=entry.InterruptTime,
            interrupt_count=entry.InterruptCount))
    return out


def core_loads(before: List[CoreTimes],
               after: List[CoreTimes]) -> List[CoreLoad]:
    """Utilisation per core between two readings.

    `KernelTime` includes `IdleTime`, so busy time is
    `(kernel - idle) + user`. Forgetting that reports a quiet machine as
    fully loaded, and nothing in the API hints at it.
    """
    loads = []
    for one, two in zip(before, after):
        total = two.total - one.total
        if total <= 0:
            # Two readings inside the timer's resolution.
            loads.append(CoreLoad(0.0, 0.0, 0.0, 0.0))
            continue
        idle = max(0, two.idle - one.idle)
        kernel = max(0, (two.kernel - one.kernel) - idle)
        user = max(0, two.user - one.user)
        interrupt = max(0, two.interrupt - one.interrupt)
        loads.append(CoreLoad(
            total=_pct(kernel + user, total),
            kernel=_pct(kernel, total),
            user=_pct(user, total),
            interrupt=_pct(interrupt, total)))
    return loads


def _pct(part: int, whole: int) -> float:
    return min(100.0, max(0.0, part / whole * 100.0))


def uptime_seconds() -> float:
    """How long since the machine booted."""
    return _kernel32.GetTickCount64() / 1000.0


def cpu_static() -> CpuStatic:
    """Everything about the processor that does not change."""
    name, speed = _from_registry()
    topology = _topology()
    return CpuStatic(
        name=name,
        base_speed_mhz=speed,
        sockets=topology.get("sockets"),
        cores=topology.get("cores"),
        logical=topology.get("logical") or _logical_count(),
        l1_cache=topology.get("l1"),
        l2_cache=topology.get("l2"),
        l3_cache=topology.get("l3"),
        virtualisation=_virtualisation(),
    )


def _from_registry():
    """Processor name and base clock, which live in the registry.

    There is no API for the marketing name; Task Manager reads the same
    key.
    """
    try:
        import winreg

        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            speed, _ = winreg.QueryValueEx(key, "~MHz")
            return (name or "").strip() or None, int(speed) or None
    except (OSError, ValueError) as error:
        logger.debug("Could not read the processor name: %s", error)
        return None, None


def _logical_count() -> int:
    import os

    return os.cpu_count() or 1


def _virtualisation() -> Optional[bool]:
    try:
        return bool(_kernel32.IsProcessorFeaturePresent(
            PF_VIRT_FIRMWARE_ENABLED))
    except OSError:
        return None


class _PROCESSOR_RELATIONSHIP_HEAD(ctypes.Structure):
    _fields_ = [("Relationship", wintypes.DWORD), ("Size", wintypes.DWORD)]


class _CACHE_RELATIONSHIP(ctypes.Structure):
    _fields_ = [
        ("Level", ctypes.c_ubyte),
        ("Associativity", ctypes.c_ubyte),
        ("LineSize", wintypes.WORD),
        ("CacheSize", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


def _topology() -> dict:
    """Sockets, physical cores, logical processors and cache sizes.

    `GetLogicalProcessorInformationEx` returns a chain of variable-length
    records; each one's own `Size` is the only way to find the next, so this
    walks by that rather than by a fixed stride.
    """
    needed = wintypes.DWORD(0)
    # RelationAll == 0xFFFF
    _kernel32.GetLogicalProcessorInformationEx(
        0xFFFF, None, ctypes.byref(needed))
    if not needed.value:
        return {}
    buffer = ctypes.create_string_buffer(needed.value)
    if not _kernel32.GetLogicalProcessorInformationEx(
            0xFFFF, buffer, ctypes.byref(needed)):
        logger.debug("GetLogicalProcessorInformationEx failed")
        return {}

    found = {"sockets": 0, "cores": 0, "logical": 0}
    caches = {1: 0, 2: 0, 3: 0}
    offset = 0
    limit = needed.value
    head_size = ctypes.sizeof(_PROCESSOR_RELATIONSHIP_HEAD)
    while offset + head_size <= limit:
        head = _PROCESSOR_RELATIONSHIP_HEAD.from_buffer(buffer, offset)
        if head.Size == 0:
            break
        if head.Relationship == RelationProcessorPackage:
            found["sockets"] += 1
        elif head.Relationship == RelationProcessorCore:
            found["cores"] += 1
        elif head.Relationship == RelationCache:
            cache = _CACHE_RELATIONSHIP.from_buffer(buffer,
                                                    offset + head_size)
            if cache.Level in caches:
                caches[cache.Level] += cache.CacheSize
        offset += head.Size

    found["logical"] = _logical_count()
    return {
        "sockets": found["sockets"] or None,
        "cores": found["cores"] or None,
        "logical": found["logical"],
        "l1": caches[1] or None,
        "l2": caches[2] or None,
        "l3": caches[3] or None,
    }
