"""The shared text-log parsers must not silently lose lines.

Both faults here were found by measuring against the real
C:\\Windows\\Logs\\CBS\\CBS.log rather than a fixture: 6,333 of its 85,850
lines never reached the Diagnose tab, and the very first line was one of them.
"""
import pytest

from core.log_parser_base import LogParserBase
from core.types import LogEntry
from modules.cbs_log.cbs_parser import CBSParser
from modules.dism_log.dism_parser import DISMParser

CBS_LINES = [
    "2026-08-18 11:19:12, Info                  CBS    TI: Initializing",
    "2026-08-18 11:19:13, Warning               CBS    Overlap detected",
    "      (0)  AddCat: flags: 1 catfile: \\SystemRoot\\WinSxS\\Temp\\x",
    "2026-08-18 11:19:14, Error                 CBS    It failed",
]

DISM_LINES = [
    "2026-08-07 10:25:32, Info                  DISM   API: PID=1 starting",
    "  continuation of the previous entry",
    "2026-08-07 10:25:33, Error                 DISM   API: it broke",
]


# ---- the UTF-8 BOM ------------------------------------------------------

def test_a_utf8_bom_file_is_read_without_the_marker(tmp_path):
    r"""_detect_encoding only looked for a UTF-16 BOM. Every log under
    C:\Windows\Logs is UTF-8 WITH one, so the first line arrived as
    "\ufeff2026-..." , failed the timestamp regex, and was dropped -- the
    first line of every CBS, DISM and Windows Update log."""
    path = tmp_path / "bom.log"
    with open(path, "wb") as handle:
        handle.write(b"\xef\xbb\xbf" + CBS_LINES[0].encode("utf-8") + b"\r\n")
    entries = CBSParser(str(path)).parse()
    assert len(entries) == 1
    assert not entries[0].message.startswith("\ufeff")
    assert entries[0].timestamp.year == 2026


def test_utf16_is_still_detected(tmp_path):
    """The UTF-16 branch was there for a reason; do not lose it."""
    path = tmp_path / "u16.log"
    with open(path, "wb") as handle:
        handle.write(CBS_LINES[0].encode("utf-16"))
    assert CBSParser(str(path))._detect_encoding() == "utf-16"


def test_a_file_with_no_bom_is_unaffected(tmp_path):
    path = tmp_path / "plain.log"
    path.write_text(CBS_LINES[0] + "\n", encoding="utf-8")
    assert len(CBSParser(str(path)).parse()) == 1


# ---- continuation lines -------------------------------------------------

def _parse(cls, lines, tmp_path, name):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return cls(str(path)).parse()


def test_cbs_keeps_every_line(tmp_path):
    """7.4% of a real CBS.log does not match the timestamped pattern -- it is
    continuation detail belonging to the entry above. Dropping it means the
    tab shows a message whose explanation is missing."""
    entries = _parse(CBSParser, CBS_LINES, tmp_path, "cbs.log")
    assert len(entries) == len(CBS_LINES)


def test_a_continuation_line_keeps_its_own_text(tmp_path):
    entries = _parse(CBSParser, CBS_LINES, tmp_path, "cbs.log")
    assert "AddCat" in entries[2].message


def test_a_continuation_line_inherits_the_entry_it_belongs_to(tmp_path):
    """It happened at the moment of the record above it, not at year one, and
    it belongs to that record's component."""
    entries = _parse(CBSParser, CBS_LINES, tmp_path, "cbs.log")
    assert entries[2].timestamp == entries[1].timestamp
    assert entries[2].source == entries[1].source


def test_a_continuation_line_does_not_claim_a_severity_it_lacks(tmp_path):
    """Inheriting "Warning" would colour a detail line as a warning of its
    own and inflate any count of them."""
    entries = _parse(CBSParser, CBS_LINES, tmp_path, "cbs.log")
    assert entries[2].raw.get("continuation") is True


def test_a_leading_orphan_line_is_still_kept(tmp_path):
    """Nothing above it to inherit from -- it must still not vanish."""
    entries = _parse(CBSParser, ["  orphan before anything"], tmp_path, "o.log")
    assert len(entries) == 1
    assert "orphan" in entries[0].message


def test_dism_keeps_every_line_too(tmp_path):
    entries = _parse(DISMParser, DISM_LINES, tmp_path, "dism.log")
    assert len(entries) == len(DISM_LINES)
    assert entries[1].timestamp == entries[0].timestamp


def test_a_normal_line_is_not_marked_as_a_continuation(tmp_path):
    entries = _parse(CBSParser, CBS_LINES, tmp_path, "cbs.log")
    assert entries[0].raw.get("continuation") is not True


def test_blank_lines_are_still_skipped(tmp_path):
    """Keeping every line does not mean keeping the empty ones."""
    entries = _parse(CBSParser, [CBS_LINES[0], "", "   ", CBS_LINES[1]],
                     tmp_path, "blank.log")
    assert len(entries) == 2


def test_severity_and_component_still_parse(tmp_path):
    """The regex path must be untouched by all of the above."""
    entries = _parse(CBSParser, CBS_LINES, tmp_path, "cbs.log")
    assert entries[1].level == "Warning"
    assert entries[1].source == "CBS"
    assert entries[3].level == "Error"


# ---- against the real file ---------------------------------------------

def test_the_real_cbs_log_loses_nothing(tmp_path):
    import os
    path = r"C:\Windows\Logs\CBS\CBS.log"
    if not os.path.exists(path):
        pytest.skip("no CBS.log on this machine")
    raw = open(path, encoding="utf-8-sig", errors="replace").read()
    expected = len([l for l in raw.splitlines() if l.strip()])
    entries = CBSParser(path).parse()
    assert len(entries) == expected, (
        f"{expected - len(entries)} lines were dropped")
