from datetime import datetime
from unittest.mock import patch, MagicMock
from modules.event_viewer.event_search_provider import EventViewerSearchProvider
from core.search_provider import SearchQuery
from core.types import LogEntry


def _make_entries():
    return [
        LogEntry(timestamp=datetime(2026, 3, 25, 10, 0), source="DCOM", level="Error", message="DCOM got error 10016"),
        LogEntry(timestamp=datetime(2026, 3, 25, 11, 0), source="Service Control Manager", level="Warning", message="service timeout"),
        LogEntry(timestamp=datetime(2026, 3, 25, 12, 0), source="Kernel-General", level="Info", message="system time changed"),
    ]


def test_search_provider_text_filter():
    sp = EventViewerSearchProvider()
    sp.set_entries(_make_entries())
    results = sp.search(SearchQuery(text="DCOM"))
    assert len(results) == 1
    assert results[0].source == "DCOM"


def test_search_provider_type_filter():
    sp = EventViewerSearchProvider()
    sp.set_entries(_make_entries())
    results = sp.search(SearchQuery(text="", types=["Error"]))
    assert len(results) == 1
    assert results[0].type == "Error"


def test_search_provider_regex():
    sp = EventViewerSearchProvider()
    sp.set_entries(_make_entries())
    results = sp.search(SearchQuery(text="DCOM.*10016", regex_enabled=True))
    assert len(results) == 1


def test_search_provider_empty_query():
    sp = EventViewerSearchProvider()
    sp.set_entries(_make_entries())
    results = sp.search(SearchQuery(text=""))
    assert len(results) == 3  # All entries match empty query


def test_filterable_fields():
    sp = EventViewerSearchProvider()
    sp.set_entries(_make_entries())
    fields = sp.get_filterable_fields()
    assert len(fields) == 2
    source_field = next(f for f in fields if f.name == "source")
    assert "DCOM" in source_field.values


def test_event_viewer_module_creates_widget():
    from modules.event_viewer.event_viewer_module import EventViewerModule
    mod = EventViewerModule()
    widget = mod.create_widget()
    assert widget is not None
    assert mod._table is not None
