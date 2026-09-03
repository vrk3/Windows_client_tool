"""Incremental log reading: big files, tailing, and rotation.

Everything here uses REAL files. What breaks a tailer is never the parsing --
it is the file shrinking under you, a half-written final line, and a rollover
that silently restarts the byte count.
"""
import os


from modules.log_viewer.log_reader import LogReader


def _write(path, text, mode="w"):
    with open(path, mode, encoding="utf-8", newline="") as handle:
        handle.write(text)


# ---- reading ------------------------------------------------------------

def test_the_first_read_returns_everything(tmp_path):
    path = tmp_path / "a.log"
    _write(path, "one\ntwo\n")
    assert LogReader(str(path)).read_new() == "one\ntwo\n"


def test_a_second_read_returns_only_what_is_new(tmp_path):
    """The whole point. Re-reading 300 MB every second is not tailing."""
    path = tmp_path / "a.log"
    _write(path, "one\n")
    reader = LogReader(str(path))
    assert reader.read_new() == "one\n"
    _write(path, "two\n", mode="a")
    assert reader.read_new() == "two\n"


def test_nothing_new_reads_as_empty(tmp_path):
    path = tmp_path / "a.log"
    _write(path, "one\n")
    reader = LogReader(str(path))
    reader.read_new()
    assert reader.read_new() == ""


def test_a_partial_final_line_is_held_back(tmp_path):
    """The writer is mid-line. Half a line is not a log entry, and a CMTrace
    record split down the middle parses as nothing at all."""
    path = tmp_path / "a.log"
    _write(path, "complete\nincomp")
    reader = LogReader(str(path))
    assert reader.read_new() == "complete\n"
    _write(path, "lete\n", mode="a")
    assert reader.read_new() == "incomplete\n"


def test_a_missing_file_reads_as_empty_rather_than_raising(tmp_path):
    assert LogReader(str(tmp_path / "never.log")).read_new() == ""


# ---- rotation and truncation --------------------------------------------

def test_a_shrinking_file_is_reread_from_the_start(tmp_path):
    """SCCM rolls the log and starts a new one at the same name. Keeping the
    old offset means reading from the middle of the new file forever -- the
    tailer goes silent and looks like a quiet machine."""
    path = tmp_path / "a.log"
    _write(path, "old line one\nold line two\n")
    reader = LogReader(str(path))
    reader.read_new()
    _write(path, "fresh\n")                 # truncated and rewritten
    assert reader.read_new() == "fresh\n"


def test_a_rollover_is_noticed_even_at_the_same_size(tmp_path):
    """Same length, different content. Size alone cannot tell, so the reader
    checks the file's identity too."""
    path = tmp_path / "a.log"
    _write(path, "aaaa\n")
    reader = LogReader(str(path))
    reader.read_new()
    os.remove(path)
    _write(path, "bbbb\n")
    assert reader.read_new() == "bbbb\n"


def test_the_rolled_sibling_is_read_first(tmp_path):
    """ConfigMgr rolls foo.log to foo.lo_ . The pair is one timeline, and
    reading them out of order puts yesterday after today."""
    _write(tmp_path / "a.lo_", "older\n")
    _write(tmp_path / "a.log", "newer\n")
    reader = LogReader(str(tmp_path / "a.log"), include_rolled=True)
    assert reader.read_new() == "older\nnewer\n"


def test_the_rolled_sibling_is_only_read_once(tmp_path):
    _write(tmp_path / "a.lo_", "older\n")
    _write(tmp_path / "a.log", "newer\n")
    reader = LogReader(str(tmp_path / "a.log"), include_rolled=True)
    reader.read_new()
    _write(tmp_path / "a.log", "newest\n", mode="a")
    assert reader.read_new() == "newest\n"


def test_rolled_files_are_ignored_when_not_asked_for(tmp_path):
    _write(tmp_path / "a.lo_", "older\n")
    _write(tmp_path / "a.log", "newer\n")
    assert LogReader(str(tmp_path / "a.log")).read_new() == "newer\n"


# ---- big files ----------------------------------------------------------

def test_only_the_tail_of_a_huge_file_is_read(tmp_path):
    """Opening a 300 MB log must not pull 300 MB into memory. The last slice
    is what anyone looks at first anyway."""
    path = tmp_path / "big.log"
    _write(path, "".join(f"line {i}\n" for i in range(200_000)))
    assert os.path.getsize(path) > 1_000_000

    reader = LogReader(str(path), max_bytes=50_000)
    text = reader.read_new()
    assert len(text) <= 60_000
    assert text.endswith("line 199999\n")
    assert reader.truncated is True


def test_a_truncated_read_starts_on_a_line_boundary(tmp_path):
    """Slicing mid-line hands the parser a fragment that is not a record."""
    path = tmp_path / "big.log"
    _write(path, "".join(f"line {i}\n" for i in range(50_000)))
    text = LogReader(str(path), max_bytes=1000).read_new()
    assert text.startswith("line ")


def test_a_small_file_is_not_reported_as_truncated(tmp_path):
    path = tmp_path / "a.log"
    _write(path, "short\n")
    reader = LogReader(str(path), max_bytes=50_000)
    reader.read_new()
    assert reader.truncated is False


def test_tailing_continues_normally_after_a_truncated_first_read(tmp_path):
    path = tmp_path / "big.log"
    _write(path, "".join(f"line {i}\n" for i in range(50_000)))
    reader = LogReader(str(path), max_bytes=1000)
    reader.read_new()
    _write(path, "brand new\n", mode="a")
    assert reader.read_new() == "brand new\n"


# ---- encoding -----------------------------------------------------------

def test_a_non_utf8_byte_does_not_kill_the_read(tmp_path):
    """Logs carry whatever the writing process emitted. One bad byte must
    cost one character, not the file."""
    path = tmp_path / "a.log"
    with open(path, "wb") as handle:
        handle.write(b"before \xff\xfe after\n")
    assert "before" in LogReader(str(path)).read_new()


def test_a_utf8_character_split_across_reads_survives(tmp_path):
    """The writer flushed half a multi-byte character. Decoding the half is
    a replacement character that never repairs itself."""
    path = tmp_path / "a.log"
    payload = "café\n".encode("utf-8")
    with open(path, "wb") as handle:
        handle.write(payload[:4])           # cuts the é in half
    reader = LogReader(str(path))
    reader.read_new()
    with open(path, "ab") as handle:
        handle.write(payload[4:])
    assert "café" in reader.read_new()


def test_a_utf8_bom_is_stripped(tmp_path):
    r"""Every log in C:\Windows\Logs on a real machine starts with a UTF-8
    BOM. Decoding it leaves \ufeff on the front of the first line, which is
    invisible, is NOT matched by \s, and so costs that line its timestamp --
    the first line of every CBS, DISM and Setup log."""
    path = tmp_path / "bom.log"
    with open(path, "wb") as handle:
        handle.write(b"\xef\xbb\xbf2026-08-20 10:00:00 first line\n")
    text = LogReader(str(path)).read_new()
    assert not text.startswith("\ufeff")
    assert text.startswith("2026-08-20")


def test_the_bom_is_only_stripped_at_the_very_start(tmp_path):
    """A BOM-looking sequence mid-file is data, not a marker."""
    path = tmp_path / "bom.log"
    with open(path, "wb") as handle:
        handle.write(b"first\n\xef\xbb\xbfsecond\n")
    assert LogReader(str(path)).read_new().count("\ufeff") == 1
