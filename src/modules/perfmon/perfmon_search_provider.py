import re
from datetime import datetime
from typing import List

from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult
from core.types import LogEntry


class PerfMonSearchProvider(SearchProvider):
    """Search provider for PerfMon alert history."""

    module_name = "PerfMon"

    def __init__(self):
        self._alerts: List[LogEntry] = []

    def add_alert(self, entry: LogEntry) -> None:
        self._alerts.insert(0, entry)

    def set_entries(self, entries: List[LogEntry]) -> None:
        self._alerts = entries

    def search(self, query: SearchQuery) -> List[SearchResult]:
        results = []
        for entry in self._alerts:
            if query.text:
                haystack = f"{entry.source} {entry.level} {entry.message}"
                if query.regex_enabled:
                    try:
                        if not re.search(query.text, haystack, re.IGNORECASE):
                            continue
                    except re.error:
                        continue
                else:
                    if query.text.lower() not in haystack.lower():
                        continue
            if query.types and entry.level not in query.types:
                continue
            results.append(SearchResult(
                timestamp=entry.timestamp,
                source="PerfMon",
                type=entry.level,
                summary=entry.message[:200],
                detail=entry.raw,
                relevance=1.0,
            ))
        return results

    def get_filterable_fields(self) -> List[FilterField]:
        return [
            FilterField(name="level", label="Level", values=["Warning", "Error"]),
        ]
