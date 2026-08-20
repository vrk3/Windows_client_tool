"""Exposes the open log to the app's global search bar, as every other
module does."""
import re
from typing import List

from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult


class LogSearchProvider(SearchProvider):
    module_name = "LogViewer"

    #: The bar queries every provider on each keystroke and merges the
    #: results, so one module must not be able to drown the rest.
    MAX_RESULTS = 200

    def __init__(self) -> None:
        self._entries: List = []
        self._source = ""

    def set_entries(self, entries, source: str = "") -> None:
        self._entries = list(entries)
        self._source = source

    def search(self, query: SearchQuery) -> List[SearchResult]:
        text = (query.text or "").strip()
        # An empty query means the user has not typed anything yet; answering
        # it with the whole log is not a search.
        if not text or not self._entries:
            return []

        matcher = None
        if query.regex_enabled:
            try:
                matcher = re.compile(text, re.IGNORECASE)
            except re.error:
                # A half-typed pattern is a typo, not a failure.
                matcher = None
        needle = text.lower()

        results = []
        for entry in self._entries:
            haystack = f"{entry.source} {entry.level} {entry.message}"
            if matcher is not None:
                if not matcher.search(haystack):
                    continue
            elif needle not in haystack.lower():
                continue
            if query.types and entry.level not in query.types:
                continue
            if query.date_from and entry.timestamp < query.date_from:
                continue
            if query.date_to and entry.timestamp > query.date_to:
                continue
            results.append(SearchResult(
                timestamp=entry.timestamp,
                source=entry.source or self._source,
                type=entry.level,
                summary=entry.message[:200],
                detail=entry.message,
                relevance=1.0,
            ))
            if len(results) >= self.MAX_RESULTS:
                break
        return results

    def get_filterable_fields(self) -> List[FilterField]:
        return [FilterField(name="level", label="Severity",
                            values=["Error", "Warning", "Info", "Debug"])]
