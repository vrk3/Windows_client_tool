"""Spec 9: "A SearchProvider exposes scanned paths to the global search bar,
consistent with the other modules."

TreeSize was the one module in the app that shipped without one, so the app's
own search bar could reach crash dumps, CBS entries and installed packages but
not the half-million paths TreeSize had already indexed in memory.
"""
from datetime import datetime

import pytest

from core.search_provider import SearchQuery
from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
from modules.treesize.store.rollup import rollup
from modules.treesize.search_provider import TreeSizeSearchProvider


def _scan():
    s = NodeStore()
    root = s.add(-1, "C:\\proj", attrs=DIR)
    docs = s.add(root, "docs", attrs=DIR)
    s.add(docs, "invoice-2026.pdf", size=5_000_000, mtime=133_000_000_000_000_000)
    s.add(docs, "notes.txt", size=1200)
    s.add(root, "invoice-backup.zip", size=90_000_000)
    s.add(root, "gone.tmp", size=800, attrs=EXCLUDED)
    s.build_child_lists()
    rollup(s)
    return s, root


@pytest.fixture
def provider():
    p = TreeSizeSearchProvider()
    store, root = _scan()
    p.set_scan(store, root, "C:\\proj")
    return p


def test_it_declares_the_module_name_the_engine_filters_on():
    assert TreeSizeSearchProvider.module_name == "TreeSize"


def test_with_no_scan_it_returns_nothing_rather_than_raising():
    """The provider is registered at startup; a scan may never happen."""
    assert TreeSizeSearchProvider().search(SearchQuery(text="anything")) == []


def test_it_finds_scanned_paths_by_substring(provider):
    hits = provider.search(SearchQuery(text="invoice"))
    names = {h.summary.split()[0] for h in hits}
    assert "invoice-2026.pdf" in names
    assert "invoice-backup.zip" in names
    assert "notes.txt" not in names


def test_the_detail_carries_the_full_path(provider):
    hit = next(h for h in provider.search(SearchQuery(text="invoice-2026")))
    assert hit.detail == "C:\\proj\\docs\\invoice-2026.pdf"


def test_the_summary_carries_the_size(provider):
    """The whole reason to search a disk-space tool is to find the big one."""
    hit = next(h for h in provider.search(SearchQuery(text="backup")))
    assert "85.8 MB" in hit.summary


def test_biggest_first(provider):
    """Sorted by size, not alphabetically -- searching a space tool means
    "find the big thing called X"."""
    hits = provider.search(SearchQuery(text="invoice"))
    assert hits[0].detail.endswith("invoice-backup.zip")


def test_relevance_falls_off_down_the_list(provider):
    hits = provider.search(SearchQuery(text="invoice"))
    assert hits[0].relevance >= hits[-1].relevance


def test_an_excluded_node_is_never_a_result(provider):
    assert provider.search(SearchQuery(text="gone")) == []


def test_an_empty_query_returns_nothing(provider):
    """The global bar asks every provider on every keystroke. Answering an
    empty query with half a million paths would be a denial of service on the
    result list, not a search."""
    assert provider.search(SearchQuery(text="")) == []


def test_regex_is_honoured_when_the_query_asks_for_it(provider):
    hits = provider.search(SearchQuery(text=r"invoice-\d+", regex_enabled=True))
    assert len(hits) == 1
    assert hits[0].detail.endswith("invoice-2026.pdf")


def test_a_broken_regex_degrades_to_a_substring_match(provider):
    """A bad pattern is a typo mid-typing, not a crash."""
    assert provider.search(SearchQuery(text="invoice[", regex_enabled=True)) == []
    assert provider.search(SearchQuery(text="invoice", regex_enabled=True))


def test_results_are_capped(provider):
    provider.MAX_RESULTS = 1
    assert len(provider.search(SearchQuery(text="invoice"))) == 1


def test_it_offers_a_filterable_kind_field(provider):
    fields = provider.get_filterable_fields()
    assert any(f.name == "kind" for f in fields)


def test_folders_can_be_filtered_in(provider):
    """Files only by default -- a folder is not what "find X" usually means."""
    assert not provider.search(SearchQuery(text="docs"))
    assert provider.search(SearchQuery(text="docs", types=["Folder"]))


def test_the_timestamp_is_the_files_own_mtime(provider):
    hit = next(h for h in provider.search(SearchQuery(text="invoice-2026")))
    assert isinstance(hit.timestamp, datetime)
    assert hit.timestamp.year == 2022


def test_clearing_the_scan_clears_the_results(provider):
    provider.set_scan(None, -1, "")
    assert provider.search(SearchQuery(text="invoice")) == []
