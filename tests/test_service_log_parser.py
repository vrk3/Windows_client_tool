r"""CBS, DISM and Panther logs state their own severity; stop guessing it.

`parse_plain` decides Error/Warning by grepping the whole line for
`error|fail|fatal|exception`, which on these files is wrong in one direction
only -- noise, never silence. Measured on this machine: CBS.log **32** lines
that say `Info` and render red, `CbsPersist_20260829190803.log` **834**,
`CbsPersist_20260827190818.log` **102**, `dism.log` **188**.

The same lines also carry a component and, in DISM's case, a thread id, and
the viewer's Component and Thread columns were empty on every real log --
0px of content, one entry (`All`) in the dropdown.

The format is fixed-column and was MEASURED, not guessed, across CBS.log,
CbsPersist, dism.log, setupact.log and setuperr.log (62,208 head lines):

    2026-08-29 22:08:03, Info                  CBS    TI: --- Initializing ---
    0         1         2         3         4         5
    0123456789012345678901234567890123456789012345678901234567890
    [--- timestamp ---] , [--- severity ---][comp ][--- message ---]
     0..18              19  21..42           43..50  50..

Severity starts at col 21 on 100% of head-matching lines, and the component
field [43:50) overflows col 49 on NONE of them. Only three severity tokens
exist in all five files: Info (61,790), Warning (359), Error (59).

Every line below is verbatim from this machine.
"""
from datetime import datetime

from modules.log_viewer.cmtrace_parser import (parse, parse_service_log,
                                               looks_like_service_log)

#: Says `Info`, and contains the word "failed". The word-match calls it Error.
CBS_INFO_THAT_READS_AS_ERROR = (
    "2026-08-29 22:08:03, Info                  CBS    InternalOpenPackage "
    "failed for Package_for_KB3025096~31bf3856ad364e35~amd64~~6.4.1.0 "
    "[HRESULT = 0x800f0805 - CBS_E_INVALID_PACKAGE]"
)
CBS_INFO = (
    "2026-08-29 22:08:03, Info                  CBS    TI: --- Initializing "
    "Trusted Installer ---"
)
#: The component field is genuinely blank on 7,059 of CBS.log's lines and the
#: message still starts at column 50.
CBS_BLANK_COMPONENT = (
    "2026-08-29 22:48:03, Info                         Arbiter invoked from "
    "servicing stack; skip locking"
)
CBS_WARNING = (
    r"2026-08-29 22:48:03, Warning                      WatsonHelper: File "
    r"already set: [C:\WINDOWS\Logs\MoSetup\UpdateAgent.log]"
)
SETUPERR_ERROR = (
    "2026-07-21 10:36:32, Error                 MOUPG  "
    "CUnattendManager::Initialize(90): Result = 0x80070490[gle=0x00000002]"
)
DISM_WITH_TID = (
    "2026-08-24 21:45:46, Info                  DISM   API: PID=41612 "
    "TID=29016 DismApi.dll: <----- Starting DismApi.dll session -----> - "
    "DismInitializeInternal"
)
#: 206 lines of setupact.log put their message at column 32, not 50. Cutting
#: at 50 would slice `[0x090008] PANTHR ` off the front of the text.
SETUPACT_NARROW = (
    r"2026-07-21 10:36:56, Info       [0x090008] PANTHR CBlackboard::Open: "
    r"X:\$Windows.~BT\Sources\Panther\CompatScanCache.dat succeeded"
)
#: A CSI record and the first two of the 1,260 continuation lines under it.
CSI_BLOCK = "\n".join([
    "2026-08-27 22:08:36, Info                  CSI    00000287 Performing "
    "1260 operations as follows:",
    "  (0)  Uninstall:  tlc: [0b1b725eec1fd30d644b1cdd217b3d75, version "
    "4.0.15920.116, arch amd64]",
    "  (1)  Install:  tlc: [0b1b725eec1fd30d644b1cdd217b3d75, version "
    "4.0.15920.116, arch amd64]",
])
#: setupact aligns its continuations to column 35. That is padding, not
#: structure, unlike CSI's two- and four-space nesting.
SETUPACT_BLOCK = "\n".join([
    "2026-07-21 10:36:56, Info                  SP     Machine info:",
    "                                   VM: NO",
    "                                   Firmware type: UEFI",
])


def _one(line):
    entries = parse_service_log(line)
    assert len(entries) == 1
    return entries[0]


# ---- defect 2: the line states its severity -----------------------------

def test_a_stated_info_beats_the_word_match():
    """The measured 1,156 false Errors are all this one line shape."""
    assert _one(CBS_INFO_THAT_READS_AS_ERROR).level == "Info"


def test_a_stated_warning_is_read_from_the_line():
    assert _one(CBS_WARNING).level == "Warning"


def test_a_stated_error_is_read_from_the_line():
    assert _one(SETUPERR_ERROR).level == "Error"


# ---- defect 3: component and thread --------------------------------------

def test_the_component_comes_from_the_fixed_column():
    assert _one(CBS_INFO).source == "CBS"
    assert _one(DISM_WITH_TID).source == "DISM"
    assert _one(SETUPERR_ERROR).source == "MOUPG"


def test_a_blank_component_field_stays_blank():
    """Not the first word of the message, which is what a split() would give."""
    entry = _one(CBS_BLANK_COMPONENT)
    assert entry.source == ""
    assert entry.message.startswith("Arbiter invoked")


def test_a_dism_thread_id_fills_the_thread_column():
    assert _one(DISM_WITH_TID).raw.get("thread") == "29016"
    assert _one(CBS_INFO).raw.get("thread", "") == ""


# ---- defect 4: the message is only the message ---------------------------

def test_the_message_excludes_the_timestamp_and_severity_prefix():
    entry = _one(CBS_INFO)
    assert entry.message == "TI: --- Initializing Trusted Installer ---"
    assert "2026-08-29" not in entry.message
    assert "Info" not in entry.message


def test_the_timestamp_is_read_from_the_line():
    assert _one(CBS_INFO).timestamp == datetime(2026, 8, 29, 22, 8, 3)


def test_a_whole_second_timestamp_is_not_claimed_to_have_milliseconds():
    """CBS writes seconds. Rendering `.000` invents a precision it never had."""
    assert "subsecond" not in _one(CBS_INFO).raw


# ---- the narrow layout ---------------------------------------------------

def test_a_narrow_layout_line_keeps_its_whole_message():
    entry = _one(SETUPACT_NARROW)
    assert entry.source == ""
    assert entry.message.startswith("[0x090008] PANTHR CBlackboard::Open:")
    assert entry.level == "Info"


# ---- continuation lines --------------------------------------------------

def test_continuation_lines_inherit_the_record_above():
    entries = parse_service_log(CSI_BLOCK)
    assert len(entries) == 3
    head, first, second = entries
    for entry in (first, second):
        assert entry.timestamp == head.timestamp
        assert entry.level == "Info"
        assert entry.source == "CSI"
        assert entry.raw.get("continuation")
    assert not head.raw.get("continuation")
    assert first.message.startswith("  (0)  Uninstall:")


def test_alignment_padding_is_dropped_but_nesting_is_kept():
    entries = parse_service_log(SETUPACT_BLOCK)
    assert [e.message for e in entries[1:]] == ["VM: NO", "Firmware type: UEFI"]


def test_a_continuation_line_with_no_record_above_is_still_kept():
    """A tail slice can start in the middle of a 1,260-line CSI block."""
    entries = parse_service_log("  (0)  Uninstall:  tlc: [0b1b725e]")
    assert len(entries) == 1
    assert entries[0].message.strip().startswith("(0)  Uninstall:")


# ---- picking the parser --------------------------------------------------

def test_parse_picks_the_service_parser():
    entries = parse(CBS_INFO_THAT_READS_AS_ERROR)
    assert entries[0].level == "Info"
    assert entries[0].source == "CBS"


def test_cmtrace_still_wins_when_the_records_are_cmtrace():
    text = ('<![LOG[Starting]LOG]!><time="13:45:12.345+000" date="08-20-2026" '
            'component="UpdatesHandler" type="3" thread="1234">')
    entries = parse(text)
    assert entries[0].level == "Error"
    assert entries[0].source == "UpdatesHandler"


def test_plain_text_is_still_the_last_resort():
    entries = parse("just a line\nand another")
    assert [e.message for e in entries] == ["just a line", "and another"]


def test_the_sniffer_does_not_claim_arbitrary_text():
    assert not looks_like_service_log("just a line\nand another")
    assert not looks_like_service_log("")
    assert looks_like_service_log(CBS_INFO + "\n" + CBS_WARNING)
