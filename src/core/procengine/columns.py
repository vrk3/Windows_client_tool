"""Every column the Details table can show, declared once.

Forty columns written as forty branches of a `data()` method is how a table
model becomes unmaintainable. Each column is a small record instead: where its
value comes from, how it is rendered, how it sorts, and which side it aligns
to. Adding one is adding a row to a list.

Two rules run through all of them, and both come from this project's standing
one that a refusal is not an answer:

- **The sort key is the VALUE, never the rendered text.** The rule TreeSize
  already pays for: sort "9 B" and "10 GB" as strings and the byte lands
  above the gigabyte.
- **An unknown renders as an em dash with the reason in its tooltip, never as
  zero or blank.** Unelevated, 133 of this machine's 275 processes refuse
  their path -- as `0` or `""` the table would state, in 133 rows, things
  about those processes that are not true.

Qt-free: these are functions over `ProcessInfo`, so the whole column set is
testable without a display.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, List, Optional

#: What a value we do not have looks like. Not "" and not 0 -- both of those
#: read as facts about the process.
UNKNOWN = "—"

#: Windows counts FILETIME from 1601-01-01 UTC, not the Unix epoch.
_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

#: CPU times arrive in 100-nanosecond ticks.
_HUNDRED_NS = 10_000_000

LEFT = "left"
RIGHT = "right"


@dataclass(frozen=True)
class Column:
    """One column: where the number comes from and how it should look."""

    key: str
    title: str
    group: str
    value: Callable[[Any], Any]
    render: Callable[[Any], str]
    align: str = LEFT
    default: bool = False
    #: Why the value is missing, when it is. Only the columns that can be
    #: refused carry one; the rest are simply absent for that process.
    reason: Optional[Callable[[Any], Optional[str]]] = None
    description: str = ""


# ---- formatters ---------------------------------------------------------

def fmt_bytes(value) -> str:
    if value is None:
        return UNKNOWN
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            precision = 0 if unit == "B" else 1
            return f"{size:,.{precision}f} {unit}"
        size /= 1024
    return f"{size:,.1f} TB"


def fmt_rate(value) -> str:
    """Bytes per second. Task Manager shows a dash rather than "0 B/s" for
    an idle process, because a column of zeros is noise."""
    if value is None:
        return UNKNOWN
    if value < 1:
        return ""
    return f"{fmt_bytes(value)}/s"


def fmt_percent(value) -> str:
    if value is None:
        return UNKNOWN
    if value < 0.05:
        # Task Manager blanks a process using no measurable CPU rather than
        # printing 0.0 down the whole column.
        return ""
    return f"{value:.1f}"


def fmt_count(value) -> str:
    return UNKNOWN if value is None else f"{value:,}"


def fmt_text(value) -> str:
    return UNKNOWN if value in (None, "") else str(value)


def fmt_bool(value) -> str:
    if value is None:
        return UNKNOWN
    return "Yes" if value else "No"


def fmt_cpu_time(value) -> str:
    """Kernel + user time as h:mm:ss, the way Task Manager shows it."""
    if value is None:
        return UNKNOWN
    seconds = value / _HUNDRED_NS
    return str(timedelta(seconds=int(seconds)))


def fmt_start_time(value) -> str:
    if not value:
        return UNKNOWN
    try:
        stamp = _FILETIME_EPOCH + timedelta(microseconds=value // 10)
        return stamp.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        # Pid 0 and pid 4 report a create time of 0 or the boot instant;
        # neither is worth an exception.
        return UNKNOWN


# ---- the columns --------------------------------------------------------

def _raw(field, default=None):
    return lambda info: getattr(info.raw, field, default)


def _detail(field):
    return lambda info: getattr(info.details, field, None)


def _rate(field):
    return lambda info: getattr(info.rates, field, None)


def _reason(field):
    return lambda info: getattr(info.details, field, None)


COLUMNS: List[Column] = [
    # ---- identity ----
    Column("name", "Name", "Identity", _raw("name"), fmt_text,
           default=True, description="The process's image name."),
    Column("pid", "PID", "Identity", _raw("pid"), fmt_count, RIGHT,
           default=True, description="Process identifier."),
    Column("ppid", "Parent PID", "Identity", _raw("ppid"), fmt_count, RIGHT,
           description="The pid that created this one, if it still exists."),
    Column("user", "User name", "Identity", _detail("user"), fmt_text,
           default=True, reason=_reason("user_error"),
           description="The account the process runs as."),
    Column("session", "Session ID", "Identity", _raw("session"), fmt_count,
           RIGHT, description="0 is services; 1 and up are logged-on users."),
    Column("description", "Description", "Identity", _detail("description"),
           fmt_text, default=True,
           description="From the binary's version resource."),
    Column("company", "Company name", "Identity", _detail("company"),
           fmt_text, description="From the binary's version resource."),
    Column("path", "Image path name", "Identity", _detail("path"), fmt_text,
           reason=_reason("path_error"),
           description="Full path to the executable."),
    Column("cmdline", "Command line", "Identity", _detail("cmdline"),
           fmt_text, reason=_reason("cmdline_error"),
           description="The arguments the process was started with."),
    Column("architecture", "Platform", "Identity", _detail("architecture"),
           fmt_text, description="x64, x86 or ARM64."),
    Column("elevated", "Elevated", "Identity", _detail("elevated"), fmt_bool,
           description="Whether the process holds an elevated token."),
    Column("integrity", "Integrity", "Identity", _detail("integrity"),
           fmt_text,
           description="Untrusted, Low, Medium, High or System."),
    Column("start_time", "Start time", "Identity", _raw("create_time"),
           fmt_start_time, description="When the process started."),

    # ---- cpu ----
    Column("cpu", "CPU", "CPU", _rate("cpu_percent"), fmt_percent, RIGHT,
           default=True,
           description="Share of the whole machine, as Task Manager counts it."),
    Column("cpu_time", "CPU time", "CPU",
           lambda info: info.raw.kernel_time + info.raw.user_time,
           fmt_cpu_time, RIGHT,
           description="Total processor time since the process started."),
    Column("kernel_time", "Kernel time", "CPU", _raw("kernel_time"),
           fmt_cpu_time, RIGHT, description="Time spent in kernel mode."),
    Column("user_time", "User time", "CPU", _raw("user_time"), fmt_cpu_time,
           RIGHT, description="Time spent in user mode."),
    Column("cycles", "Cycles", "CPU", _raw("cycles"), fmt_count, RIGHT,
           description="Raw cycle count, which does not vary with clock speed."),
    Column("base_priority", "Base priority", "CPU", _raw("base_priority"),
           fmt_count, RIGHT, description="Scheduling priority class."),
    Column("threads", "Threads", "CPU", _raw("threads"), fmt_count, RIGHT,
           default=True, description="Threads currently in the process."),

    # ---- memory ----
    Column("memory", "Memory", "Memory", _raw("working_set_private"),
           fmt_bytes, RIGHT, default=True,
           description="Private working set -- the column Task Manager "
                       "labels simply Memory."),
    Column("working_set", "Working set", "Memory", _raw("working_set"),
           fmt_bytes, RIGHT,
           description="All physical memory mapped, shared pages included."),
    Column("peak_working_set", "Peak working set", "Memory",
           _raw("peak_working_set"), fmt_bytes, RIGHT,
           description="The most physical memory it has held."),
    Column("commit", "Commit size", "Memory", _raw("pagefile"), fmt_bytes,
           RIGHT, description="Virtual memory committed to the process."),
    Column("peak_commit", "Peak commit size", "Memory", _raw("peak_pagefile"),
           fmt_bytes, RIGHT, description="The most it has committed."),
    Column("private_bytes", "Private bytes", "Memory", _raw("private_bytes"),
           fmt_bytes, RIGHT,
           description="Memory this process alone can address."),
    Column("paged_pool", "Paged pool", "Memory", _raw("paged_pool"),
           fmt_bytes, RIGHT, description="Kernel memory that can page out."),
    Column("nonpaged_pool", "NP pool", "Memory", _raw("nonpaged_pool"),
           fmt_bytes, RIGHT, description="Kernel memory that cannot page out."),
    Column("virtual_size", "Virtual size", "Memory", _raw("virtual_size"),
           fmt_bytes, RIGHT, description="Total address space reserved."),
    Column("peak_virtual_size", "Peak virtual size", "Memory",
           _raw("peak_virtual_size"), fmt_bytes, RIGHT,
           description="The most address space it has reserved."),
    Column("page_faults", "Page faults", "Memory", _raw("page_faults"),
           fmt_count, RIGHT, description="Faults since the process started."),
    Column("hard_faults", "Hard faults", "Memory", _raw("hard_faults"),
           fmt_count, RIGHT,
           description="Faults that had to reach the disk."),

    # ---- i/o ----
    Column("disk_read", "Disk read", "I/O", _rate("read_bps"), fmt_rate,
           RIGHT, default=True, description="Read rate, now."),
    Column("disk_write", "Disk write", "I/O", _rate("write_bps"), fmt_rate,
           RIGHT, default=True, description="Write rate, now."),
    Column("disk_other", "Other", "I/O", _rate("other_bps"), fmt_rate, RIGHT,
           description="Non-read, non-write I/O rate, mostly device control."),
    Column("read_bytes", "I/O read bytes", "I/O", _raw("read_bytes"),
           fmt_bytes, RIGHT, description="Total read since it started."),
    Column("write_bytes", "I/O write bytes", "I/O", _raw("write_bytes"),
           fmt_bytes, RIGHT, description="Total written since it started."),
    Column("other_bytes", "I/O other bytes", "I/O", _raw("other_bytes"),
           fmt_bytes, RIGHT, description="Total other I/O since it started."),
    Column("read_ops", "I/O reads", "I/O", _raw("read_ops"), fmt_count,
           RIGHT, description="Read operations since it started."),
    Column("write_ops", "I/O writes", "I/O", _raw("write_ops"), fmt_count,
           RIGHT, description="Write operations since it started."),
    Column("other_ops", "I/O other", "I/O", _raw("other_ops"), fmt_count,
           RIGHT, description="Other operations since it started."),

    # ---- handles ----
    Column("handles", "Handles", "Handles", _raw("handles"), fmt_count,
           RIGHT, default=True, description="Open kernel handles."),
]

BY_KEY = {column.key: column for column in COLUMNS}

#: The columns shown before anyone customises anything, in this order.
DEFAULT_KEYS = [column.key for column in COLUMNS if column.default]

GROUPS = list(dict.fromkeys(column.group for column in COLUMNS))


def cell_text(column: Column, info) -> str:
    """What the cell shows."""
    return column.render(column.value(info))


def cell_tooltip(column: Column, info) -> Optional[str]:
    """Why the cell is empty, when it is.

    This is where a refusal becomes visible. The cell itself has room for a
    dash; the reason goes here, so "access denied" is one hover away rather
    than lost.
    """
    if column.value(info) is not None:
        return None
    if column.reason is None:
        return None
    reason = column.reason(info)
    return f"{column.title}: {reason}" if reason else None


def sort_key(column: Column, info):
    """A key that orders on the value, with unknowns last.

    Returns a `(known, value)` pair so `None` never has to compare against a
    number -- which raises, inside a Qt sort, inside a reimplemented virtual,
    which is fatal rather than catchable.
    """
    value = column.value(info)
    if value is None:
        return (1, "")
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (0, str(value).lower())
