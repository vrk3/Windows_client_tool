import pytest
from datetime import datetime
from core.search_provider import SearchProvider, SearchQuery, SearchResult, FilterField
from core.search_engine import SearchEngine

class MockProvider(SearchProvider):
    def __init__(self, results):
        self._results = results
    def search(self, query):
        return [r for r in self._results if query.text.lower() in r.summary.lower()]
    def get_filterable_fields(self):
        return [FilterField(name="type", label="Type", values=["Error", "Warning"])]

def _make_result(summary, source="test", type_="Error"):
    return SearchResult(timestamp=datetime(2026, 3, 25), source=source, type=type_, summary=summary, detail=None, relevance=1.0)

def test_register_provider_and_search():
    engine = SearchEngine()
    provider = MockProvider([_make_result("disk error"), _make_result("network ok")])
    engine.register_provider(provider)
    results = engine.execute(SearchQuery(text="disk"))
    assert len(results) == 1
    assert results[0].summary == "disk error"

def test_multiple_providers():
    engine = SearchEngine()
    engine.register_provider(MockProvider([_make_result("disk error", source="logs")]))
    engine.register_provider(MockProvider([_make_result("disk full", source="events")]))
    assert len(engine.execute(SearchQuery(text="disk"))) == 2

def test_empty_query_returns_no_results():
    engine = SearchEngine()
    engine.register_provider(MockProvider([_make_result("something")]))
    assert len(engine.execute(SearchQuery(text="nonexistent"))) == 0

def test_no_providers_returns_empty():
    assert SearchEngine().execute(SearchQuery(text="anything")) == []

def test_save_and_load_preset():
    engine = SearchEngine()
    query = SearchQuery(text="critical errors", types=["Error"], regex_enabled=True)
    engine.save_preset("critical_only", query)
    loaded = engine.load_preset("critical_only")
    assert loaded.text == "critical errors"
    assert loaded.types == ["Error"]
    assert loaded.regex_enabled is True

def test_load_nonexistent_preset_returns_none():
    assert SearchEngine().load_preset("nonexistent") is None

def test_get_all_presets():
    engine = SearchEngine()
    engine.save_preset("a", SearchQuery(text="a"))
    engine.save_preset("b", SearchQuery(text="b"))
    assert sorted(engine.get_all_presets()) == ["a", "b"]
