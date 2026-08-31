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

Then, for any log larger than the 32 MB window, it walks that file BACKWARDS
to its head and checks the walk against the file itself:

  records          -- every non-blank line must become exactly one record.
                      Fewer means a chunk boundary swallowed something; more
                      means a seam overlapped and parsed a record twice.
  lines paged      -- newlines seen while paging vs newlines in the file. A
                      seam that eats one line per step is invisible in a
                      table and fatal to an investigation.
  window start     -- must reach 0, or paging stopped short of the head.

Note that the log this matters for is NOT the one the Open menu offers. The
menu offers the NEWEST CBS archive, which is routinely the smallest; the
paging pass goes looking for the LARGEST archive on disk instead.
"""
import codecs
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
from modules.log_viewer.log_reader import (DEFAULT_MAX_BYTES,     # noqa: E402
                                           LogReader)


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


def _paging_targets():
    """Logs big enough for backward paging to mean anything.

    Deliberately NOT the Open menu's list. That offers the NEWEST CBS
    archive, and the newest is routinely the smallest -- 15 MB here, well
    under the 32 MB window, so nothing about paging would be exercised. What
    this feature exists for is the archive that does not fit, which today is
    the 363 MB one from two days earlier.
    """
    targets = [(label, path) for label, path in _files()
               if os.path.getsize(path) > DEFAULT_MAX_BYTES]
    folder = os.path.join(os.environ.get("SystemRoot", ""), "Logs", "CBS")
    known = {path for _label, path in targets}
    biggest = None
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            if not name.lower().endswith(".log"):
                continue
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size > DEFAULT_MAX_BYTES and path not in known:
                if biggest is None or size > biggest[0]:
                    biggest = (size, path)
    if biggest:
        targets.append(("CBS — largest archive on disk", biggest[1]))
    return targets


def _line_counts(path, encoding, width):
    """`(lines, non-blank lines)`, streamed rather than loaded.

    The yardstick for paging: read the file forwards once, count, then walk
    it backwards and count again. A seam that eats a line makes the second
    number smaller; one that repeats a line makes it bigger. Nothing else
    about a 380 MB archive is small enough to compare directly.

    Blank lines are counted separately because they are what separates the
    two honest totals: this archive has 1,497,582 lines of which 4,810 are
    blank, and blank lines produce no record. Without that number the 4,810
    missing records look like a seam eating them.
    """
    block_size = 8 * 1024 * 1024
    decoder = (None if width == 1
               else codecs.getincrementaldecoder(encoding)(errors="replace"))
    lines = blank = 0
    tail = b"" if decoder is None else ""
    newline = b"\n" if decoder is None else "\n"
    with open(path, "rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            data = tail + (block if decoder is None else decoder.decode(block))
            pieces = data.split(newline)
            tail = pieces.pop()
            for piece in pieces:
                lines += 1
                if not piece.strip():
                    blank += 1
    if tail:
        lines += 1
        if not tail.strip():
            blank += 1
    return lines, lines - blank


def page_back(label, path):
    """Walk a truncated log backwards to its head, at the REAL step size.

    The tests for this run against kilobyte files through an injected
    `max_bytes`, and an injectable seam hides the bugs that live on the other
    side of it. This is the other side: the real archive, the real 32 MB
    step, the real encoding.
    """
    reader = LogReader(path)
    tail = reader.read_new()
    if not reader.truncated:
        return

    encoding, width = reader._encoding, reader._char_width
    expected, expected_records = _line_counts(path, encoding, width)

    steps = 0
    newlines = tail.count("\n")
    records = len(cmtrace_parser.parse(tail))
    first_line = ""
    started = time.monotonic()
    while reader.has_earlier():
        chunk = reader.read_earlier()
        steps += 1
        newlines += chunk.count("\n")
        records += len(cmtrace_parser.parse(chunk))
        if chunk:
            first_line = chunk.splitlines()[0]
    elapsed = time.monotonic() - started

    size = os.path.getsize(path)
    print(f"\n=== {label} — paging back to the head")
    print(f"    {size:,} bytes, {steps} step(s) of "
          f"{DEFAULT_MAX_BYTES // (1024 * 1024)} MB in {elapsed:.1f}s")
    # Every non-blank line must become exactly one record. Fewer means a
    # chunk boundary swallowed something; more means a record was parsed
    # twice, which is what a seam that overlaps rather than abuts produces.
    kept = ("OK" if records == expected_records
            else f"*** {abs(expected_records - records):,} record(s) "
                 + ("LOST" if records < expected_records else "INVENTED"))
    print(f"    records          : {records:,} of {expected_records:,} "
          f"non-blank lines   {kept}")
    # The whole point. A seam that drops one line per step is invisible in a
    # table and fatal to an investigation: the missing line is as likely as
    # any other to be the failure someone opened the log to find.
    verdict = "OK" if newlines == expected else (
        f"*** {abs(expected - newlines):,} line(s) "
        + ("LOST" if newlines < expected else "DUPLICATED") + " at a seam")
    print(f"    lines paged      : {newlines:,} of {expected:,} in the file"
          f"   {verdict}")
    print(f"    window start     : {reader.window_start():,} "
          f"(0 means the head was reached)")
    print(f"    first line       : {first_line[:90]}")


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
    targets = _paging_targets()
    if not targets:
        print("\nNo log on this machine is larger than the "
              f"{DEFAULT_MAX_BYTES // (1024 * 1024)} MB window, so backward "
              "paging has nothing to walk.")
    for label, path in targets:
        try:
            page_back(label, path)
        except Exception as exc:                            # noqa: BLE001
            print(f"\n=== {label} — paging\n    *** RAISED: {exc!r}")
    print("\nNote: `severity` is expected to be non-zero on CBS and DISM -- "
          "it counts\nthe rows the word-match used to colour wrongly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
