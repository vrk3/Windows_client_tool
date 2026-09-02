r"""Every process on the machine, in one syscall.

`NtQuerySystemInformation(SystemProcessInformation)` returns a packed array
covering every process at once: identity, memory, I/O, handles, threads and
CPU time. It is what Task Manager and Process Explorer are built on, and the
reason they can repaint forty live columns once a second.

Measured here, 278 processes, best of 5:

    psutil.process_iter (10 attrs)      667.9 ms
    psutil.process_iter (17 attrs)     1081.9 ms
    NtQuerySystemInformation             2.6 ms

257x, for more data. The existing `ProcessCollector` polls `process_iter` at
1 Hz and so burns roughly two thirds of a core doing nothing else; asked for
the Details tab's columns it would need 1.08 s per 1 s tick and never
converge. Every HOT field therefore comes from here. Anything needing a
per-process open (path, command line, user, signature) is cold, resolved once
per pid and cached -- see `details.py`.

No Qt in this file, the same split `scan/` and `store/` keep in TreeSize: it
runs with no display and no elevation.

Two things about this API that are easy to get wrong, both of which produce a
plausible-looking wrong answer rather than an error:

- **The buffer never fits on the first try.** The call answers
  `STATUS_INFO_LENGTH_MISMATCH` and reports the size it wanted, but that size
  is already stale by the time it returns -- processes start. A single retry
  is not enough; this loops, and a caller that ignored the status would get
  the first N processes and read it as a quiet machine.
- **The struct layout is not a documented contract.** A field in the wrong
  place still parses, and every number after it is nonsense. The tests pin
  landmarks (pid 4 is "System", our own working set is plausible) precisely
  because a misalignment is otherwise invisible.
"""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass

SystemProcessInformation = 5
STATUS_SUCCESS = 0
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004

#: Pid 0 has a NULL ImageName. Task Manager shows CPU idle against this row,
#: so it is named here rather than dropped or left blank.
IDLE_PROCESS_NAME = "System Idle Process"

_ntdll = ctypes.WinDLL("ntdll")
_ntdll.NtQuerySystemInformation.restype = wintypes.LONG
_ntdll.NtQuerySystemInformation.argtypes = [
    wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG),
]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]


class _SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    """The x64 layout ntdll returns.

    Ordered exactly as the kernel writes it -- the names come from the public
    symbols, and the order is the contract. Do not "tidy" this.
    """

    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_longlong),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", ctypes.c_ulonglong),
        ("CreateTime", ctypes.c_longlong),
        ("UserTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
        ("ImageName", _UNICODE_STRING),
        ("BasePriority", ctypes.c_long),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_void_p),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivatePageCount", ctypes.c_size_t),
        ("ReadOperationCount", ctypes.c_longlong),
        ("WriteOperationCount", ctypes.c_longlong),
        ("OtherOperationCount", ctypes.c_longlong),
        ("ReadTransferCount", ctypes.c_longlong),
        ("WriteTransferCount", ctypes.c_longlong),
        ("OtherTransferCount", ctypes.c_longlong),
    ]


@dataclass(frozen=True, slots=True)
class ProcessRaw:
    """One process as the kernel described it at one instant.

    Frozen: a snapshot is a reading of a moment, and the rate maths compares
    two of them. Something that edited one in place would be rewriting the
    past half of that subtraction.

    Times are kept in the units the syscall speaks -- 100-nanosecond ticks
    for kernel/user time, Windows FILETIME for creation. Converting here
    would hide which unit it is and lose precision the rate maths wants.
    """

    pid: int
    ppid: int
    name: str
    threads: int
    handles: int
    session: int
    base_priority: int
    working_set: int
    #: Task Manager's "Memory (private working set)" column -- the one it
    #: labels simply "Memory". NOT the working set, which counts shared
    #: pages every process mapping a DLL is charged for.
    working_set_private: int
    peak_working_set: int
    private_bytes: int
    peak_pagefile: int
    peak_virtual_size: int
    paged_pool: int
    nonpaged_pool: int
    pagefile: int
    virtual_size: int
    page_faults: int
    hard_faults: int
    kernel_time: int
    user_time: int
    cycles: int
    create_time: int
    read_bytes: int
    write_bytes: int
    other_bytes: int
    read_ops: int
    write_ops: int
    other_ops: int


def system_processes(initial_size: int = 512 * 1024):
    """Every process on the machine, as of now.

    `initial_size` exists for the test that proves the retry loop grows the
    buffer rather than truncating -- a short read would look like a machine
    with fewer processes, not like a failure.
    """
    buffer = _query(initial_size)
    return _parse(buffer)


def _query(size: int) -> ctypes.Array:
    """The call, with the growth loop.

    The size the kernel asks for is stale as soon as it returns: processes
    start between the two calls. So this loops rather than retrying once, and
    always asks for more than it was told.
    """
    while True:
        buffer = ctypes.create_string_buffer(size)
        needed = wintypes.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(
            SystemProcessInformation, buffer, size, ctypes.byref(needed))
        if status == STATUS_SUCCESS:
            return buffer
        if (status & 0xFFFFFFFF) != STATUS_INFO_LENGTH_MISMATCH:
            raise OSError(
                f"NtQuerySystemInformation failed: 0x{status & 0xFFFFFFFF:08X}")
        # Headroom on purpose: asking for exactly what it wanted loses the
        # race against a process starting, and spins.
        size = max(needed.value + 64 * 1024, size * 2)


def _parse(buffer: ctypes.Array):
    """Walk the packed array.

    Entries are chained by byte offset, not indexed, and the last one carries
    `NextEntryOffset == 0`. A zero offset anywhere else would loop forever on
    the same entry, so the walk is bounded by the buffer as well.
    """
    out = []
    offset = 0
    limit = len(buffer)
    while offset < limit:
        entry = _SYSTEM_PROCESS_INFORMATION.from_buffer(buffer, offset)
        out.append(_row(entry))
        step = entry.NextEntryOffset
        if step == 0:
            break
        offset += step
    return out


def _row(entry) -> ProcessRaw:
    return ProcessRaw(
        pid=entry.UniqueProcessId or 0,
        ppid=entry.InheritedFromUniqueProcessId or 0,
        name=_image_name(entry),
        threads=entry.NumberOfThreads,
        handles=entry.HandleCount,
        session=entry.SessionId,
        base_priority=entry.BasePriority,
        working_set=entry.WorkingSetSize,
        working_set_private=entry.WorkingSetPrivateSize,
        peak_working_set=entry.PeakWorkingSetSize,
        private_bytes=entry.PrivatePageCount,
        peak_pagefile=entry.PeakPagefileUsage,
        peak_virtual_size=entry.PeakVirtualSize,
        paged_pool=entry.QuotaPagedPoolUsage,
        nonpaged_pool=entry.QuotaNonPagedPoolUsage,
        pagefile=entry.PagefileUsage,
        virtual_size=entry.VirtualSize,
        page_faults=entry.PageFaultCount,
        hard_faults=entry.HardFaultCount,
        kernel_time=entry.KernelTime,
        user_time=entry.UserTime,
        cycles=entry.CycleTime,
        create_time=entry.CreateTime,
        read_bytes=entry.ReadTransferCount,
        write_bytes=entry.WriteTransferCount,
        other_bytes=entry.OtherTransferCount,
        read_ops=entry.ReadOperationCount,
        write_ops=entry.WriteOperationCount,
        other_ops=entry.OtherOperationCount,
    )


def _image_name(entry) -> str:
    """The process name, and a real one for pid 0.

    `Length` is in BYTES while `wstring_at` counts CHARACTERS, so the halving
    is not optional -- without it the name runs past its own buffer into
    whatever follows.
    """
    name = entry.ImageName
    if name.Buffer and name.Length:
        return ctypes.wstring_at(name.Buffer, name.Length // 2)
    return IDLE_PROCESS_NAME
