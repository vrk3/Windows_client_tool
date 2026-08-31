r"""Several logs read as ONE timeline.

A Windows servicing failure is told across CBS, DISM, setupact and
ReportingEvents at once. Reading them one at a time means holding four clocks
in your head; interleaving them by time is the whole point of this.

The merge key is where this feature lives or dies, and two properties of it
are load-bearing:

* **A continuation sorts immediately after its parent.** Continuation lines
  carry no timestamp of their own -- 9,185 of the big CBS archive's 90,714
  records are continuations, and one CSI block runs to 1,260 of them.
  Interleaving those on their own absent timestamps would scatter one
  operation list across the whole timeline.
* **File order is authoritative WITHIN a log; timestamps only decide BETWEEN
  logs.** Real logs are not perfectly monotonic, and a log's own sequence is
  the truth about what happened in it.

No Qt here, like the reader and the parser it sits beside.
"""
import os

import pytest

from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.log_reader import DEFAULT_MAX_BYTES
from modules.log_viewer.log_set import LogSet


def _service_line(stamp, component, message):
    """The `2026-08-27 17:13:31, Info   CBS   text` form CBS and DISM use."""
    return f"{stamp}, Info                  {component}    {message}\n"


def _write(path, text, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="") as handle:
        handle.write(text)
    return str(path)


def _messages(entries):
    return [e.message for e in entries]


def _logs(entries):
    return [e.raw.get("log", "") for e in entries]


# ---- interleaving -------------------------------------------------------

def test_two_logs_are_interleaved_by_time(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "first")
               + _service_line("2026-08-27 10:00:30", "CBS", "third"))
    b = _write(tmp_path / "dism.log",
               _service_line("2026-08-27 10:00:15", "DISM", "second")
               + _service_line("2026-08-27 10:00:45", "DISM", "fourth"))

    entries = LogSet([a, b]).read_new()

    assert _messages(entries) == ["first", "second", "third", "fourth"]


def test_each_record_carries_the_log_it_came_from(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "first"))
    b = _write(tmp_path / "dism.log",
               _service_line("2026-08-27 10:00:15", "DISM", "second"))

    entries = LogSet([a, b]).read_new()

    assert _logs(entries) == ["cbs.log", "dism.log"]


def test_the_log_name_does_not_overwrite_the_component(tmp_path):
    """`entry.source` is the COMPONENT and the Component column reads it."""
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "first"))

    entry = LogSet([a]).read_new()[0]

    assert entry.source == "CBS"
    assert entry.raw["log"] == "cbs.log"


def test_one_log_still_reads_as_itself(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "only"))

    assert _messages(LogSet([a]).read_new()) == ["only"]


def test_sources_are_listed_by_name(tmp_path):
    a = _write(tmp_path / "cbs.log", _service_line("2026-08-27 10:00:00",
                                                   "CBS", "x"))
    b = _write(tmp_path / "dism.log", _service_line("2026-08-27 10:00:01",
                                                    "DISM", "y"))

    assert LogSet([a, b]).sources() == ["cbs.log", "dism.log"]


# ---- the two load-bearing properties ------------------------------------

def test_a_continuation_stays_under_its_parent_across_a_merge(tmp_path):
    """The failure this design exists to prevent.

    A CSI block's continuation lines have no timestamp. If they are
    interleaved on their own, the other log's records land in the middle of
    one operation list and the block is destroyed.
    """
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CSI", "Performing 3 operations:")
               + "    (0) Uninstall: alpha\n"
               + "    (1) Install: beta\n"
               + _service_line("2026-08-27 10:00:30", "CBS", "Ending"))
    b = _write(tmp_path / "dism.log",
               _service_line("2026-08-27 10:00:10", "DISM", "meanwhile"))

    entries = LogSet([a, b]).read_new()

    assert _messages(entries) == [
        "Performing 3 operations:",
        "    (0) Uninstall: alpha",
        "    (1) Install: beta",
        "meanwhile",
        "Ending",
    ], "the continuations must follow their parent, not their own clock"


def test_a_logs_own_order_is_never_rearranged_by_its_clock(tmp_path):
    """Real logs are not perfectly monotonic. What the file says happened in
    what order is the truth about that file."""
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:30", "CBS", "later stamp first")
               + _service_line("2026-08-27 10:00:00", "CBS", "earlier stamp second"))

    entries = LogSet([a]).read_new()

    assert _messages(entries) == ["later stamp first", "earlier stamp second"]


def test_an_orphan_continuation_is_not_dropped(tmp_path):
    """A truncated slice can begin inside a block, so its first records are
    continuations with nothing above them to inherit from."""
    a = _write(tmp_path / "cbs.log",
               "    (7) Install: orphan\n"
               + _service_line("2026-08-27 10:00:00", "CBS", "Ending"))

    entries = LogSet([a]).read_new()

    assert "    (7) Install: orphan" in _messages(entries)


def test_a_record_with_no_timestamp_anywhere_survives(tmp_path):
    a = _write(tmp_path / "plain.log", "no timestamp at all\n")

    entries = LogSet([a]).read_new()

    assert len(entries) == 1
    assert entries[0].timestamp == UNKNOWN_TIME


# ---- encodings ----------------------------------------------------------

def test_sources_are_decoded_independently(tmp_path):
    """ReportingEvents.log is UTF-16 LE while CBS is UTF-8. Each source is
    sniffed by its own reader, so one merged set spans both."""
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "utf8 line"))
    b = tmp_path / "ReportingEvents.log"
    with open(b, "wb") as handle:
        handle.write(_service_line("2026-08-27 10:00:10", "WU",
                                   "utf16 line").encode("utf-16"))

    entries = LogSet([a, str(b)]).read_new()

    # Decoded, not mangled: read as UTF-8 a UTF-16 file comes back with a NUL
    # beside every character. Which parser claims a one-line file is a
    # separate question and not what this is testing.
    assert not any("\x00" in e.message for e in entries)
    assert "utf8 line" in entries[0].message
    assert "utf16 line" in entries[1].message
    assert _logs(entries) == ["cbs.log", "ReportingEvents.log"]


# ---- the reading budget -------------------------------------------------

def test_one_log_gets_the_whole_window(tmp_path):
    a = _write(tmp_path / "cbs.log", "x\n")
    assert LogSet([a]).per_source_bytes == DEFAULT_MAX_BYTES


def test_the_window_is_shared_between_sources(tmp_path):
    """Twelve logs must not read twelve full windows: opening a folder would
    stall for the size of the pile rather than the size of the window."""
    paths = [_write(tmp_path / f"{n}.log", "x\n") for n in range(4)]
    assert LogSet(paths).per_source_bytes == DEFAULT_MAX_BYTES // 4


def test_a_share_never_falls_below_the_floor(tmp_path):
    """Split far enough and a share becomes too small to hold a record."""
    paths = [_write(tmp_path / f"{n}.log", "x\n") for n in range(100)]
    assert DEFAULT_MAX_BYTES // 100 < LogSet.MIN_BYTES, "the split must bite"
    assert LogSet(paths).per_source_bytes == LogSet.MIN_BYTES


def test_the_floor_never_raises_a_source_above_its_window(tmp_path):
    """The floor bounds the SPLIT. Letting it exceed `max_bytes` gave a
    caller asking for a small window a 2 MB one instead, which stopped the
    paging fixtures truncating at all."""
    a = _write(tmp_path / "a.log", "x\n")
    assert LogSet([a], max_bytes=2048).per_source_bytes == 2048


# ---- following and paging -----------------------------------------------

def test_appended_lines_are_picked_up_from_every_source(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "first"))
    b = _write(tmp_path / "dism.log",
               _service_line("2026-08-27 10:00:05", "DISM", "second"))
    log_set = LogSet([a, b])
    log_set.read_new()

    with open(a, "a", encoding="utf-8", newline="") as handle:
        handle.write(_service_line("2026-08-27 10:01:00", "CBS", "later a"))
    with open(b, "a", encoding="utf-8", newline="") as handle:
        handle.write(_service_line("2026-08-27 10:00:30", "DISM", "later b"))

    fresh = log_set.read_new()

    assert _messages(fresh) == ["later b", "later a"], \
        "one tick's records are merged among themselves"


def test_a_set_of_small_logs_has_nothing_earlier(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "x"))
    log_set = LogSet([a])
    log_set.read_new()

    assert not log_set.has_earlier()


def test_reading_earlier_rebuilds_the_whole_merged_set(tmp_path):
    """A prepend would be wrong here: one source's earlier chunk is older
    than its OWN loaded part, but not necessarily older than what is already
    loaded from another source."""
    big = "".join(_service_line(f"2026-08-27 10:{n // 60:02d}:{n % 60:02d}",
                                "CBS", f"cbs {n:04d}") for n in range(400))
    a = _write(tmp_path / "cbs.log", big)
    b = _write(tmp_path / "dism.log",
               _service_line("2026-08-27 10:00:05", "DISM", "very early dism"))
    log_set = LogSet([a, b], max_bytes=4096, min_bytes=512)
    log_set.read_new()
    assert log_set.has_earlier()

    while log_set.has_earlier():
        merged = log_set.read_earlier()

    assert _messages(merged)[0] == "cbs 0000"
    assert "very early dism" in _messages(merged)
    assert _messages(merged).count("very early dism") == 1, \
        "the rebuild must not duplicate what was already loaded"


def test_earlier_bytes_sums_across_the_sources(tmp_path):
    big = "".join(_service_line(f"2026-08-27 10:{n // 60:02d}:{n % 60:02d}",
                                "CBS", f"cbs {n:04d}") for n in range(400))
    a = _write(tmp_path / "cbs.log", big)
    b = _write(tmp_path / "dism.log", big)
    log_set = LogSet([a, b], max_bytes=4096, min_bytes=512)
    log_set.read_new()

    assert log_set.earlier_bytes() > 0


# ---- opening a folder ---------------------------------------------------

def test_a_folder_yields_its_logs_in_name_order(tmp_path):
    _write(tmp_path / "b.log", "x\n")
    _write(tmp_path / "a.log", "x\n")
    _write(tmp_path / "c.lo_", "x\n")

    found = LogSet.logs_in_folder(str(tmp_path))

    assert [os.path.basename(p) for p in found] == ["a.log", "b.log", "c.lo_"]


def test_a_folder_ignores_everything_that_is_not_a_log(tmp_path):
    _write(tmp_path / "a.log", "x\n")
    _write(tmp_path / "readme.txt", "x\n")
    _write(tmp_path / "notes.md", "x\n")

    found = LogSet.logs_in_folder(str(tmp_path))

    assert [os.path.basename(p) for p in found] == ["a.log"]


def test_a_folder_does_not_recurse(tmp_path):
    """`C:\\Windows\\Logs` has ~30 subfolders. Recursing it would open
    several hundred files and a few hundred MB by accident."""
    _write(tmp_path / "a.log", "x\n")
    nested = tmp_path / "sub"
    nested.mkdir()
    _write(nested / "deep.log", "x\n")

    found = LogSet.logs_in_folder(str(tmp_path))

    assert [os.path.basename(p) for p in found] == ["a.log"]


def test_an_empty_folder_yields_nothing(tmp_path):
    assert LogSet.logs_in_folder(str(tmp_path)) == []


def test_a_folder_that_is_not_there_yields_nothing(tmp_path):
    assert LogSet.logs_in_folder(str(tmp_path / "absent")) == []


# ---- the accumulation cap -----------------------------------------------
#
# LogSet keeps what it has read so that "load earlier" can re-merge. Left
# unbounded, paging the real 380 MB archive to its head would hold 1,492,772
# entries -- the model's deque used to evict those for us, and a merged set
# has to do it itself.

def _many(prefix, count, start=0):
    return "".join(
        _service_line(f"2026-08-27 1{(start + n) // 3600:01d}:"
                      f"{((start + n) // 60) % 60:02d}:{(start + n) % 60:02d}",
                      "CBS", f"{prefix} {start + n:05d}")
        for n in range(count))


def test_reading_earlier_never_holds_more_than_the_cap(tmp_path):
    a = _write(tmp_path / "cbs.log", _many("cbs", 400))
    log_set = LogSet([a], max_bytes=4096, min_bytes=512, cap=50)

    log_set.read_new()
    while log_set.has_earlier():
        log_set.read_earlier()

    assert len(log_set.entries()) <= 50


def test_paging_back_keeps_the_OLDEST_within_the_cap(tmp_path):
    """The window slid backwards, so what goes is the newest -- the same
    semantics the model's deque gave chunk 3."""
    a = _write(tmp_path / "cbs.log", _many("cbs", 400))
    log_set = LogSet([a], max_bytes=4096, min_bytes=512, cap=50)
    log_set.read_new()
    while log_set.has_earlier():
        merged = log_set.read_earlier()

    assert _messages(merged)[0] == "cbs 00000"


def test_following_keeps_the_NEWEST_within_the_cap(tmp_path):
    a = _write(tmp_path / "cbs.log", _many("cbs", 20))
    log_set = LogSet([a], cap=10)
    log_set.read_new()

    with open(a, "a", encoding="utf-8", newline="") as handle:
        handle.write(_many("cbs", 10, start=20))
    log_set.read_new()

    kept = _messages(log_set.entries())
    assert len(kept) == 10
    assert kept[-1] == "cbs 00029"


def test_trimming_does_not_break_the_merge(tmp_path):
    """The per-source lists are rebuilt from the trimmed merge, so each one
    must still be in its own file order afterwards."""
    a = _write(tmp_path / "cbs.log", _many("cbs", 30))
    b = _write(tmp_path / "dism.log", _many("dism", 30))
    log_set = LogSet([a, b], cap=20)

    log_set.read_new()
    entries = log_set.entries()

    assert len(entries) == 20
    for name in ("cbs.log", "dism.log"):
        own = [e.message for e in entries if e.raw["log"] == name]
        assert own == sorted(own), f"{name} was reordered by the trim"


# ---- the architecture this file's docstring claims ----------------------

def test_the_engine_files_declare_no_qt_import():
    """`scan/` and `store/` keep Qt out of TreeSize so the engine stays
    testable with no display, and the Log Viewer's reader, parser and merge
    engine claim the same split at the top of each file.

    This checks each file's OWN imports, which is the property that actually
    holds. Import-time purity does not: `src/core/__init__.py` eagerly
    imports ThemeManager, Worker and friends, so any `from core.types import
    LogEntry` -- which `cmtrace_parser` does -- starts PyQt6. `log_reader` is
    the only one of the three that is clean end to end. That leak predates
    this module and is recorded here rather than papered over.
    """
    import ast
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "src", "modules", "log_viewer")
    for name in ("log_set.py", "log_reader.py", "cmtrace_parser.py"):
        with open(os.path.join(base, name), encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = " ".join(alias.name for alias in node.names)
            assert "PyQt" not in module, f"{name} imports Qt: {module}"


def test_the_cap_matches_the_models():
    """Duplicated rather than imported, so it has to be pinned."""
    from modules.log_viewer import log_model, log_set
    assert log_set.DEFAULT_CAP == log_model.DEFAULT_CAP


# ---- sources that carry no clock at all ---------------------------------
#
# `C:\Windows\Logs\CBS\FilterList.log` has no timestamps anywhere: it is a
# table of filter drivers, not a timeline. Its 22 records all take the epoch,
# which sorted them to the very top of a merged view of that folder -- so the
# first thing anyone saw on opening the CBS folder was a filter driver table.

def test_a_source_with_no_timestamps_anywhere_sorts_last(tmp_path):
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "real record"))
    b = _write(tmp_path / "FilterList.log", "bindflt   1\nFsDepends   7\n")

    entries = LogSet([a, b]).read_new()

    assert _messages(entries)[0] == "real record"
    assert _logs(entries)[-1] == "FilterList.log"


def test_a_source_with_SOME_timestamps_is_not_moved(tmp_path):
    """Only a source with no clock AT ALL is demoted. One that merely starts
    with an undated line is still a timeline."""
    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:30", "CBS", "later"))
    b = _write(tmp_path / "dism.log",
               "a preamble line with no date\n"
               + _service_line("2026-08-27 10:00:00", "DISM", "earlier"))

    entries = LogSet([a, b]).read_new()

    assert _messages(entries)[-1] == "later", \
        "dism.log has timestamps and must still interleave normally"


def test_a_clockless_source_keeps_its_own_order(tmp_path):
    a = _write(tmp_path / "FilterList.log", "first\nsecond\nthird\n")

    entries = LogSet([a]).read_new()

    assert _messages(entries) == ["first", "second", "third"]


def test_a_clockless_source_on_its_own_is_not_hidden(tmp_path):
    a = _write(tmp_path / "FilterList.log", "bindflt   1\n")
    assert len(LogSet([a]).read_new()) == 1


def test_an_orphan_continuation_is_still_not_demoted(tmp_path):
    """A dated file whose slice STARTS mid-block still has real timestamps,
    so the orphan keeps the epoch and leads that file -- it must not drag the
    whole source to the end."""
    a = _write(tmp_path / "cbs.log",
               "    (7) Install: orphan\n"
               + _service_line("2026-08-27 10:00:00", "CBS", "Ending"))
    b = _write(tmp_path / "dism.log",
               _service_line("2026-08-27 10:00:30", "DISM", "later"))

    entries = LogSet([a, b]).read_new()

    assert _messages(entries)[-1] == "later"
    assert "    (7) Install: orphan" in _messages(entries)


# ---- the appendix sentinel is a sort key, never a moment ----------------

def test_effective_time_rejects_the_appendix_sentinel(tmp_path):
    r"""A source with no clock is sorted last by giving its records
    `APPENDIX_TIME` (datetime.max). Anything that reads `merge_time` as a
    real timestamp -- the gap finder, the density strip -- must reject it, or
    the record lands in the year 9999: gaps of two millennia, and a density
    strip squashed into one bar at the right-hand edge.
    """
    from modules.log_viewer.log_set import APPENDIX_TIME, effective_time

    a = _write(tmp_path / "FilterList.log", "bindflt   1\n")
    entries = LogSet([a]).read_new()

    assert entries[0].raw["merge_time"] == APPENDIX_TIME, "sorted last"
    assert effective_time(entries[0]) is None, "but not a moment in time"


def test_effective_time_gives_a_real_timestamp_through(tmp_path):
    from modules.log_viewer.log_set import effective_time

    a = _write(tmp_path / "cbs.log",
               _service_line("2026-08-27 10:00:00", "CBS", "real"))
    entries = LogSet([a]).read_new()

    assert effective_time(entries[0]) is not None
