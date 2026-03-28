# src/modules/tweaks/tweak_search_provider.py
import os
from datetime import datetime
from typing import List

from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult
from modules.tweaks.tweak_engine import TweakEngine

_DEFS_DIR = os.path.join(os.path.dirname(__file__), "definitions")
_FILES = ["privacy.json", "performance.json", "telemetry.json",
          "ui_tweaks.json", "services.json"]

_CATEGORY_LABELS = {
    "privacy.json":     "Privacy",
    "performance.json": "Performance",
    "telemetry.json":   "Telemetry",
    "ui_tweaks.json":   "UI Tweaks",
    "services.json":    "Services",
}


class TweakSearchProvider(SearchProvider):
    module_name = "Tweaks"

    def search(self, query: SearchQuery) -> List[SearchResult]:
        text = query.text.lower()
        results: List[SearchResult] = []
        for fname in _FILES:
            path = os.path.join(_DEFS_DIR, fname)
            if not os.path.exists(path):
                continue
            category = _CATEGORY_LABELS.get(fname, fname)
            for tweak in TweakEngine.load_definitions(path):
                if text and (
                    text not in tweak["name"].lower() and
                    text not in tweak.get("description", "").lower()
                ):
                    continue
                results.append(SearchResult(
                    timestamp=datetime.now(),
                    source=category,
                    type="tweak",
                    summary=tweak["name"],
                    detail=tweak.get("description", ""),
                    relevance=1.0,
                ))
        return results

    def get_filterable_fields(self) -> List[FilterField]:
        return [
            FilterField(
                name="category",
                label="Category",
                values=list(_CATEGORY_LABELS.values()),
            ),
            FilterField(
                name="risk",
                label="Risk",
                values=["low", "medium", "high"],
            ),
        ]
