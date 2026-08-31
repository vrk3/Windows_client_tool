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


def format_stamp(entry) -> str:
    """The one implementation of "how a timestamp is written out" --
    LogModel.data()'s TIME column calls this too, so the exported file and
    the table someone actually looked at cannot quietly disagree.

    UNKNOWN_TIME (a continuation line with no timestamp of its own) is
    blank rather than a fabricated date; milliseconds are shown only when
    the log actually wrote them, since a whole-second log like CBS would
    otherwise get a `.000` on every row that reads as a measurement rather
    than as padding.
    """
    if entry.timestamp == UNKNOWN_TIME:
        return ""
    if entry.raw.get("subsecond"):
        return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _row(entry):
    return (format_stamp(entry), entry.level, entry.source,
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


def as_markdown(entries) -> str:
    """A table that pastes into a ticket without reformatting.

    Pipes are escaped and newlines folded: a CBS message can contain both,
    and either one unescaped turns a single row into a broken table for
    every row after it.
    """
    lines = ["| " + " | ".join(COLUMNS) + " |",
             "|" + "|".join(["---"] * len(COLUMNS)) + "|"]
    for entry in entries or ():
        cells = []
        for value in _row(entry):
            value = str(value).replace("|", r"\|")
            # A stack trace is one entry; a raw newline would end the row.
            value = value.replace("\n", " ").replace("\r", " ")
            cells.append(value)
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


#: Severity colours for the exported page, taken from the same values the
#: pane uses. Hardcoded rather than imported from `semantic_colors` because
#: this module has no Qt and no theme: an exported file has one appearance,
#: and it is read on someone else's machine.
_HTML_SEVERITY = {
    "Error": "#b3261e",
    "Warning": "#8a5300",
    "Info": "#00639c",
}


def as_html(entries) -> str:
    """The view as a self-contained page, colours intact.

    The text and CSV writers drop exactly the information the colouring was
    added to carry -- which rows are failures. This keeps it, so what someone
    is sent looks like what was on screen.
    """
    from html import escape

    styles = "\n".join(
        f"    td.{level} {{ color: {colour}; }}"
        for level, colour in _HTML_SEVERITY.items())
    rows = []
    for entry in entries or ():
        stamp, level, component, thread, message = _row(entry)
        safe_level = escape(level or "")
        rows.append(
            f"  <tr><td>{escape(stamp)}</td>"
            f"<td class=\"{safe_level}\">{safe_level}</td>"
            f"<td>{escape(component or '')}</td>"
            f"<td>{escape(thread or '')}</td>"
            f"<td>{escape(message or '')}</td></tr>")
    heads = "".join(f"<th>{escape(name)}</th>" for name in COLUMNS)
    return (
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">\n"
        "<title>Log Viewer export</title>\n<style>\n"
        "    body { font: 13px Consolas, monospace; }\n"
        "    table { border-collapse: collapse; }\n"
        "    td, th { padding: 1px 8px; text-align: left; "
        "vertical-align: top; }\n"
        "    th { border-bottom: 1px solid #999; }\n"
        f"{styles}\n"
        "</style></head>\n<body>\n"
        f"<p>{escape(_HEADER.lstrip('# '))}</p>\n"
        f"<table>\n  <tr>{heads}</tr>\n" + "\n".join(rows) +
        "\n</table>\n</body></html>\n")


def as_csv(entries) -> str:
    buffer = io.StringIO()
    # lineterminator explicitly: csv defaults to \r\n, which lands as blank
    # lines between rows once the file is opened as text on Windows.
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(COLUMNS)
    for entry in entries or ():
        writer.writerow(_row(entry))
    return buffer.getvalue()
