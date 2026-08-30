r"""A log is whatever encoding the writing process chose, not UTF-8.

`C:\Windows\SoftwareDistribution\ReportingEvents.log` is UTF-16 LE with a
BOM, and it is one click away in the viewer's Open menu. Decoded as UTF-8 it
does not raise: every character comes back with a NUL beside it, every second
line is a lone NUL, and not one of its 3,378 records keeps its timestamp. The
pane renders that as wide-spaced text, so it reads as a font quirk rather
than as a file that was never decoded at all.

The lines below are verbatim from this machine, encoded to the same form
Windows wrote them in.
"""
from modules.log_viewer.log_reader import LogReader

#: One real record out of ReportingEvents.log. Tab separated, and note the
#: timestamp is NOT at the start of the line -- the GUID is.
REAL_REPORTING_EVENT = (
    "{39D5CB74-A3A1-4E38-8459-2CAAB15D1376}\t2026-07-28 21:31:28:095+0300\t"
    "1\t167 [AGENT_DOWNLOAD_STARTED]\t101\t{717EAA48-2123-4ECD-A9A7-6}\t"
    "Download started"
)


def _write_utf16(path, text):
    """As Windows writes it: UTF-16 LE with a BOM."""
    with open(path, "wb") as handle:
        handle.write(text.encode("utf-16"))     # utf-16 emits the BOM


def test_a_utf16_log_is_decoded_rather_than_mangled(tmp_path):
    path = tmp_path / "ReportingEvents.log"
    _write_utf16(path, REAL_REPORTING_EVENT + "\n")

    text = LogReader(str(path)).read_new()

    assert "\x00" not in text, "decoded as UTF-8: a NUL beside every character"
    assert text.startswith("{39D5CB74-A3A1-4E38-8459-2CAAB15D1376}")
    assert "AGENT_DOWNLOAD_STARTED" in text


def test_a_utf16_log_does_not_gain_a_blank_line_per_record(tmp_path):
    """The NUL from each newline's high byte parses as its own empty record,
    which is why the pane showed 3,378 rows alternating with blanks."""
    path = tmp_path / "ReportingEvents.log"
    _write_utf16(path, "first\nsecond\nthird\n")

    lines = LogReader(str(path)).read_new().splitlines()

    assert lines == ["first", "second", "third"]


def test_the_utf16_bom_is_not_left_on_the_first_line(tmp_path):
    path = tmp_path / "ReportingEvents.log"
    _write_utf16(path, "2026-07-28 21:31:28 first line\n")

    text = LogReader(str(path)).read_new()

    assert not text.startswith("\ufeff")
    assert text.startswith("2026-07-28")


def test_a_utf16_log_tails_across_a_character_split_between_reads(tmp_path):
    """Half a UTF-16 character is two bytes with no partner. Carrying the odd
    byte forward is what keeps the next read from starting one byte out of
    phase and turning the rest of the file into CJK."""
    path = tmp_path / "ReportingEvents.log"
    _write_utf16(path, "first\n")
    reader = LogReader(str(path))
    assert reader.read_new() == "first\n"

    payload = "second\n".encode("utf-16-le")
    with open(path, "ab") as handle:
        handle.write(payload[:5])               # odd length, splits a char
    reader.read_new()
    with open(path, "ab") as handle:
        handle.write(payload[5:])

    assert reader.read_new() == "second\n"


def test_a_big_utf16_log_opens_at_its_tail_without_losing_phase(tmp_path):
    """The tail seek lands on a byte offset. On UTF-16 an odd one shifts every
    character afterwards by a byte, so the whole visible slice is garbage --
    a file too big to open is exactly the one nobody can check by eye."""
    path = tmp_path / "big.log"
    _write_utf16(path, "".join(f"line {n}\n" for n in range(4000)))

    reader = LogReader(str(path), max_bytes=8192)
    text = reader.read_new()

    assert reader.truncated
    assert "\x00" not in text
    assert text.rstrip().endswith("line 3999")
    for line in text.splitlines():
        assert line.startswith("line "), f"lost phase: {line!r}"


def test_a_utf8_log_is_still_read_as_utf8(tmp_path):
    """The machine's CBS, DISM and Setup logs are UTF-8 with a BOM. Sniffing
    for UTF-16 must not cost them their accents."""
    path = tmp_path / "CBS.log"
    with open(path, "wb") as handle:
        handle.write("2026-08-29 22:08:03, Info  CBS  café\n".encode("utf-8-sig"))

    text = LogReader(str(path)).read_new()

    assert text == "2026-08-29 22:08:03, Info  CBS  café\n"
