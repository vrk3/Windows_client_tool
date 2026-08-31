r"""Disk and network throughput, per device.

Both panels ask the same question -- how much is moving through this device
right now -- so both are built the same way and on the same discipline as the
process rates: **two readings and the time between them, and the first
reading is `None` rather than zero.**

Sources, and why these rather than the obvious ones:

- **Disk** uses `DeviceIoControl(IOCTL_DISK_PERFORMANCE)` against each
  physical drive. It is what Task Manager's Disk panel reads: bytes read and
  written, idle time, and the queue depth, straight from the storage stack.
  `psutil.disk_io_counters` aggregates by volume rather than by disk, so it
  cannot answer "which drive".
- **Network** uses `GetIfTable2`, which reports per-interface octet counts
  including the interface's own speed and whether it is up. `psutil` has the
  counters but not the link speed, and the speed is what the panel's graph is
  scaled against.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IOCTL_DISK_PERFORMANCE = 0x00070020

#: 100-nanosecond ticks per second, the unit the disk counters use.
HUNDRED_NS = 10_000_000


class _DISK_PERFORMANCE(ctypes.Structure):
    _fields_ = [
        ("BytesRead", ctypes.c_longlong),
        ("BytesWritten", ctypes.c_longlong),
        ("ReadTime", ctypes.c_longlong),
        ("WriteTime", ctypes.c_longlong),
        ("IdleTime", ctypes.c_longlong),
        ("ReadCount", wintypes.DWORD),
        ("WriteCount", wintypes.DWORD),
        ("QueueDepth", wintypes.DWORD),
        ("SplitCount", wintypes.DWORD),
        ("QueryTime", ctypes.c_longlong),
        ("StorageDeviceNumber", wintypes.DWORD),
        ("StorageManagerName", wintypes.WCHAR * 8),
    ]


_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_kernel32.DeviceIoControl.restype = wintypes.BOOL
_kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


@dataclass(frozen=True, slots=True)
class DiskCounters:
    """One physical disk's counters at one instant."""

    index: int
    bytes_read: int
    bytes_written: int
    read_time: int
    write_time: int
    idle_time: int
    queue_depth: int
    #: The storage stack's OWN timestamp for this sample, in 100ns ticks.
    #: Used in preference to a wall clock read here: the disks are polled in
    #: a loop, so a single `now` taken before it is already stale by the
    #: time the seventh disk answers, and that skew lands directly in the
    #: active-time percentage.
    query_time: int
    at: float


@dataclass(frozen=True, slots=True)
class DiskRate:
    """One disk's throughput over an interval."""

    index: int
    read_bps: Optional[float] = None
    write_bps: Optional[float] = None
    #: Percentage of the interval the disk was NOT idle -- Task Manager's
    #: "Active time".
    active_percent: Optional[float] = None
    queue_depth: int = 0


def disk_counters(max_disks: int = 16) -> List[DiskCounters]:
    r"""Counters for every physical disk that answers.

    A disk that refuses is skipped rather than reported as zero: an
    unreadable drive is not an idle one. `\\.\PhysicalDriveN` opens without
    elevation when asked for no access rights (see `_one_disk`), but a drive
    can still be absent -- the numbering has gaps.
    """
    now = time.monotonic()
    found = []
    for index in range(max_disks):
        counters = _one_disk(index, now)
        if counters is not None:
            found.append(counters)
    return found


def _one_disk(index: int, now: float) -> Optional[DiskCounters]:
    # Opened with NO access rights at all, which is the whole trick here.
    # `IOCTL_DISK_PERFORMANCE` is a FILE_ANY_ACCESS control code, so it does
    # not need read access to the device -- and asking for GENERIC_READ on a
    # raw physical drive DOES need elevation. Measured on this machine
    # unelevated: with GENERIC_READ, zero of seven drives open; with zero
    # access rights, all seven do.
    handle = _kernel32.CreateFileW(
        f"\\\\.\\PhysicalDrive{index}", 0,
        FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    try:
        performance = _DISK_PERFORMANCE()
        returned = wintypes.DWORD(0)
        ok = _kernel32.DeviceIoControl(
            handle, IOCTL_DISK_PERFORMANCE, None, 0,
            ctypes.byref(performance), ctypes.sizeof(performance),
            ctypes.byref(returned), None)
        if not ok:
            return None
        return DiskCounters(
            index=index,
            bytes_read=performance.BytesRead,
            bytes_written=performance.BytesWritten,
            read_time=performance.ReadTime,
            write_time=performance.WriteTime,
            idle_time=performance.IdleTime,
            queue_depth=performance.QueueDepth,
            query_time=performance.QueryTime,
            at=now)
    finally:
        _kernel32.CloseHandle(handle)


def disk_rates(before: List[DiskCounters],
               after: List[DiskCounters]) -> List[DiskRate]:
    """Throughput and active time per disk, matched by disk index.

    Matched by index rather than by position: a disk that stopped answering
    between the two readings shifts every later entry, and comparing across
    that shift attributes one drive's traffic to another.
    """
    first = {counters.index: counters for counters in before}
    rates = []
    for counters in after:
        previous = first.get(counters.index)
        if previous is None:
            rates.append(DiskRate(index=counters.index,
                                  queue_depth=counters.queue_depth))
            continue
        elapsed = counters.at - previous.at
        if elapsed <= 0:
            rates.append(DiskRate(index=counters.index,
                                  queue_depth=counters.queue_depth))
            continue
        rates.append(DiskRate(
            index=counters.index,
            read_bps=_per_second(previous.bytes_read, counters.bytes_read,
                                 elapsed),
            write_bps=_per_second(previous.bytes_written,
                                  counters.bytes_written, elapsed),
            active_percent=_active(previous, counters, elapsed),
            queue_depth=counters.queue_depth))
    return rates


def _active(before: DiskCounters, after: DiskCounters,
            elapsed: float) -> Optional[float]:
    """How much of the interval the disk was doing something.

    Derived from IDLE time, which is what the storage stack actually
    counts: active is the remainder. Read and write time overlap on a
    queued device, so adding those two would exceed the interval.

    The window is measured with the driver's OWN `QueryTime` where both
    samples carry one. Using a wall clock instead put a permanent 2-3%
    ripple on every disk, including ones doing nothing at all: the disks
    are polled in a loop, so one timestamp taken before it is wrong by
    however long the loop takes, and that error is the whole signal when
    the true answer is zero.
    """
    idle = after.idle_time - before.idle_time
    if idle < 0:
        return None
    window = _window(before, after, elapsed)
    if window <= 0:
        return None
    return min(100.0, max(0.0, (1.0 - idle / window) * 100.0))


def _window(before: DiskCounters, after: DiskCounters,
            elapsed: float) -> float:
    """The interval in 100ns ticks, from the driver's clock if it gave one."""
    if before.query_time and after.query_time:
        measured = after.query_time - before.query_time
        if measured > 0:
            return float(measured)
    return elapsed * HUNDRED_NS


def _per_second(before: int, after: int, elapsed: float) -> Optional[float]:
    moved = after - before
    if moved < 0:
        return None
    return moved / elapsed


# ---- network ------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class InterfaceCounters:
    """One network interface at one instant."""

    index: int
    name: str
    bytes_sent: int
    bytes_received: int
    speed_bps: Optional[int]
    up: bool
    #: True for the loopback adapter, which carries no real traffic and is
    #: not something Task Manager lists. Detected from its ADDRESS rather
    #: than its name: the name is localised, and "Loopback" only matches on
    #: an English install.
    loopback: bool
    at: float


@dataclass(frozen=True, slots=True)
class InterfaceRate:
    index: int
    name: str
    send_bps: Optional[float] = None
    receive_bps: Optional[float] = None
    speed_bps: Optional[int] = None
    up: bool = False
    loopback: bool = False


def interface_counters() -> List[InterfaceCounters]:
    """Per-interface octet counts, link speed and link state.

    Via psutil for the counters and the addresses, and psutil's own stats
    for the speed: `GetIfTable2` would give all three in one call, but its
    struct is large and version-sensitive, and this path is not hot -- it
    runs once a second against a handful of interfaces.
    """
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return []

    now = time.monotonic()
    try:
        counters = psutil.net_io_counters(pernic=True)
        stats = psutil.net_if_stats()
        addresses = psutil.net_if_addrs()
    except Exception as error:  # noqa: BLE001
        logger.warning("Could not read the network counters: %s", error)
        return []

    out = []
    for index, (name, entry) in enumerate(sorted(counters.items())):
        stat = stats.get(name)
        # psutil reports speed in megabits, and 0 means "unknown" rather
        # than "a zero-speed link" -- so it becomes None, not 0.
        speed = None
        if stat is not None and stat.speed:
            speed = int(stat.speed) * 1_000_000
        out.append(InterfaceCounters(
            index=index,
            name=name,
            bytes_sent=entry.bytes_sent,
            bytes_received=entry.bytes_recv,
            speed_bps=speed,
            up=bool(stat.isup) if stat is not None else False,
            loopback=_is_loopback(addresses.get(name, ())),
            at=now))
    return out


def _is_loopback(entries) -> bool:
    """Whether an interface is the loopback adapter.

    By address, not by name. "Loopback Pseudo-Interface 1" is what it is
    called on an English install and something else everywhere else, and a
    name match would quietly start listing it on a German machine.
    """
    for entry in entries:
        address = getattr(entry, "address", "") or ""
        if address.startswith("127.") or address == "::1":
            return True
    return False


def interface_rates(before: List[InterfaceCounters],
                    after: List[InterfaceCounters]) -> List[InterfaceRate]:
    """Send and receive rates per interface, matched by NAME.

    By name rather than index: interfaces come and go -- a VPN connecting,
    a dock attaching -- and an index shifts under them.
    """
    first = {counters.name: counters for counters in before}
    rates = []
    for counters in after:
        previous = first.get(counters.name)
        if previous is None:
            rates.append(InterfaceRate(
                index=counters.index, name=counters.name,
                speed_bps=counters.speed_bps, up=counters.up,
                loopback=counters.loopback))
            continue
        elapsed = counters.at - previous.at
        if elapsed <= 0:
            rates.append(InterfaceRate(
                index=counters.index, name=counters.name,
                speed_bps=counters.speed_bps, up=counters.up,
                loopback=counters.loopback))
            continue
        rates.append(InterfaceRate(
            index=counters.index,
            name=counters.name,
            send_bps=_per_second(previous.bytes_sent, counters.bytes_sent,
                                 elapsed),
            receive_bps=_per_second(previous.bytes_received,
                                    counters.bytes_received, elapsed),
            speed_bps=counters.speed_bps,
            up=counters.up,
            loopback=counters.loopback))
    return rates
