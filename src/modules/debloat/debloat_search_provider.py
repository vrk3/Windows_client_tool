# DebloatModule search provider stub
from typing import List

from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult


class DebloatSearchProvider(SearchProvider):
    """Search provider for debloat module. Returns no searchable results
    since the module operates on app removal and registry tweaks."""

    module_name = "Debloat"

    def search(self, query: SearchQuery) -> List[SearchResult]:
        return []

    def get_filterable_fields(self) -> List[FilterField]:
        return []
