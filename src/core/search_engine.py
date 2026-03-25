import logging
from dataclasses import asdict
from typing import List, Optional
from core.search_provider import SearchProvider, SearchQuery, SearchResult

logger = logging.getLogger(__name__)

class SearchEngine:
    def __init__(self, config_manager=None):
        self._providers: List[SearchProvider] = []
        self._presets: dict[str, SearchQuery] = {}
        self._config = config_manager
        if self._config:
            self._load_presets_from_config()

    def _load_presets_from_config(self):
        saved = self._config.get("search.presets", {})
        for name, data in saved.items():
            try:
                self._presets[name] = SearchQuery(**data)
            except (TypeError, KeyError):
                logger.warning("Failed to load preset '%s'", name)

    def _save_presets_to_config(self):
        if self._config:
            serialized = {}
            for name, query in self._presets.items():
                serialized[name] = asdict(query)
            self._config.set("search.presets", serialized)

    def register_provider(self, provider: SearchProvider) -> None:
        self._providers.append(provider)

    def execute(self, query: SearchQuery) -> List[SearchResult]:
        results: List[SearchResult] = []
        for provider in self._providers:
            try:
                results.extend(provider.search(query))
            except Exception:
                logger.exception("SearchEngine: provider %r failed", provider)
        results.sort(key=lambda r: r.relevance, reverse=True)
        return results

    def save_preset(self, name: str, query: SearchQuery) -> None:
        self._presets[name] = query
        self._save_presets_to_config()

    def load_preset(self, name: str) -> Optional[SearchQuery]:
        return self._presets.get(name)

    def get_all_presets(self) -> List[str]:
        return list(self._presets.keys())
