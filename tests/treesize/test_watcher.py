"""Spec 3.5: live updates.

The Windows notification plumbing is not tested here — the change source is
injected instead, so the coalescing and the delta arithmetic, which is where
the bugs actually live, are testable without a filesystem or a volume handle.
"""
import os
import time

import pytest

from modules.treesize.scan.watcher import (
    Change, Watcher, apply_change, find_node,
)
from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup


def _tree(tmp_path):
    """A store mirroring a real directory, so re-stat has something to read."""
    sub = tmp_path / "sub"
    sub.mkdir()
    (tmp_path / "top.bin").write_bytes(b"x" * 100)
    (sub / "inner.bin").write_bytes(b"y" * 200)

    store = NodeStore()
    root = store.add(-1, str(tmp_path), attrs=DIR)
    sub_node = store.add(root, "sub", attrs=DIR)
    store.add(sub_node, "inner.bin", size=200)
    store.add(root, "top.bin", size=100)
    store.build_child_lists()
    rollup(store)
    return store, root


# ---- locating a node by path -------------------------------------------

def test_find_node_walks_down_from_the_root(tmp_path):
    store, root = _tree(tmp_path)
    node = find_node(store, root, str(tmp_path / "sub" / "inner.bin"))
    assert store.name(node) == "inner.bin"


def test_find_node_is_case_insensitive(tmp_path):
    store, root = _tree(tmp_path)
    node = find_node(store, root, str(tmp_path / "SUB" / "INNER.BIN"))
    assert store.name(node) == "inner.bin"


def test_find_node_returns_the_root_for_the_root(tmp_path):
    store, root = _tree(tmp_path)
    assert find_node(store, root, str(tmp_path)) == root


def test_find_node_rejects_a_path_outside_the_scan(tmp_path):
    store, root = _tree(tmp_path)
    assert find_node(store, root, "C:\\somewhere\\else.bin") == -1


def test_find_node_returns_minus_one_for_something_unscanned(tmp_path):
    store, root = _tree(tmp_path)
    assert find_node(store, root, str(tmp_path / "never-scanned.bin")) == -1


# ---- applying a delta ---------------------------------------------------

def test_growth_propagates_up_the_parent_chain(tmp_path):
    store, root = _tree(tmp_path)
    before = store.size[root]
    (tmp_path / "sub" / "inner.bin").write_bytes(b"y" * 500)

    delta = apply_change(store, root, str(tmp_path / "sub" / "inner.bin"))
    assert delta == 300
    node = find_node(store, root, str(tmp_path / "sub" / "inner.bin"))
    assert store.size[node] == 500
    assert store.size[find_node(store, root, str(tmp_path / "sub"))] == 500
    assert store.size[root] == before + 300


def test_shrinking_propagates_too(tmp_path):
    store, root = _tree(tmp_path)
    before = store.size[root]
    (tmp_path / "top.bin").write_bytes(b"x" * 40)
    assert apply_change(store, root, str(tmp_path / "top.bin")) == -60
    assert store.size[root] == before - 60


def test_a_deleted_file_removes_exactly_what_the_store_held(tmp_path):
    """Gone between notification and stat: treat as zero, so the delta takes
    away precisely what was counted and no more."""
    store, root = _tree(tmp_path)
    before = store.size[root]
    os.remove(tmp_path / "top.bin")
    assert apply_change(store, root, str(tmp_path / "top.bin")) == -100
    assert store.size[root] == before - 100


def test_an_unchanged_file_applies_nothing(tmp_path):
    store, root = _tree(tmp_path)
    before = list(store.size)
    assert apply_change(store, root, str(tmp_path / "top.bin")) == 0
    assert list(store.size) == before


def test_an_unknown_path_is_ignored(tmp_path):
    store, root = _tree(tmp_path)
    before = list(store.size)
    assert apply_change(store, root, str(tmp_path / "ghost.bin")) == 0
    assert list(store.size) == before


def test_a_parent_cycle_cannot_hang_the_walk(tmp_path):
    """The store is trusted here, but a corrupt chain must cost a wrong number
    rather than a frozen UI thread."""
    store, root = _tree(tmp_path)
    node = find_node(store, root, str(tmp_path / "top.bin"))
    store.parent[root] = node                      # root -> top.bin -> root
    (tmp_path / "top.bin").write_bytes(b"x" * 300)
    apply_change(store, root, str(tmp_path / "top.bin"))   # must terminate


# ---- coalescing ---------------------------------------------------------

def _run_watcher(events, clock_values, coalesce=0.5):
    seen = []
    ticks = iter(clock_values)
    watcher = Watcher("C:\\ignored", seen.append,
                      source=lambda: iter(events),
                      coalesce=coalesce,
                      clock=lambda: next(ticks, 999.0))
    watcher._run()
    return seen


def test_the_last_action_for_a_path_wins():
    """A file written in ten chunks is one change; reporting ten would defeat
    the point of coalescing."""
    events = [("a.bin", 1), ("a.bin", 3), ("a.bin", 3)]
    batches = _run_watcher(events, [0.0, 0.0, 0.0, 0.0])
    assert len(batches) == 1
    assert batches[0] == [Change("a.bin", 3)]


def test_changes_are_batched_until_the_window_elapses():
    events = [("a.bin", 1), ("b.bin", 1), ("c.bin", 1)]
    # Clock stays put, so nothing flushes until the final drain.
    batches = _run_watcher(events, [0.0] * 8)
    assert len(batches) == 1
    assert {c.path for c in batches[0]} == {"a.bin", "b.bin", "c.bin"}


def test_a_batch_is_emitted_once_the_window_passes():
    """The window is checked AFTER each event is buffered, so a clock that has
    already passed it flushes that event with whatever preceded it. An
    always-advancing clock therefore yields one batch per event."""
    events = [("a.bin", 1), ("b.bin", 1), ("c.bin", 1)]
    batches = _run_watcher(events, [i * 9.0 for i in range(10)])
    assert len(batches) == 3
    assert [b[0].path for b in batches] == ["a.bin", "b.bin", "c.bin"]


def test_pending_changes_are_flushed_when_the_source_ends():
    """Whatever is buffered when watching stops must still be reported."""
    batches = _run_watcher([("a.bin", 1)], [0.0] * 4)
    assert batches and batches[0][0].path == "a.bin"


def test_a_failing_source_is_recorded_not_raised():
    def broken():
        raise OSError("handle went away")
        yield

    seen = []
    watcher = Watcher("C:\\x", seen.append, source=broken)
    watcher._run()
    assert watcher.error and "handle went away" in watcher.error


def test_a_failing_callback_does_not_kill_the_watcher():
    def explode(_changes):
        raise ValueError("consumer bug")

    watcher = Watcher("C:\\x", explode, source=lambda: iter([("a", 1)]))
    watcher._run()                                  # must not raise
    assert watcher.error is None


def test_start_and_stop_are_idempotent():
    watcher = Watcher("C:\\x", lambda _c: None,
                      source=lambda: iter(()))
    watcher.start()
    watcher.start()                                 # second start is a no-op
    watcher.stop()
    watcher.stop()
    assert not watcher.running
