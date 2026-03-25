from datetime import datetime
from core.types import LogEntry
from modules.reliability.reliability_search_provider import ReliabilitySearchProvider
from core.search_provider import SearchQuery


def test_reliability_search_provider():
    sp = ReliabilitySearchProvider()
    entries = [
        LogEntry(timestamp=datetime(2026, 3, 25, 10, 0), source="WindowsUpdate", level="Info", message="Update installed"),
        LogEntry(timestamp=datetime(2026, 3, 25, 11, 0), source="Application", level="Error", message="App crashed"),
    ]
    sp.set_entries(entries)
    results = sp.search(SearchQuery(text="crashed"))
    assert len(results) == 1
    assert results[0].type == "Error"


def test_reliability_module_creates_widget():
    from modules.reliability.reliability_module import ReliabilityModule
    mod = ReliabilityModule()
    widget = mod.create_widget()
    assert widget is not None
