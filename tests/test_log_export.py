"""Getting the filtered rows out.

Both writers emit the PARSED view, not the original bytes: keeping every
original line would roughly double the model's footprint at its 200,000
cap, and reconstructing one from raw["line"] is unreliable once the file is
tail-capped, followed, or read with a rolled .lo_ sibling. The text writer
says so in its header so nobody mistakes it for a copy of the file.
"""
import csv
import io
from datetime import datetime

from core.types import LogEntry
from modules.log_viewer.log_export import as_csv, as_text, format_stamp


def _entry(message, level="Info", source="CBS", thread="42"):
    return LogEntry(timestamp=datetime(2026, 8, 30, 12, 0, 0), source=source,
                    level=level, message=message, raw={"thread": thread})


def test_text_carries_the_fields_of_each_row():
    out = as_text([_entry("something happened")])
    assert "2026-08-30 12:00:00" in out
    assert "Info" in out and "CBS" in out and "something happened" in out


def test_the_text_header_says_this_is_the_parsed_view():
    out = as_text([_entry("x")])
    assert out.splitlines()[0].startswith("#")
    assert "parsed" in out.splitlines()[0].lower()


def test_the_clipboard_form_carries_no_header():
    out = as_text([_entry("x")], header=False)
    assert not out.startswith("#")


def test_csv_survives_a_comma_a_quote_and_a_newline():
    nasty = 'a, b "quoted" and\na second line'
    parsed = list(csv.reader(io.StringIO(as_csv([_entry(nasty)]))))
    assert parsed[0] == ["Time", "Severity", "Component", "Thread", "Message"]
    assert parsed[1][4] == nasty


def test_an_unknown_timestamp_exports_blank_rather_than_year_one():
    from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME

    entry = LogEntry(timestamp=UNKNOWN_TIME, source="", level="Info",
                     message="x", raw={})
    assert "0001-01-01" not in as_text([entry])
    assert "0001-01-01" not in as_csv([entry])


def test_exporting_nothing_is_not_a_crash():
    assert as_csv([]).strip().startswith("Time")
    assert isinstance(as_text([], header=False), str)


# ---- the public formatter LogModel's TIME column also calls -------------
#
# This used to be a private `_stamp`, duplicated (independently) in
# log_model.data()'s TIME branch. Promoted to public so there is one
# implementation of "UNKNOWN_TIME -> blank, subsecond -> milliseconds, else
# whole seconds" rather than two that happen to agree today.

def test_format_stamp_is_blank_for_an_unknown_timestamp():
    from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME

    entry = LogEntry(timestamp=UNKNOWN_TIME, source="", level="Info",
                     message="x", raw={})
    assert format_stamp(entry) == ""


def test_format_stamp_shows_milliseconds_only_when_the_log_wrote_them():
    with_sub = LogEntry(timestamp=datetime(2026, 8, 30, 12, 0, 0, 123000),
                        source="", level="Info", message="x",
                        raw={"subsecond": True})
    without_sub = LogEntry(timestamp=datetime(2026, 8, 30, 12, 0, 0, 123000),
                           source="", level="Info", message="x", raw={})
    assert format_stamp(with_sub) == "2026-08-30 12:00:00.123"
    assert format_stamp(without_sub) == "2026-08-30 12:00:00"
