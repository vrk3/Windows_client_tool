"""Writers that get the filtered rows out of the viewer.

Both emit the PARSED view -- time, severity, component, thread, message --
rather than the original bytes. Keeping every original line would roughly
double the model's footprint at its 200,000-record cap, and rebuilding one
from `raw["line"]` is unreliable the moment the file is tail-capped,
followed, or read together with a rolled `.lo_` sibling. The original file
is always still on disk when a verbatim copy is what is wanted, and the text
header says as much so nobody is misled about what they are holding.

No Qt: the pane decides where the text goes, this decides what it says.
"""
import csv
import io

from .cmtrace_parser import UNKNOWN_TIME

COLUMNS = ("Time", "Severity", "Component", "Thread", "Message")

_HEADER = ("# Parsed view exported from the Log Viewer -- not a byte-for-byte "
           "copy of the log file.")


def _stamp(entry) -> str:
    if entry.timestamp == UNKNOWN_TIME:
        return ""
    if entry.raw.get("subsecond"):
        return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _row(entry):
    return (_stamp(entry), entry.level, entry.source,
            entry.raw.get("thread", ""), entry.message)


def as_text(entries, header: bool = True) -> str:
    """Aligned columns. `header=False` for the clipboard, where a provenance
    note is noise rather than context."""
    lines = [_HEADER] if header else []
    for entry in entries or ():
        stamp, level, component, thread, message = _row(entry)
        lines.append(f"{stamp:<23} {level:<8} {component:<8} "
                     f"{thread:<8} {message}".rstrip())
    return "\n".join(lines)


def as_csv(entries) -> str:
    buffer = io.StringIO()
    # lineterminator explicitly: csv defaults to \r\n, which lands as blank
    # lines between rows once the file is opened as text on Windows.
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for entry in entries or ():
        writer.writerow(_row(entry))
    return buffer.getvalue()
