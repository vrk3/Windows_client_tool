r"""Servicing sessions: who asked for the work, and did it fail.

The markers here were found by reading this machine's real CBS logs, not
assumed. The plan for this task guessed at "Beginning/Ending TrustedInstaller"
and that phrase does not appear in either log -- a detector built on it would
have found zero sessions on every file and looked like it worked.

What CBS actually writes is:

    Session: 31275276_4079573531 initialized by client WindowsUpdateAgent

12 of them in CBS.log across three clients, 9 in the 138,683-record archive
across six -- including `DISM Package Manager Provider` and `SPP`. The client
is the useful half: it says which component asked for the servicing that
failed.
"""
from datetime import datetime, timedelta

import pytest

from core.types import LogEntry
from modules.log_viewer.sessions import sessions

BASE = datetime(2026, 8, 31, 10, 0, 0)


def _entry(message, level="Info", seconds=0):
    return LogEntry(timestamp=BASE + timedelta(seconds=seconds),
                    source="CBS", level=level, message=message,
                    raw={"thread": "1"})


def _start(session_id="31275276_4079573531", client="WindowsUpdateAgent",
           seconds=0):
    return _entry(f"Session: {session_id} initialized by client {client}",
                  seconds=seconds)


def test_a_marker_starts_a_session():
    found = sessions([_start(), _entry("work")])
    assert len(found) == 1
    assert found[0].session_id == "31275276_4079573531"
    assert found[0].client == "WindowsUpdateAgent"


def test_a_session_runs_to_the_end_when_it_is_the_last_one():
    found = sessions([_start(), _entry("work"), _entry("more")])
    assert found[0].start == 0
    assert found[0].end == 2


def test_a_second_marker_ends_the_first_session():
    found = sessions([_start(client="Arbiter"), _entry("work"),
                      _start(session_id="other", client="SPP"),
                      _entry("more")])
    assert len(found) == 2
    assert found[0].end == 1, "the first session stops before the second"
    assert found[1].start == 2
    assert [s.client for s in found] == ["Arbiter", "SPP"]


def test_records_before_the_first_marker_belong_to_no_session():
    """A tail slice routinely opens mid-session, and inventing one to hold
    the preamble would claim a client that never asked for it."""
    found = sessions([_entry("orphaned preamble"), _start()])
    assert len(found) == 1
    assert found[0].start == 1


def test_a_session_carrying_an_error_is_marked_failed():
    found = sessions([_start(), _entry("it broke", level="Error")])
    assert found[0].errors == 1
    assert found[0].failed is True


def test_a_clean_session_is_not_marked_failed():
    found = sessions([_start(), _entry("fine")])
    assert found[0].errors == 0
    assert found[0].failed is False


def test_errors_are_attributed_to_the_session_they_fall_in():
    found = sessions([_start(client="A"), _entry("bad", level="Error"),
                      _start(session_id="s2", client="B"), _entry("fine")])
    assert found[0].errors == 1
    assert found[1].errors == 0


def test_no_markers_means_no_sessions():
    assert sessions([_entry("just some work")]) == []
    assert sessions([]) == []


def test_a_marker_as_the_very_last_record_still_yields_a_session():
    found = sessions([_entry("work"), _start()])
    assert len(found) == 1
    assert found[0].start == found[0].end == 1


def test_the_session_carries_when_it_started():
    found = sessions([_start(seconds=90)])
    assert found[0].when == BASE + timedelta(seconds=90)


def test_a_client_name_with_spaces_is_captured_whole():
    """`DISM Package Manager Provider` is a real client on this machine."""
    found = sessions([_start(client="DISM Package Manager Provider")])
    assert found[0].client == "DISM Package Manager Provider"


def test_a_line_merely_mentioning_a_session_is_not_a_marker():
    assert sessions([_entry("Session: 123 was mentioned in passing")]) == []


# ---- the panel column ---------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

SESSIONED = (
    '<![LOG[Session: 31275276_4079573531 initialized by client '
    'WindowsUpdateAgent]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'
    '<![LOG[it broke]LOG]!><time="13:45:11.000+000" date="08-20-2026" '
    'component="CBS" context="" type="3" thread="1" file="a.cpp:2">\n'
    '<![LOG[Session: 31275276_4079608590 initialized by client Arbiter]LOG]!>'
    '<time="13:45:12.000+000" date="08-20-2026" component="CBS" context="" '
    'type="1" thread="1" file="a.cpp:3">\n'
    '<![LOG[all fine]LOG]!><time="13:45:13.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:4">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(SESSIONED, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def _rows(listing):
    return [listing.item(row).text() for row in range(listing.count())]


def test_the_panel_lists_each_session_by_client(viewer):
    viewer.summary_button.setChecked(True)
    rows = _rows(viewer.summary_sessions)
    assert any("WindowsUpdateAgent" in text for text in rows)
    assert any("Arbiter" in text for text in rows)


def test_a_failed_session_says_how_many_errors(viewer):
    viewer.summary_button.setChecked(True)
    failed = next(t for t in _rows(viewer.summary_sessions)
                  if "WindowsUpdateAgent" in t)
    assert "1 error" in failed


def test_a_clean_session_says_so(viewer):
    viewer.summary_button.setChecked(True)
    clean = next(t for t in _rows(viewer.summary_sessions) if "Arbiter" in t)
    assert "clean" in clean


def test_clicking_a_session_goes_to_where_it_started(viewer):
    viewer.summary_button.setChecked(True)

    viewer.summary_sessions.itemClicked.emit(
        viewer.summary_sessions.item(0))

    entry = viewer.model.entry(viewer.table.currentIndex().row())
    assert "WindowsUpdateAgent" in entry.message


def test_a_log_with_no_sessions_says_so_rather_than_being_blank(qapp,
                                                               tmp_path):
    path = tmp_path / "plain.log"
    path.write_text(
        '<![LOG[just work]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
        'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n',
        encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        widget.summary_button.setChecked(True)
        rows = _rows(widget.summary_sessions)
        assert rows and "no servicing sessions" in rows[0].lower()
    finally:
        widget.stop()
