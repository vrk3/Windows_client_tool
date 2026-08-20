"""Exposes scanned paths to the app's global search bar (spec 9).

Every other module registers one of these; TreeSize did not, so the one module
in the app that already holds half a million indexed paths in memory was the
one the global bar could not reach.

The query runs over the store that is already loaded -- no disk access at all.
`store.search` does the matching, so the rules here are the same ones the
module's own Find dialog uses rather than a second, subtly different set.
"""
import datetime
import logging
from typing import List, Optional

from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult

from modules.treesize.store import search as store_search
from modules.treesize.ui.formatting import format_bytes

logger = logging.getLogger(__name__)

#: FILETIME counts 100-nanosecond ticks from 1601-01-01.
_FILETIME_EPOCH = datetime.datetime(1601, 1, 1)
_TICKS_PER_SECOND = 10_000_000

FOLDER = "Folder"
FILE = "File"


def _to_datetime(filetime: int) -> datetime.datetime:
    """A FILETIME as a datetime, falling back to the epoch rather than raising.

    A node with no timestamp carries 0, and plenty of them do -- the MFT path
    reads records that genuinely lack a $STANDARD_INFORMATION time, and a
    remote target may not report one at all.
    """
    if filetime <= 0:
        return _FILETIME_EPOCH
    try:
        return _FILETIME_EPOCH + datetime.timedelta(
            seconds=filetime / _TICKS_PER_SECOND)
    except (OverflowError, OSError, ValueError):
        return _FILETIME_EPOCH


class TreeSizeSearchProvider(SearchProvider):
    """Searches the paths of the most recent scan."""

    module_name = "TreeSize"

    #: The global bar queries every provider on every keystroke and shows one
    #: merged list. Returning a whole volume's worth of paths would drown
    #: every other module's results and freeze the list building them.
    MAX_RESULTS = 200

    def __init__(self) -> None:
        self._store = None
        self._root = -1
        self._target = ""

    def set_scan(self, store, root: int, target: str) -> None:
        self._store = store
        self._root = root
        self._target = target

    def search(self, query: SearchQuery) -> List[SearchResult]:
        # An empty query means "the user has not typed anything yet". Answering
        # it with every path on the volume is not a search.
        if self._store is None or self._root < 0 or not (query.text or "").strip():
            return []
        want_folders = FOLDER in (query.types or ())
        want_files = not query.types or FILE in query.types

        inner = store_search.Query(
            pattern=query.text.strip(),
            regex=bool(query.regex_enabled),
            include_files=want_files,
            include_folders=want_folders,
            limit=self.MAX_RESULTS,
        )
        try:
            hits = store_search.search(self._store, self._root, inner)
        except Exception:                           # noqa: BLE001
            # A search must never take the whole bar down with it.
            logger.warning("TreeSize search failed", exc_info=True)
            return []

        results: List[SearchResult] = []
        total = len(hits) or 1
        for rank, hit in enumerate(hits[:self.MAX_RESULTS]):
            results.append(SearchResult(
                timestamp=_to_datetime(self._store.mtime[hit.node]),
                source=self._target or self.module_name,
                type=FOLDER if hit.is_dir else FILE,
                summary=f"{hit.name}  —  {format_bytes(hit.size)}",
                detail=self._store.path(hit.node),
                # Hits arrive largest-first, which for a disk-space tool IS
                # the relevance order: the reason to search here is "find the
                # big thing called X".
                relevance=1.0 - (rank / (total * 2.0)),
            ))
        return results

    def get_filterable_fields(self) -> List[FilterField]:
        return [FilterField(name="kind", label="Kind", values=[FILE, FOLDER])]
