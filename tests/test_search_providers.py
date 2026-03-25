"""Tests for per-module search providers: CBS, DISM, WU, CrashDumps, EventViewer."""
import pytest
from datetime import datetime

from core.types import LogEntry
from core.search_provider import SearchQuery


def _entry(message, level="Error", source="TestSource", ts=None):
    return LogEntry(
        timestamp=ts or datetime(2026, 3, 25, 12, 0, 0),
        source=source,
        level=level,
        message=message,
        raw={"raw": message},
    )


# ---------------------------------------------------------------------------
# Shared behaviour helper — every provider must satisfy these
# ---------------------------------------------------------------------------

def _run_shared_cases(provider_cls):
    """Run common search cases against any LogEntry-based search provider."""
    provider = provider_cls()

    # Empty entries → empty results
    assert provider.search(SearchQuery(text="anything")) == []

    entries = [
        _entry("disk failure detected", level="Error"),
        _entry("network adapter reset", level="Warning"),
        _entry("service started normally", level="Info"),
    ]
    provider.set_entries(entries)

    # Text match (case-insensitive)
    results = provider.search(SearchQuery(text="disk"))
    assert len(results) == 1
    assert "disk failure" in results[0].summary

    # No match
    assert provider.search(SearchQuery(text="ZZZNOTFOUND")) == []

    # Empty text → returns all (no text filter)
    assert len(provider.search(SearchQuery(text=""))) == 3

    # Type filter: only Errors
    results = provider.search(SearchQuery(text="", types=["Error"]))
    assert all(r.type == "Error" for r in results)
    assert len(results) == 1

    # Type filter: empty list = no filter
    assert len(provider.search(SearchQuery(text="", types=[]))) == 3

    # Date filter: exclude everything before a future date
    future = datetime(2030, 1, 1)
    assert provider.search(SearchQuery(text="", date_from=future)) == []

    # Date filter: include everything before a far-future date
    assert len(provider.search(SearchQuery(text="", date_to=datetime(2030, 1, 1)))) == 3

    # Regex match
    results = provider.search(SearchQuery(text=r"disk|network", regex_enabled=True))
    assert len(results) == 2

    # Invalid regex → no results (not a crash)
    results = provider.search(SearchQuery(text=r"[invalid", regex_enabled=True))
    assert results == []

    # get_filterable_fields returns a list (may be empty)
    fields = provider.get_filterable_fields()
    assert isinstance(fields, list)


# ---------------------------------------------------------------------------
# CBS
# ---------------------------------------------------------------------------

def test_cbs_search_provider():
    from modules.cbs_log.cbs_search_provider import CBSSearchProvider
    _run_shared_cases(CBSSearchProvider)


def test_cbs_search_provider_module_name():
    from modules.cbs_log.cbs_search_provider import CBSSearchProvider
    assert CBSSearchProvider.module_name == "CBS"


# ---------------------------------------------------------------------------
# DISM
# ---------------------------------------------------------------------------

def test_dism_search_provider():
    from modules.dism_log.dism_search_provider import DISMSearchProvider
    _run_shared_cases(DISMSearchProvider)


def test_dism_search_provider_module_name():
    from modules.dism_log.dism_search_provider import DISMSearchProvider
    assert DISMSearchProvider.module_name == "DISM"


# ---------------------------------------------------------------------------
# Windows Update
# ---------------------------------------------------------------------------

def test_wu_search_provider():
    from modules.windows_update.wu_search_provider import WUSearchProvider
    _run_shared_cases(WUSearchProvider)


def test_wu_search_provider_module_name():
    from modules.windows_update.wu_search_provider import WUSearchProvider
    assert WUSearchProvider.module_name == "WindowsUpdate"


# ---------------------------------------------------------------------------
# Crash Dumps
# ---------------------------------------------------------------------------

def test_crash_dump_search_provider():
    from modules.crash_dumps.crash_dump_search_provider import CrashDumpSearchProvider
    _run_shared_cases(CrashDumpSearchProvider)


def test_crash_dump_search_provider_module_name():
    from modules.crash_dumps.crash_dump_search_provider import CrashDumpSearchProvider
    assert CrashDumpSearchProvider.module_name == "CrashDumps"


# ---------------------------------------------------------------------------
# Event Viewer
# ---------------------------------------------------------------------------

def test_event_viewer_search_provider():
    from modules.event_viewer.event_search_provider import EventViewerSearchProvider
    _run_shared_cases(EventViewerSearchProvider)


def test_event_viewer_search_provider_module_name():
    from modules.event_viewer.event_search_provider import EventViewerSearchProvider
    assert EventViewerSearchProvider.module_name == "EventViewer"


def test_event_viewer_search_result_fields():
    from modules.event_viewer.event_search_provider import EventViewerSearchProvider
    provider = EventViewerSearchProvider()
    provider.set_entries([_entry("test message", level="Warning", source="Application")])
    results = provider.search(SearchQuery(text="test"))
    assert len(results) == 1
    r = results[0]
    assert r.source == "Application"
    assert r.type == "Warning"
    assert "test message" in r.summary
    assert r.relevance == 1.0
