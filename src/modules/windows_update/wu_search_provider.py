import re
from typing import List

from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult
from core.types import LogEntry


class WUSearchProvider(SearchProvider):
    """Search provider for Windows Update log entries."""

    def __init__(self):
        self._entries: List[LogEntry] = []

    def set_entries(self, entries: List[LogEntry]) -> None:
        self._entries = entries

    def search(self, query: SearchQuery) -> List[SearchResult]:
        results = []
        for entry in self._entries:
            if not self._matches(entry, query):
                continue
            results.append(SearchResult(
                timestamp=entry.timestamp,
                source=entry.source,
                type=entry.level,
                summary=entry.message[:200],
                detail=entry.raw,
                relevance=1.0,
            ))
        return results

    def _matches(self, entry: LogEntry, query: SearchQuery) -> bool:
        if query.text:
            haystack = f"{entry.source} {entry.level} {entry.message}"
            if query.regex_enabled:
                try:
                    if not re.search(query.text, haystack, re.IGNORECASE):
                        return False
                except re.error:
                    return False
            else:
                if query.text.lower() not in haystack.lower():
                    return False

        if query.date_from and entry.timestamp < query.date_from:
            return False
        if query.date_to and entry.timestamp > query.date_to:
            return False

        if query.types and entry.level not in query.types:
            return False

        if query.sources and entry.source not in query.sources:
            return False

        return True

    def get_filterable_fields(self) -> List[FilterField]:
        sources = list(set(e.source for e in self._entries))
        return [
            FilterField(name="source", label="Source", values=sorted(sources)),
            FilterField(name="level", label="Level", values=["Error", "Warning", "Info"]),
        ]
