r"""Does the Log Viewer actually read this machine's own logs?

    .venv\Scripts\python.exe tools\log_viewer_real_check.py

2,525 passing tests never once opened a real log, and pointing the viewer at
the files Windows had already written found five defects in an afternoon:
a UTF-16 file rendered as NUL-laced garbage, severity guessed by word-match
while the line stated its own, dead Component and Thread columns, the
timestamp and severity repeated inside every message, and clipped lines with
no way to reach them. Every one of them RENDERS -- nothing raises, nothing
logs, so only looking at the output finds them.

This is the same shape as `tools/security_refusal_sweep.py`: run it after
touching the reader, the parser or the model, and it reports on whatever
logs this machine happens to have.

It reads. It never writes, and it needs no elevation -- the files below are
all world-readable.

What it reports per file, and what a bad answer looks like:

  decoded          -- a NUL beside every character means the encoding was
                      not sniffed. A FEW NULs are not that: Windows Update
                      leaves one 928-character run of them in the middle of
                      `ReportingEvents.log`, real padding between two real
                      records, so the test is the ratio and not the count.
  parser           -- which of the three parsers claimed the file.
  coverage         -- records vs non-blank lines. Records must not be LOST;
                      fewer records than lines means something was dropped.
  severity         -- lines whose stated severity disagrees with the old
                      word-match. This is the count of rows that used to be
                      coloured wrongly, so it is EXPECTED to be non-zero on
                      CBS and DISM; it is here to show the fix still bites.
  components       -- distinct non-empty components. 1 (`All` only) is the
                      dead-column symptom.
  threads          -- records carrying a thread id.
  prefix           -- messages that still start with their own timestamp.
                      Must be 0.
"""
import collections
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.log_viewer import cmtrace_parser                    # noqa: E402
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME       # noqa: E402
from modules.log_viewer.known_logs import (known_logs,           # noqa: E402
                                           newest_cbs_archive)
from modules.log_viewer.log_reader import LogReader              # noqa: E402


def _files():
    """Every log the viewer's own Open menu offers, newest archive included."""
    seen = []
    for log in known_logs():
        seen.append((log.label, log.path))
    archive = newest_cbs_archive()
    if archive:
        seen.append(("CBS — newest rolled archive", archive))
    return seen


def _parser_name(text):
    if cmtrace_parser.looks_like_cmtrace(text):
        return "cmtrace"
    if cmtrace_parser.looks_like_service_log(text):
        return "service"
    return "plain"


def check(label, path):
    started = time.monotonic()
    reader = LogReader(path)
    text = reader.read_new()
    read_seconds = time.monotonic() - started

    started = time.monotonic()
    entries = cmtrace_parser.parse(text)
    parse_seconds = time.monotonic() - started

    lines = [line for line in text.splitlines() if line.strip()]
    components = collections.Counter(e.source for e in entries if e.source)
    threads = sum(1 for e in entries if e.raw.get("thread"))
    no_time = sum(1 for e in entries if e.timestamp == UNKNOWN_TIME)
    continuations = sum(1 for e in entries if e.raw.get("continuation"))
    prefixed = sum(1 for e in entries
                   if cmtrace_parser._PLAIN_TIME.match(e.message))
    disagree = sum(1 for e in entries
                   if e.level == "Info"
                   and cmtrace_parser._PLAIN_ERROR.search(e.message))

    size = os.path.getsize(path)
    print(f"\n=== {label}")
    print(f"    {path}")
    print(f"    {size:,} bytes on disk; read {len(text):,} chars in "
          f"{read_seconds:.2f}s, parsed in {parse_seconds:.2f}s"
          + ("  [TAIL ONLY]" if reader.truncated else ""))
    # A UTF-16 file read as UTF-8 comes back with a NUL beside almost every
    # character -- a ratio near 0.5, not a handful.
    nuls = text.count("\x00")
    ratio = nuls / len(text) if text else 0
    decoded = ("OK" if ratio < 0.1
               else f"*** NUL beside {ratio:.0%} of characters: not decoded")
    if nuls and ratio < 0.1:
        decoded += f"  ({nuls:,} NUL characters of padding in the file)"
    print(f"    decoded          : {decoded}")
    print(f"    parser           : {_parser_name(text)}")
    print(f"    coverage         : {len(entries):,} records / {len(lines):,} "
          f"non-blank lines"
          + ("" if len(entries) >= len(lines) else "   *** RECORDS LOST"))
    print(f"    severity         : {disagree:,} Info lines the old word-match "
          f"would have called Error/Warning")
    # Only the two structured parsers can produce a component at all, so an
    # empty column is a defect there and simply the truth for a plain log --
    # a flag that cries wolf every run is a flag nobody reads.
    dead = not components and _parser_name(text) != "plain"
    print(f"    components       : {len(components)} "
          f"{dict(components.most_common(6))}"
          + ("   *** dead column" if dead else ""))
    print(f"    threads          : {threads:,} records with a thread id")
    threads_seen = collections.Counter(e.raw.get("thread", "")
                                       for e in entries if e.raw.get("thread"))
    print(f"    distinct threads : {len(threads_seen)} "
          f"{dict(threads_seen.most_common(4))}")
    print(f"    continuations    : {continuations:,}")
    print(f"    blank timestamps : {no_time:,}")
    print(f"    prefix in message: {prefixed:,}"
          + ("" if not prefixed else "   *** the message repeats its own time"))

    from modules.log_viewer.log_model import LogModel

    model = LogModel()
    model.append(entries)
    total = model.rowCount()
    model.set_filter(levels={"Error"})
    errors = model.rowCount()
    print(f"    filter sanity    : {errors:,} errors of {total:,}"
          + ("" if errors <= total else "   *** FILTER GREW THE LOG"))


def main():
    files = _files()
    if not files:
        print("This machine has none of the logs the viewer knows about.")
        return 0
    print(f"{len(files)} log(s) offered by the viewer's Open menu.")
    for label, path in files:
        try:
            check(label, path)
        except Exception as exc:                            # noqa: BLE001
            print(f"\n=== {label}\n    {path}\n    *** RAISED: {exc!r}")
    print("\nNote: `severity` is expected to be non-zero on CBS and DISM -- "
          "it counts\nthe rows the word-match used to colour wrongly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
