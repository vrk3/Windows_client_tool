"""An excerpt with its provenance attached.

Rows pasted into a ticket are not evidence of anything on their own. Which
files they came from, how big those files are, what span they cover, HOW MUCH
of each was actually loaded, and what was being filtered at the time -- that
is what makes the excerpt mean something.

The loaded-fraction line is the one that matters most: a 32 MB window over a
381 MB archive that does not say so implies the whole file was searched.
"""
from datetime import datetime, timedelta

import pytest

from core.types import LogEntry
from modules.log_viewer.log_export import as_evidence

BASE = datetime(2026, 8, 27, 10, 0, 0)


def _entry(message, seconds=0, level="Info"):
    return LogEntry(timestamp=BASE + timedelta(seconds=seconds), source="CBS",
                    level=level, message=message, raw={"thread": "1"})


SOURCES = [
    {"name": "CBS.log", "path": r"C:\Windows\Logs\CBS\CBS.log",
     "size": 1_800_000, "loaded": 1_800_000,
     "first": BASE, "last": BASE + timedelta(hours=2)},
    {"name": "CbsPersist_x.log", "path": r"C:\Windows\Logs\CBS\big.log",
     "size": 380_976_172, "loaded": 33_554_432,
     "first": BASE, "last": BASE + timedelta(hours=5)},
]
FILTERS = {"Filter": "hresult", "Hide": "detectParent",
           "Severity": "Error", "Component": "CBS"}


def _bundle(**overrides):
    fields = dict(entries=[_entry("it broke", level="Error")],
                  sources=SOURCES, filters=FILTERS, shown=1, total=138_683)
    fields.update(overrides)
    return as_evidence(**fields)


def test_the_bundle_names_every_source():
    text = _bundle()
    assert "CBS.log" in text
    assert "CbsPersist_x.log" in text


def test_each_source_carries_its_size_and_span():
    text = _bundle()
    assert "2026-08-27 10:00:00" in text
    assert "MB" in text


def test_a_partly_loaded_source_says_how_much_was_read():
    """The line that stops an excerpt implying the whole file was searched."""
    text = _bundle()
    assert "32.0 MB of 363.3 MB" in text or "9%" in text


def test_a_fully_loaded_source_says_so_plainly():
    text = _bundle()
    assert "whole file" in text.lower()


def test_the_filters_in_force_are_stated():
    text = _bundle()
    for name, value in FILTERS.items():
        assert name in text and value in text


def test_no_filters_says_so_rather_than_leaving_it_blank():
    """A blank filter section reads as "the filters were not recorded"."""
    text = _bundle(filters={})
    assert "no filters" in text.lower()


def test_the_counts_are_stated():
    text = _bundle()
    assert "1" in text and "138,683" in text


def test_the_rows_themselves_are_included():
    assert "it broke" in _bundle()


def test_a_bundle_with_no_rows_is_still_a_bundle():
    text = _bundle(entries=[])
    assert "CBS.log" in text, "provenance survives an empty excerpt"


def test_the_bundle_says_it_is_a_parsed_view():
    """The same honesty the other exports carry: not a byte-for-byte copy."""
    assert "not a byte-for-byte copy" in _bundle()


# ---- the pane gathers the provenance ------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

CMTRACE = (
    '<![LOG[it broke]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
    'component="CBS" context="" type="3" thread="1" file="a.cpp:1">\n'
    '<![LOG[all fine]LOG]!><time="13:45:11.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:2">\n'
)


@pytest.fixture
def viewer(qapp, tmp_path):
    path = tmp_path / "cbs.log"
    path.write_text(CMTRACE, encoding="utf-8")
    widget = LogViewerWidget()
    widget.open(str(path))
    yield widget
    widget.stop()


def test_the_pane_names_the_open_log_with_its_size_and_span(viewer):
    text = viewer.evidence_bundle()
    assert "cbs.log" in text
    assert "2026-08-20 13:45:10" in text


def test_the_pane_reports_the_filters_it_is_using(viewer):
    viewer.filter_box.setText("broke")
    text = viewer.evidence_bundle()
    assert "broke" in text and "Filter" in text


def test_the_bundle_carries_only_the_visible_rows(viewer):
    viewer.filter_box.setText("broke")
    text = viewer.evidence_bundle()
    assert "it broke" in text
    assert "all fine" not in text


def test_a_fully_loaded_small_log_says_the_whole_file(viewer):
    assert "whole file" in viewer.evidence_bundle().lower()


def test_the_bundle_can_be_written_to_a_file(viewer, tmp_path):
    target = str(tmp_path / "evidence.txt")
    assert viewer.write_evidence_to(target) == ""
    with open(target, encoding="utf-8") as handle:
        assert "cbs.log" in handle.read()


def test_a_source_whose_size_is_unreadable_says_so(qapp):
    r"""Found by running this on a log Windows had re-compacted into its
    .cab mid-session. "loaded: 0.0 B of 0.0 B (0%)" reads as a fact about
    the file rather than as "it is not there any more"."""
    gone = [{"name": "vanished.log", "path": r"C:\gone\vanished.log",
             "size": 0, "loaded": 0, "first": None, "last": None}]

    text = as_evidence([], gone, {}, 0, 0)

    assert "0%" not in text
    assert "could not be read" in text.lower()
