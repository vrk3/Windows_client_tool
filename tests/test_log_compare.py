"""A working machine's log beside a broken one.

Aligned on WHAT HAPPENED, not on when: two machines never share a clock, and
even one machine's own clock jumps (setupact moves ten hours backwards at a
phase boundary). The normaliser from the clustering work is what makes two
lines about different packages comparable.

The output answers one question: which steps happened on one and not the
other.
"""
from datetime import datetime, timedelta


from core.types import LogEntry
from modules.log_viewer.compare import compare

BASE = datetime(2026, 8, 27, 10, 0, 0)


def _entry(message, seconds=0):
    return LogEntry(timestamp=BASE + timedelta(seconds=seconds), source="CBS",
                    level="Info", message=message, raw={"thread": "1"})


def test_identical_logs_report_no_differences():
    rows = [_entry("step one"), _entry("step two", 1)]
    result = compare(rows, list(rows))
    assert result.only_in_left == []
    assert result.only_in_right == []
    assert result.identical


def test_a_step_present_in_one_only_is_reported():
    left = [_entry("step one"), _entry("step two", 1)]
    right = [_entry("step one")]

    result = compare(left, right)

    assert result.only_in_left == ["step two"]
    assert result.only_in_right == []
    assert not result.identical


def test_a_step_present_in_the_other_only_is_reported():
    result = compare([_entry("shared")], [_entry("shared"), _entry("extra", 1)])
    assert result.only_in_right == ["extra"]


def test_alignment_is_on_the_message_not_the_timestamp():
    """The same step at wildly different times is the SAME step."""
    left = [_entry("step one", 0)]
    right = [_entry("step one", 99999)]
    assert compare(left, right).identical


def test_lines_differing_only_by_package_are_the_same_step():
    """This is why the normaliser is used: two machines service different
    packages and every line would otherwise differ."""
    left = [_entry("Installing A~31bf3856ad364e35~amd64~~1.0")]
    right = [_entry("Installing B~31bf3856ad364e35~amd64~~2.0")]
    assert compare(left, right).identical


def test_genuinely_different_steps_are_still_different():
    result = compare([_entry("Installing thing")], [_entry("Removing thing")])
    assert not result.identical


def test_a_step_repeated_more_often_on_one_side_is_reported():
    """"Ran once" and "ran forty times" are not the same servicing run."""
    left = [_entry("retrying"), _entry("retrying", 1), _entry("retrying", 2)]
    right = [_entry("retrying")]

    result = compare(left, right)

    assert result.counts_differ, "a 3x vs 1x difference went unreported"


def test_two_empty_logs_are_identical():
    assert compare([], []).identical


def test_an_empty_log_against_a_full_one_reports_everything():
    result = compare([], [_entry("something")])
    assert result.only_in_right == ["something"]


def test_the_report_reads_as_sentences():
    result = compare([_entry("only here")], [_entry("only there")])
    text = result.as_text()
    assert "only here" in text and "only there" in text


def test_the_report_says_so_when_they_match():
    assert "no differences" in compare([_entry("x")], [_entry("x")]).as_text().lower()


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

ONE = (
    '<![LOG[step one]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
    '<![LOG[step two]LOG]!><time="13:45:11.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:2">\n'
)
TWO = (
    '<![LOG[step one]LOG]!><time="09:00:00.000+000" date="01-01-2020" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
)


def test_the_pane_compares_the_open_log_against_another(qapp, tmp_path):
    here = tmp_path / "mine.log"
    here.write_text(ONE, encoding="utf-8")
    other = tmp_path / "theirs.log"
    other.write_text(TWO, encoding="utf-8")

    widget = LogViewerWidget()
    try:
        widget.open(str(here))
        text = widget.compare_with(str(other))
        assert "step two" in text
        assert "Only in the first log" in text
    finally:
        widget.stop()


def test_comparing_against_an_unreadable_file_says_why(qapp, tmp_path):
    here = tmp_path / "mine.log"
    here.write_text(ONE, encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(here))
        text = widget.compare_with(str(tmp_path / "nope.log"))
        assert "could not" in text.lower() or "no records" in text.lower()
    finally:
        widget.stop()
