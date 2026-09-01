r"""The machine-wide counters behind Process Explorer's System Information.

One syscall -- `NtQuerySystemInformation(SystemPerformanceInformation)` --
answers every figure on that window that the other engine modules do not
already carry: context switches, system calls, page faults and page reads,
the pool allocation counts, free system PTEs, and the system-wide I/O
totals. `cpuinfo`, `meminfo`, `ioinfo` and `gpuinfo` supply the rest.

**The struct is undocumented and has grown across Windows versions**, so its
layout is a guess until something independent agrees with it. It was checked
both ends on this machine (Windows 11 26200) rather than trusted:

| | struct | independent source | |
|---|---|---|---|
| available pages | 11,282,363 | 11,282,357 `GetPerformanceInfo` | head |
| committed pages | 5,742,871 | 5,742,871 `GetPerformanceInfo` | head |
| commit limit | 17,167,704 | 17,167,704 `GetPerformanceInfo` | head |
| context switches | 23,851/s | 23,843/s PDH | tail |
| system calls | 444,024/s | 444,270/s PDH | tail |
| page faults | 5,087/s | 5,090/s PDH | tail |

Agreement at both ends is what makes the middle believable, and the fields
this module exposes are only the ones inside that verified span.

`NtQuerySystemInformation` also reports the length it wrote, and
`system_counters()` refuses a reply shorter than the struct rather than
reading past the end of what the kernel filled in -- on a Windows build with
a shorter struct, the tail fields would otherwise be whatever was in the
buffer, and "whatever was in the buffer" formats as a perfectly plausible
number of context switches.

Every figure here is CUMULATIVE since boot. Rates come from two samples, the
same rule the process, disk and network rates keep, and the first sample of
anything is `None` rather than 0.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
import time
from ctypes import wintypes
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_ntdll = ctypes.WinDLL("ntdll")

#: `SystemPerformanceInformation`.
SYSTEM_PERFORMANCE_INFORMATION = 2

_ULONG = ctypes.c_ulong
_LONGLONG = ctypes.c_longlong

#: The 30 cache-manager counters between the pool figures and the tail.
#: Named rather than skipped with a padding array so the layout below can be
#: read against the published struct field by field.
_CACHE_FIELDS = [(f"Cc{index}", _ULONG) for index in range(30)]


class _SYSTEM_PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("IdleProcessTime", _LONGLONG),
        ("IoReadTransferCount", _LONGLONG),
        ("IoWriteTransferCount", _LONGLONG),
        ("IoOtherTransferCount", _LONGLONG),
        ("IoReadOperationCount", _ULONG),
        ("IoWriteOperationCount", _ULONG),
        ("IoOtherOperationCount", _ULONG),
        ("AvailablePages", _ULONG),
        ("CommittedPages", _ULONG),
        ("CommitLimit", _ULONG),
        ("PeakCommitment", _ULONG),
        ("PageFaultCount", _ULONG),
        ("CopyOnWriteCount", _ULONG),
        ("TransitionCount", _ULONG),
        ("CacheTransitionCount", _ULONG),
        ("DemandZeroCount", _ULONG),
        ("PageReadCount", _ULONG),
        ("PageReadIoCount", _ULONG),
        ("CacheReadCount", _ULONG),
        ("CacheIoCount", _ULONG),
        ("DirtyPagesWriteCount", _ULONG),
        ("DirtyWriteIoCount", _ULONG),
        ("MappedPagesWriteCount", _ULONG),
        ("MappedWriteIoCount", _ULONG),
        ("PagedPoolPages", _ULONG),
        ("NonPagedPoolPages", _ULONG),
        ("PagedPoolAllocs", _ULONG),
        ("PagedPoolFrees", _ULONG),
        ("NonPagedPoolAllocs", _ULONG),
        ("NonPagedPoolFrees", _ULONG),
        ("FreeSystemPtes", _ULONG),
        ("ResidentSystemCodePage", _ULONG),
        ("TotalSystemDriverPages", _ULONG),
        ("TotalSystemCodePages", _ULONG),
        ("NonPagedPoolLookasideHits", _ULONG),
        ("PagedPoolLookasideHits", _ULONG),
        ("AvailablePagedPoolPages", _ULONG),
        ("ResidentSystemCachePage", _ULONG),
        ("ResidentPagedPoolPage", _ULONG),
        ("ResidentSystemDriverPage", _ULONG),
    ] + _CACHE_FIELDS + [
        ("ContextSwitches", _ULONG),
        ("FirstLevelTbFills", _ULONG),
        ("SecondLevelTbFills", _ULONG),
        ("SystemCalls", _ULONG),
    ]


_ntdll.NtQuerySystemInformation.restype = ctypes.c_long
_ntdll.NtQuerySystemInformation.argtypes = [
    ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
    ctypes.POINTER(wintypes.ULONG)]


@dataclass(frozen=True, slots=True)
class SystemCounters:
    """The machine's cumulative counters at one instant.

    Byte counts are bytes; anything named `_pages` is pages, because that is
    what the kernel reports and converting here would need a page size this
    struct does not carry. `page_size` is supplied alongside for callers
    that want bytes.
    """

    at: float
    io_read_bytes: int
    io_write_bytes: int
    io_other_bytes: int
    io_read_ops: int
    io_write_ops: int
    io_other_ops: int
    available_pages: int
    committed_pages: int
    commit_limit_pages: int
    peak_commit_pages: int
    page_faults: int
    demand_zero_faults: int
    page_reads: int
    page_read_ios: int
    dirty_writes: int
    mapped_writes: int
    paged_pool_pages: int
    nonpaged_pool_pages: int
    paged_pool_allocs: int
    paged_pool_frees: int
    nonpaged_pool_allocs: int
    nonpaged_pool_frees: int
    free_system_ptes: int
    context_switches: int
    system_calls: int


@dataclass(frozen=True, slots=True)
class SystemRates:
    """Per-second figures between two samples.

    Every field is `None` until there are two readings to divide. Zero would
    be a claim: an idle machine and an unmeasured one look the same on a
    graph, and only one of them is a fact.
    """

    io_read_bps: Optional[float] = None
    io_write_bps: Optional[float] = None
    io_other_bps: Optional[float] = None
    io_read_ops: Optional[float] = None
    io_write_ops: Optional[float] = None
    io_other_ops: Optional[float] = None
    page_faults: Optional[float] = None
    page_reads: Optional[float] = None
    context_switches: Optional[float] = None
    system_calls: Optional[float] = None

    @property
    def io_total_bps(self) -> Optional[float]:
        """Read plus write plus other, or `None` if any part is unmeasured.

        Not a sum with the gaps read as zero -- that would report a total
        smaller than the machine's real traffic and look like a reading.
        """
        parts = (self.io_read_bps, self.io_write_bps, self.io_other_bps)
        if any(part is None for part in parts):
            return None
        return sum(parts)


def page_size() -> int:
    """The system page size, for turning the page counts into bytes."""
    class _SYSTEM_INFO(ctypes.Structure):
        _fields_ = [("wProcessorArchitecture", wintypes.WORD),
                    ("wReserved", wintypes.WORD),
                    ("dwPageSize", wintypes.DWORD),
                    ("lpMinimumApplicationAddress", ctypes.c_void_p),
                    ("lpMaximumApplicationAddress", ctypes.c_void_p),
                    ("dwActiveProcessorMask", ctypes.c_void_p),
                    ("dwNumberOfProcessors", wintypes.DWORD),
                    ("dwProcessorType", wintypes.DWORD),
                    ("dwAllocationGranularity", wintypes.DWORD),
                    ("wProcessorLevel", wintypes.WORD),
                    ("wProcessorRevision", wintypes.WORD)]

    info = _SYSTEM_INFO()
    ctypes.WinDLL("kernel32").GetSystemInfo(ctypes.byref(info))
    return int(info.dwPageSize) or 4096


def system_counters() -> Optional[SystemCounters]:
    """One reading of the machine-wide counters, or `None`.

    `None` rather than a zeroed record when the call fails or the kernel
    wrote less than this struct expects. A short reply means the fields at
    the tail -- context switches and system calls, the two this window
    exists to show -- would be uninitialised buffer, which formats as a
    perfectly ordinary number and is not one.
    """
    buffer = _SYSTEM_PERFORMANCE_INFORMATION()
    written = wintypes.ULONG(0)
    status = _ntdll.NtQuerySystemInformation(
        SYSTEM_PERFORMANCE_INFORMATION, ctypes.byref(buffer),
        ctypes.sizeof(buffer), ctypes.byref(written))
    if status != 0:
        logger.warning("The system performance counters were refused: "
                       "status %#x", status & 0xFFFFFFFF)
        return None
    if written.value < ctypes.sizeof(buffer):
        logger.warning(
            "The kernel filled %d bytes of a %d-byte performance record; "
            "the tail counters would be uninitialised memory",
            written.value, ctypes.sizeof(buffer))
        return None

    return SystemCounters(
        at=time.monotonic(),
        io_read_bytes=buffer.IoReadTransferCount,
        io_write_bytes=buffer.IoWriteTransferCount,
        io_other_bytes=buffer.IoOtherTransferCount,
        io_read_ops=buffer.IoReadOperationCount,
        io_write_ops=buffer.IoWriteOperationCount,
        io_other_ops=buffer.IoOtherOperationCount,
        available_pages=buffer.AvailablePages,
        committed_pages=buffer.CommittedPages,
        commit_limit_pages=buffer.CommitLimit,
        peak_commit_pages=buffer.PeakCommitment,
        page_faults=buffer.PageFaultCount,
        demand_zero_faults=buffer.DemandZeroCount,
        page_reads=buffer.PageReadCount,
        page_read_ios=buffer.PageReadIoCount,
        dirty_writes=buffer.DirtyPagesWriteCount,
        mapped_writes=buffer.MappedPagesWriteCount,
        paged_pool_pages=buffer.PagedPoolPages,
        nonpaged_pool_pages=buffer.NonPagedPoolPages,
        paged_pool_allocs=buffer.PagedPoolAllocs,
        paged_pool_frees=buffer.PagedPoolFrees,
        nonpaged_pool_allocs=buffer.NonPagedPoolAllocs,
        nonpaged_pool_frees=buffer.NonPagedPoolFrees,
        free_system_ptes=buffer.FreeSystemPtes,
        context_switches=buffer.ContextSwitches,
        system_calls=buffer.SystemCalls)


def system_rates(before: Optional[SystemCounters],
                 after: Optional[SystemCounters]) -> SystemRates:
    """Per-second figures between two readings.

    An empty `SystemRates` -- every field `None` -- when either reading is
    missing or no time passed. The counters are 32-bit and do wrap on a
    long-running machine; a field that went backwards reports `None` for
    that tick rather than a negative rate or a 4-billion spike.
    """
    if before is None or after is None:
        return SystemRates()
    elapsed = after.at - before.at
    if elapsed <= 0:
        return SystemRates()

    def rate(name: str) -> Optional[float]:
        moved = getattr(after, name) - getattr(before, name)
        if moved < 0:
            return None
        return moved / elapsed

    return SystemRates(
        io_read_bps=rate("io_read_bytes"),
        io_write_bps=rate("io_write_bytes"),
        io_other_bps=rate("io_other_bytes"),
        io_read_ops=rate("io_read_ops"),
        io_write_ops=rate("io_write_ops"),
        io_other_ops=rate("io_other_ops"),
        page_faults=rate("page_faults"),
        page_reads=rate("page_reads"),
        context_switches=rate("context_switches"),
        system_calls=rate("system_calls"))
