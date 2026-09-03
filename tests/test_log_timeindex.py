r"""Finding roughly where in a file a moment lives.

Paging is byte-based, so "go to 09:00 in a 380 MB archive" means walking
there. A sparse index of offset-to-time turns that into a seek.

Sparse and APPROXIMATE on purpose. It samples, so it answers "start reading
here and you will not have missed it" rather than "the record is at this
byte" -- which is all a seek needs, and all a log can honestly support: real
logs are not sorted by time. `setupact.log` jumps ten hours backwards at a
phase boundary.
"""
import os


from modules.log_viewer.timeindex import build_index, offset_at_or_before
from datetime import datetime


def _line(stamp, message="a line"):
    return f"{stamp}, Info                  CBS    {message}\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return str(path)


def _log(tmp_path, count=400):
    text = "".join(
        _line(f"2026-08-27 1{n // 3600}:{(n // 60) % 60:02d}:{n % 60:02d}",
              f"line {n:04d}")
        for n in range(count))
    return _write(tmp_path / "cbs.log", text)


def test_the_index_samples_the_whole_file(tmp_path):
    path = _log(tmp_path)
    marks = build_index(path, every_bytes=1024)

    assert len(marks) > 1
    assert marks[0].offset == 0
    assert marks[-1].offset < os.path.getsize(path)


def test_every_mark_sits_on_a_line_boundary(tmp_path):
    r"""The rule `_start` already follows: a byte offset that is not a line
    boundary costs the seam line."""
    path = _log(tmp_path)
    with open(path, "rb") as handle:
        data = handle.read()

    for mark in build_index(path, every_bytes=1024):
        assert mark.offset == 0 or data[mark.offset - 1:mark.offset] == b"\n"


def test_a_time_maps_to_an_offset_at_or_before_it(tmp_path):
    path = _log(tmp_path)
    marks = build_index(path, every_bytes=1024)
    wanted = datetime(2026, 8, 27, 10, 3, 0)

    offset = offset_at_or_before(marks, wanted)

    with open(path, "rb") as handle:
        handle.seek(offset)
        first = handle.readline().decode("utf-8")
    assert first[:19] <= wanted.strftime("%Y-%m-%d %H:%M:%S"), \
        "seeking there would have skipped past the moment"


def test_a_time_before_the_file_starts_maps_to_the_beginning(tmp_path):
    marks = build_index(_log(tmp_path), every_bytes=1024)
    assert offset_at_or_before(marks, datetime(2000, 1, 1)) == 0


def test_a_time_after_the_file_ends_maps_to_the_last_mark(tmp_path):
    marks = build_index(_log(tmp_path), every_bytes=1024)
    assert offset_at_or_before(marks, datetime(2099, 1, 1)) == marks[-1].offset


def test_an_empty_index_answers_zero(tmp_path):
    assert offset_at_or_before([], datetime(2026, 1, 1)) == 0


def test_a_file_with_no_timestamps_yields_no_marks(tmp_path):
    path = _write(tmp_path / "flat.log", "no timestamps here\nnor here\n")
    assert build_index(path, every_bytes=16) == []


def test_a_missing_file_yields_no_marks(tmp_path):
    assert build_index(str(tmp_path / "nope.log")) == []


def test_a_log_whose_clock_goes_backwards_does_not_break_it(tmp_path):
    r"""setupact.log jumps ten hours backwards at a phase boundary. The
    index must still answer, and must not claim more precision than a
    non-monotonic file can support."""
    text = ("".join(_line("2026-08-27 10:44:46", f"late {n}")
                    for n in range(200))
            + "".join(_line("2026-08-27 00:44:49", f"early {n}")
                      for n in range(200)))
    path = _write(tmp_path / "setupact.log", text)

    marks = build_index(path, every_bytes=1024)

    assert marks
    offset = offset_at_or_before(marks, datetime(2026, 8, 27, 10, 0, 0))
    assert 0 <= offset < os.path.getsize(path)


def test_a_utf16_log_is_indexed_too(tmp_path):
    path = tmp_path / "ReportingEvents.log"
    text = "".join(_line(f"2026-08-27 10:00:{n % 60:02d}") for n in range(200))
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-16"))

    marks = build_index(str(path), every_bytes=2048)

    assert marks, "a UTF-16 log produced no marks"
