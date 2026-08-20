"""CMTrace / ConfigMgr log parsing.

One record is `<![LOG[message]LOG]!>` followed by an attribute blob:

    <![LOG[Starting]LOG]!><time="13:45:12.345+000" date="08-20-2026"
      component="UpdatesHandler" context="" type="1" thread="1234"
      file="updateshandler.cpp:112">

`type` is what the colouring hangs off: 1 Info, 2 Warning, 3 Error.

Anything that is not CMTrace falls back to a best-effort line parse. A viewer
that shows nothing for an ordinary `.log` is worse than one that shows
uncoloured lines.

No Qt here, so the parsing rules are testable without a display -- the same
split the CBS and DISM parsers use.
"""
import re
from datetime import datetime

from core.types import LogEntry

#: A record whose date cannot be read still has its message. Losing the line
#: is the one outcome a log viewer must never produce, so a bad timestamp
#: costs the ordering and nothing else.
UNKNOWN_TIME = datetime.min

#: Only the head of a file is sniffed. Reading 300 MB to answer a yes/no
#: question is not a detector.
SNIFF_BYTES = 8192

_RECORD = re.compile(
    r"<!\[LOG\[(?P<message>.*?)\]LOG\]!>\s*<(?P<attrs>[^<>]*)>",
    re.DOTALL)
_ATTR = re.compile(r'(\w+)="([^"]*)"')

#: ConfigMgr writes 0/1 for informational, 2 warning, 3 error, and some
#: components use 4/5 for verbose. Anything else is shown rather than dropped.
_LEVELS = {"0": "Info", "1": "Info", "2": "Warning", "3": "Error",
           "4": "Debug", "5": "Debug"}

_PLAIN_TIME = re.compile(
    r"^\s*(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})")
_PLAIN_ERROR = re.compile(r"\b(error|fail(ed|ure)?|fatal|exception)\b", re.I)
_PLAIN_WARN = re.compile(r"\b(warn(ing)?|caution)\b", re.I)


def looks_like_cmtrace(text: str) -> bool:
    return "<![LOG[" in text[:SNIFF_BYTES]


def _timestamp(attrs: dict) -> datetime:
    """`date="08-20-2026"` plus `time="13:45:12.345+000"`.

    The trailing UTC offset is KEPT but never applied. CMTrace shows the wall
    clock the log was written with; re-basing every line onto local time makes
    it disagree with every other log on the box, and with whatever the person
    on the phone is reading out.
    """
    date_text = attrs.get("date", "")
    time_text = attrs.get("time", "")
    clock = re.split(r"[+-]", time_text, maxsplit=1)[0]
    for date_format in ("%m-%d-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        for time_format in ("%H:%M:%S.%f", "%H:%M:%S"):
            try:
                return datetime.strptime(f"{date_text} {clock}",
                                         f"{date_format} {time_format}")
            except ValueError:
                continue
    return UNKNOWN_TIME


def _offset(time_text: str) -> str:
    match = re.search(r"([+-]\d+)$", time_text or "")
    return match.group(1) if match else ""


def parse_cmtrace(text: str) -> list:
    entries = []
    for match in _RECORD.finditer(text):
        attrs = dict(_ATTR.findall(match.group("attrs")))
        if not attrs:
            # A `<...>` that carries no key="value" pair is not an attribute
            # blob; the record is malformed and half a record is not an entry.
            continue
        raw = dict(attrs)
        raw["utc_offset"] = _offset(attrs.get("time", ""))
        entries.append(LogEntry(
            timestamp=_timestamp(attrs),
            source=attrs.get("component", ""),
            level=_LEVELS.get(attrs.get("type", ""), "Info"),
            message=match.group("message"),
            raw=raw,
        ))
    return entries


def parse_plain(text: str) -> list:
    """Best effort for anything that is not CMTrace."""
    entries = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        stamp = UNKNOWN_TIME
        match = _PLAIN_TIME.match(line)
        if match:
            try:
                stamp = datetime(*(int(part) for part in match.groups()))
            except ValueError:
                stamp = UNKNOWN_TIME
        if _PLAIN_ERROR.search(line):
            level = "Error"
        elif _PLAIN_WARN.search(line):
            level = "Warning"
        else:
            level = "Info"
        entries.append(LogEntry(timestamp=stamp, source="", level=level,
                                message=line.rstrip(),
                                raw={"line": str(number)}))
    return entries


def parse(text: str) -> list:
    """Records from `text`, picking the parser by sniffing it."""
    if not text:
        return []
    # Belt and braces: LogReader strips this, but `parse` is also called
    # directly, and U+FEFF is not whitespace to the timestamp regex.
    text = text.lstrip("\ufeff")
    return parse_cmtrace(text) if looks_like_cmtrace(text) else parse_plain(text)
