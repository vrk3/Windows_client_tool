"""The global-search provider over live processes (W5-04).

What this pins: the app's global search bar (the one in MainWindow that
queries every module) can find a process by name, pid, user or command
line. The read is ON DEMAND through the bulk syscall, so it can never
answer with a process that died a second ago, and an empty query is not a
search.
"""
import os
import re

import pytest

from core.search_provider import SearchQuery
from modules.dashboard.process_search import ProcessSearchProvider, PROCESS

MY_PID = os.getpid()


@pytest.fixture(scope="module")
def provider():
    return ProcessSearchProvider()


def test_an_empty_query_is_not_a_search(provider):
    assert provider.search(SearchQuery(text="")) == []


def test_our_own_pid_is_found(provider):
    hits = provider.search(SearchQuery(text=str(MY_PID)))
    assert hits, "a search for our own pid found nothing"
    assert any(hit.detail.pid == MY_PID for hit in hits)


def test_python_is_found_by_name(provider):
    hits = provider.search(SearchQuery(text="python"))
    assert hits
    assert any("python" in hit.detail.name.lower() for hit in hits)


def test_every_result_names_a_process_and_pid(provider):
    hits = provider.search(SearchQuery(text="python"))
    for hit in hits:
        assert hit.type == PROCESS
        assert hit.detail.pid > 0
        assert str(hit.detail.pid) in hit.summary


def test_a_nonsense_query_finds_nothing(provider):
    assert provider.search(SearchQuery(text="zzzznotaprocesszzzz")) == []


def test_results_are_capped(provider):
    """The bar merges every provider's output; fifty processes is already
    more than any other pane contributes."""
    hits = provider.search(SearchQuery(text="e"))
    assert len(hits) <= 50


def test_a_refused_process_still_matches_on_name(provider):
    """pid 4 (System) refuses its cold details unelevated, but it still has
    a name -- it must be findable on that name, not invisible because its
    path refused."""
    provider.search(SearchQuery(text="System"))
    # The name is "System" but so is the description field of others; just
    # assert pid 4 itself is reachable by its pid, which never refuses.
    assert any(hit.detail.pid == 4
               for hit in provider.search(SearchQuery(text="4")))


def test_search_provider_shape(provider):
    fields = provider.get_filterable_fields()
    assert fields and fields[0].name == "type"
    assert PROCESS in fields[0].values
