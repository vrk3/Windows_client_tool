r"""Open handles, per process -- the lower pane's Handles tab.

`NtQuerySystemInformation(SystemExtendedHandleInformation)` returns every
handle on the machine in one call: **169,153 handles in 8 ms** here. There
is no per-process variant, so a pane showing one process filters the whole
list, which is still far cheaper than any alternative.

Three things this module exists to get right, each of which the previous
implementation got wrong:

**The status code is unsigned.** `NtQuerySystemInformation` answers its
first call with `STATUS_INFO_LENGTH_MISMATCH` by design -- you cannot know
the buffer size in advance -- and the caller grows the buffer and retries.
With no `restype` declared, ctypes hands back a SIGNED int, so the status
reads as `-1073741820`, never equals `0xC0000004`, and the retry never
fires. The previous handle view had exactly this, which is why its tab
showed **zero handles for every process, always**: the kernel said this
process holds 185 and the pane said 0.

**The pid field must be full width.** The classic
`SystemHandleInformation` (class 16) stores `UniqueProcessId` as a
`USHORT`. Windows pids are DWORDs; this machine is currently at 35,612 and
climbing, and past 65,535 that field silently wraps and attributes one
process's handles to another. Class 64 has a full-width pid for the same
8 ms, so there is no reason to use the narrow one.

**A name is not always available, and the reasons differ.** Of this
process's 138 handles: 93 could be duplicated (45 refused), and of those
only 34 have a name -- most kernel objects genuinely have none. "Refused",
"has no name" and "we ran out of time" are three different answers and
none of them is an empty string.

## What needs a driver

Process Explorer ships a signed kernel driver and this does not, so:

- **Handles in other users' processes** cannot be duplicated without
  `PROCESS_DUP_HANDLE`, which an unelevated process does not have over
  them. Those rows arrive with a type but no name.
- **`NtQueryObject(ObjectNameInformation)` can block for ever** on a
  synchronous named pipe whose peer never answers. There is no timeout
  parameter and no way to cancel it. The naming pass therefore runs under
  a deadline in a thread that can be abandoned -- see `HandleNamer`.

Qt-free, like the rest of the engine.
"""
import ctypes
import logging
import threading
from ctypes import wintypes
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ntdll = ctypes.WinDLL("ntdll")
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SystemExtendedHandleInformation = 64
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004
ObjectNameInformation = 1
ObjectTypeInformation = 2
DUPLICATE_SAME_ACCESS = 0x00000002
PROCESS_DUP_HANDLE = 0x0040

#: Stop growing the buffer here. 169k handles need ~7 MB; a machine needing
#: more than this has something badly wrong and an unbounded loop would
#: turn that into an out-of-memory rather than a message.
MAX_BUFFER = 128 * 1024 * 1024

#: How long the whole naming pass for one process may take. Generous: the
#: measured cost is 0.4 ms for 93 handles, so reaching this means something
#: is blocked rather than slow.
NAME_DEADLINE_SECONDS = 2.0

#: Declared, and the reason is the whole first paragraph of this module.
_ntdll.NtQuerySystemInformation.restype = ctypes.c_ulong
_ntdll.NtQuerySystemInformation.argtypes = [
    ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
    ctypes.POINTER(wintypes.ULONG)]
_ntdll.NtQueryObject.restype = ctypes.c_ulong
_ntdll.NtQueryObject.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.ULONG,
    ctypes.POINTER(wintypes.ULONG)]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                  wintypes.DWORD]
_kernel32.DuplicateHandle.restype = wintypes.BOOL
_kernel32.DuplicateHandle.argtypes = [
    wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL,
    wintypes.DWORD]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE


class _EXTENDED_HANDLE(ctypes.Structure):
    _fields_ = [
        ("Object", ctypes.c_void_p),
        ("UniqueProcessId", ctypes.c_size_t),
        ("HandleValue", ctypes.c_size_t),
        ("GrantedAccess", wintypes.ULONG),
        ("CreatorBackTraceIndex", wintypes.USHORT),
        ("ObjectTypeIndex", wintypes.USHORT),
        ("HandleAttributes", wintypes.ULONG),
        ("Reserved", wintypes.ULONG),
    ]


class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]


@dataclass(frozen=True, slots=True)
class HandleEntry:
    """One open handle, as the kernel reports it."""

    pid: int
    value: int
    object_address: int
    granted_access: int
    type_index: int
    attributes: int


@dataclass(frozen=True, slots=True)
class HandleInfo:
    """One handle, with whatever we could learn about it."""

    entry: HandleEntry
    type_name: Optional[str] = None
    name: Optional[str] = None
    #: Why `name` is None. Never collapsed into an empty string: "we were
    #: refused", "this object has no name" and "the query did not return"
    #: are three different facts about a row.
    unavailable: Optional[str] = None

    @property
    def pid(self) -> int:
        return self.entry.pid

    @property
    def value(self) -> int:
        return self.entry.value


def system_handles(pid: Optional[int] = None) -> List[HandleEntry]:
    """Every open handle on the machine, or just one process's.

    One call for the whole machine either way -- there is no per-process
    class -- so filtering here costs nothing over asking.
    """
    size = 0x10000
    while size <= MAX_BUFFER:
        buffer = (ctypes.c_byte * size)()
        needed = wintypes.ULONG(0)
        status = _ntdll.NtQuerySystemInformation(
            SystemExtendedHandleInformation, buffer, size,
            ctypes.byref(needed))
        if status == STATUS_INFO_LENGTH_MISMATCH:
            # Grow past what it asked for: the count moves between calls on
            # a live machine, and matching it exactly loops for ever.
            size = max(size * 2, needed.value + 0x10000)
            continue
        if status != 0:
            logger.warning("The handle table was refused: status %#x", status)
            return []
        return _parse(buffer, pid)
    logger.warning("The handle table did not fit in %d bytes", MAX_BUFFER)
    return []


def _parse(buffer, pid: Optional[int]) -> List[HandleEntry]:
    pointer = ctypes.sizeof(ctypes.c_size_t)
    count = ctypes.cast(buffer,
                        ctypes.POINTER(ctypes.c_size_t)).contents.value
    base = ctypes.addressof(buffer) + 2 * pointer
    stride = ctypes.sizeof(_EXTENDED_HANDLE)
    out = []
    for index in range(count):
        raw = _EXTENDED_HANDLE.from_address(base + index * stride)
        if pid is not None and raw.UniqueProcessId != pid:
            continue
        out.append(HandleEntry(
            pid=raw.UniqueProcessId,
            value=raw.HandleValue,
            object_address=raw.Object or 0,
            granted_access=raw.GrantedAccess,
            type_index=raw.ObjectTypeIndex,
            attributes=raw.HandleAttributes))
    return out


class HandleNamer:
    """Turns handle entries into named rows, under a deadline.

    Names come from duplicating each handle into this process and asking
    `NtQueryObject`. Two costs are bounded here rather than trusted:

    - **The type-name cache.** A machine has a couple of dozen object
      types and a hundred thousand handles, so the index is resolved once
      per type and reused. Measured: 16 distinct types across this
      process's 138 handles.
    - **The naming deadline.** `ObjectNameInformation` has no timeout and
      cannot be cancelled; on a synchronous pipe with no peer it never
      returns. The pass therefore runs on a daemon thread, and if that
      thread does not finish in time the rows named so far are returned
      and the rest say why. Abandoning the thread leaks it -- one per
      genuinely blocked handle -- which is the cost of not shipping a
      driver, and is stated rather than hidden.
    """

    def __init__(self) -> None:
        self._types: Dict[int, Optional[str]] = {}

    def describe(self, entries: List[HandleEntry],
                 deadline: float = NAME_DEADLINE_SECONDS
                 ) -> Tuple[List[HandleInfo], Optional[str]]:
        """`(rows, note)` -- the note explains any gap, or is `None`."""
        if not entries:
            return [], None
        pid = entries[0].pid
        source = _kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
        if not source:
            # Without PROCESS_DUP_HANDLE nothing can be duplicated, so the
            # rows carry their type index and access mask and nothing else.
            return ([HandleInfo(entry=entry,
                                unavailable="this process cannot be opened "
                                            "for handle duplication")
                     for entry in entries],
                    "Handle names need PROCESS_DUP_HANDLE on the target, "
                    "which this process does not have. Running elevated "
                    "resolves most of them; the rest need the kernel "
                    "driver Process Explorer ships.")

        rows: List[HandleInfo] = []
        finished = threading.Event()

        def work():
            try:
                for entry in entries:
                    rows.append(self._one(source, entry))
            except Exception as error:  # noqa: BLE001
                logger.debug("Naming handles for %d failed: %s", pid, error)
            finally:
                finished.set()

        worker = threading.Thread(target=work, daemon=True,
                                  name=f"handle-names-{pid}")
        worker.start()
        finished.wait(deadline)

        if not finished.is_set():
            done = list(rows)
            remaining = entries[len(done):]
            done.extend(HandleInfo(
                entry=entry,
                type_name=self._types.get(entry.type_index),
                unavailable="naming stopped: a handle query did not return")
                for entry in remaining)
            return done, (
                f"Naming stopped after {deadline:.0f}s with "
                f"{len(remaining)} handles left. NtQueryObject blocks for "
                f"ever on a synchronous pipe whose peer never answers, and "
                f"it cannot be cancelled -- Process Explorer reads these "
                f"through its kernel driver instead.")
        _kernel32.CloseHandle(source)
        return rows, None

    def _one(self, source, entry: HandleEntry) -> HandleInfo:
        duplicate = wintypes.HANDLE()
        ok = _kernel32.DuplicateHandle(
            source, wintypes.HANDLE(entry.value),
            _kernel32.GetCurrentProcess(), ctypes.byref(duplicate),
            0, False, DUPLICATE_SAME_ACCESS)
        if not ok:
            return HandleInfo(entry=entry,
                              type_name=self._types.get(entry.type_index),
                              unavailable="the handle could not be duplicated")
        try:
            kind = self._type_of(duplicate, entry.type_index)
            name = _query_string(duplicate, ObjectNameInformation)
            if name is None:
                return HandleInfo(entry=entry, type_name=kind,
                                  unavailable="the object could not be named")
            if name == "":
                return HandleInfo(entry=entry, type_name=kind,
                                  unavailable="this object has no name")
            return HandleInfo(entry=entry, type_name=kind, name=name)
        finally:
            _kernel32.CloseHandle(duplicate)

    def _type_of(self, handle, index: int) -> Optional[str]:
        if index in self._types:
            return self._types[index]
        found = _query_string(handle, ObjectTypeInformation) or None
        self._types[index] = found
        return found


def _query_string(handle, klass: int, size: int = 4096) -> Optional[str]:
    """One `NtQueryObject` string, `""` for a present-but-empty name."""
    buffer = (ctypes.c_byte * size)()
    needed = wintypes.ULONG(0)
    status = _ntdll.NtQueryObject(handle, klass, buffer, size,
                                  ctypes.byref(needed))
    if status != 0:
        return None
    text = _UNICODE_STRING.from_address(ctypes.addressof(buffer))
    if not text.Buffer or not text.Length:
        return ""
    return ctypes.wstring_at(text.Buffer, text.Length // 2)


def access_flags(granted: int, type_name: Optional[str]) -> str:
    """The access mask as the rights it grants, where they are generic.

    Only the type-independent bits are decoded. A `File`'s 0x0001 is
    FILE_READ_DATA and a `Key`'s is KEY_QUERY_VALUE, and guessing wrong
    would put a confident wrong word next to a number that was right.
    """
    generic = [
        (0x00010000, "DELETE"),
        (0x00020000, "READ_CONTROL"),
        (0x00040000, "WRITE_DAC"),
        (0x00080000, "WRITE_OWNER"),
        (0x00100000, "SYNCHRONIZE"),
    ]
    names = [label for bit, label in generic if granted & bit]
    specific = granted & 0xFFFF
    if specific:
        names.append(f"specific {specific:#06x}")
    return " | ".join(names) if names else "none"
