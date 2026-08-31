r"""Paging BACKWARDS through a log that was opened at its tail.

`LogReader` is forward-only by construction: opening a file larger than
`max_bytes` seeks to `size - max_bytes` and never looks behind that offset
again. On the real 380 MB `CbsPersist` archive that hides most of the file
with no way to reach it.

The test that matters here is reassembly. Paging a file backwards to byte 0
and concatenating the pieces must reproduce the file exactly -- every line
once, in order. Anything else means a seam is wrong, and a seam that eats one
line per 32 MB step is invisible in a viewer and fatal to an investigation:
the line that is missing is as likely as any other to be the failure someone
opened the log to find.

Everything here uses REAL files, like the rest of the reader's tests.
"""
import pytest

from modules.log_viewer.log_reader import LogReader

#: Small enough to keep these tests instant, large enough that a step lands
#: mid-line rather than tidily between records. The production value is
#: 32 MB; nothing here depends on the size beyond "smaller than the file".
STEP = 2048


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _write_utf16(path, text):
    """As Windows writes ReportingEvents.log: UTF-16 LE with a BOM."""
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-16"))


def _lines(count, width=60):
    """Numbered lines, each identifiable on sight and all the same length."""
    return "".join(f"line {number:05d} " + "." * width + "\n"
                   for number in range(count))


def _page_to_the_head(reader):
    """Every earlier chunk, oldest first, until the head is reached."""
    chunks = []
    while reader.has_earlier():
        chunks.append(reader.read_earlier())
    chunks.reverse()
    return "".join(chunks)


# ---- knowing whether there is anything behind you -----------------------

def test_a_file_that_fitted_whole_has_nothing_earlier(tmp_path):
    path = tmp_path / "small.log"
    _write(path, _lines(3))
    reader = LogReader(str(path), max_bytes=STEP)

    reader.read_new()

    assert not reader.has_earlier()


def test_a_file_opened_at_its_tail_has_something_earlier(tmp_path):
    path = tmp_path / "big.log"
    _write(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)

    reader.read_new()

    assert reader.truncated, "the file must be big enough to be cut"
    assert reader.has_earlier()


def test_an_unread_reader_has_nothing_earlier_yet(tmp_path):
    """Before the first read there is no window, so there is no behind."""
    path = tmp_path / "big.log"
    _write(path, _lines(400))

    assert not LogReader(str(path), max_bytes=STEP).has_earlier()


# ---- reassembly ---------------------------------------------------------

def test_paging_backwards_reassembles_the_whole_file(tmp_path):
    whole = _lines(400)
    path = tmp_path / "big.log"
    _write(path, whole)
    reader = LogReader(str(path), max_bytes=STEP)

    tail = reader.read_new()
    earlier = _page_to_the_head(reader)

    assert earlier + tail == whole


def test_no_line_is_lost_or_duplicated_at_a_seam(tmp_path):
    """The failure this whole chunk exists to avoid.

    Seeking to a byte offset lands mid-line. The forward read drops that
    partial line, so if the backward read stops at the same byte the line is
    gone from BOTH halves -- and the reassembly above would still look nearly
    right, one line shorter per step.
    """
    path = tmp_path / "big.log"
    _write(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)

    tail = reader.read_new()
    earlier = _page_to_the_head(reader)
    numbers = [line.split()[1] for line in (earlier + tail).splitlines()]

    assert len(numbers) == 400, "a line was lost at a seam"
    assert len(set(numbers)) == 400, "a line was duplicated at a seam"
    assert numbers == sorted(numbers), "the chunks came back out of order"


def test_the_head_chunk_reaches_the_very_first_line(tmp_path):
    path = tmp_path / "big.log"
    _write(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)
    reader.read_new()

    earlier = _page_to_the_head(reader)

    assert earlier.startswith("line 00000 ")


def test_reading_earlier_at_the_head_returns_nothing(tmp_path):
    path = tmp_path / "big.log"
    _write(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)
    reader.read_new()
    _page_to_the_head(reader)

    assert not reader.has_earlier()
    assert reader.read_earlier() == ""


def test_a_whole_file_pages_back_to_nothing(tmp_path):
    """A file that already fitted has no earlier chunk to give."""
    path = tmp_path / "small.log"
    _write(path, _lines(3))
    reader = LogReader(str(path), max_bytes=STEP)
    reader.read_new()

    assert reader.read_earlier() == ""


# ---- encodings ----------------------------------------------------------

def test_backward_paging_of_a_utf16_log_stays_aligned(tmp_path):
    r"""A byte offset is not a character offset.

    `ReportingEvents.log` is UTF-16 LE. Landing one byte out of phase shifts
    every character after it and the slice comes back as CJK -- on exactly
    the files too big to sanity-check by eye. The forward path already guards
    this; the backward path needs its own guard, and its own test.
    """
    whole = _lines(400)
    path = tmp_path / "ReportingEvents.log"
    _write_utf16(path, whole)
    reader = LogReader(str(path), max_bytes=STEP)

    tail = reader.read_new()
    earlier = _page_to_the_head(reader)

    assert "\x00" not in earlier, "decoded out of phase"
    assert earlier + tail == whole


def test_the_head_chunk_of_a_utf16_log_drops_its_bom(tmp_path):
    r"""A decoded BOM is U+FEFF: invisible, not matched by `\s`, and it costs
    the first record of the file its timestamp."""
    path = tmp_path / "ReportingEvents.log"
    _write_utf16(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)
    reader.read_new()

    earlier = _page_to_the_head(reader)

    assert not earlier.startswith("﻿")
    assert earlier.startswith("line 00000 ")


# ---- crossing two interactions ------------------------------------------

def test_paging_back_does_not_disturb_the_live_tail(tmp_path):
    """Follow and "load earlier" share one reader.

    The backward read must not touch the forward cursor or the incremental
    decoder that Follow depends on. If it does, the next `read_new()` either
    replays the file or returns nothing, and a followed log goes silent --
    the exact shape of defect the real-log pass found three of.
    """
    path = tmp_path / "big.log"
    _write(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)
    reader.read_new()

    reader.read_earlier()
    with open(path, "a", encoding="utf-8", newline="") as handle:
        handle.write("line 00400 fresh\n")

    assert reader.read_new() == "line 00400 fresh\n"


def test_paging_back_twice_walks_further_each_time(tmp_path):
    """Each step must move the window, not re-read the same chunk."""
    path = tmp_path / "big.log"
    _write(path, _lines(400))
    reader = LogReader(str(path), max_bytes=STEP)
    reader.read_new()

    first = reader.read_earlier()
    second = reader.read_earlier()

    assert first and second
    assert first != second
    assert second.splitlines()[-1] < first.splitlines()[0], \
        "the second step must land EARLIER in the file, not later"
