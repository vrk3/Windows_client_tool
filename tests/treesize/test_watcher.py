"""Spec 3.5: live updates.

The Windows notification plumbing is not tested here — the change source is
injected instead, so the coalescing and the delta arithmetic, which is where
the bugs actually live, are testable without a filesystem or a volume handle.
"""
import os
import struct
import threading
import time


from modules.treesize.scan.watcher import (
    FILE_ACTION_ADDED, FILE_ACTION_MODIFIED, FILE_ACTION_REMOVED,
    Change, Watcher, apply_change, find_node,
)
from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
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

    delta = apply_change(store, root, str(tmp_path / "sub" / "inner.bin")).delta
    assert delta == 300
    node = find_node(store, root, str(tmp_path / "sub" / "inner.bin"))
    assert store.size[node] == 500
    assert store.size[find_node(store, root, str(tmp_path / "sub"))] == 500
    assert store.size[root] == before + 300


def test_shrinking_propagates_too(tmp_path):
    store, root = _tree(tmp_path)
    before = store.size[root]
    (tmp_path / "top.bin").write_bytes(b"x" * 40)
    assert apply_change(store, root, str(tmp_path / "top.bin")).delta == -60
    assert store.size[root] == before - 60


def test_a_deleted_file_removes_exactly_what_the_store_held(tmp_path):
    """Gone between notification and stat: treat as zero, so the delta takes
    away precisely what was counted and no more."""
    store, root = _tree(tmp_path)
    before = store.size[root]
    os.remove(tmp_path / "top.bin")
    assert apply_change(store, root, str(tmp_path / "top.bin")).delta == -100
    assert store.size[root] == before - 100


def test_an_unchanged_file_applies_nothing(tmp_path):
    store, root = _tree(tmp_path)
    before = list(store.size)
    assert apply_change(store, root, str(tmp_path / "top.bin")).delta == 0
    assert list(store.size) == before


def test_an_unknown_path_is_ignored(tmp_path):
    store, root = _tree(tmp_path)
    before = list(store.size)
    assert apply_change(store, root, str(tmp_path / "ghost.bin")).delta == 0
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


# ---- the timer flush ----------------------------------------------------

def test_a_quiet_burst_is_still_delivered():
    """THE bug the fake sources hid: ReadDirectoryChangesW BLOCKS.

    Every coalescing test above uses a finite source, so the generator ends
    and the `finally` drain reports whatever was buffered. The real source
    never ends -- it sits in ReadDirectoryChangesW waiting for the next
    change. With the flush check running only on receipt of an event, a file
    edited once and then left alone was buffered and never reported, which is
    the single most ordinary way anyone uses "watch this folder".
    """
    seen = []
    delivered = threading.Event()
    release = threading.Event()

    def source():
        yield ("a.bin", FILE_ACTION_MODIFIED)
        release.wait(10.0)              # what the real source does: block

    def on_changes(batch):
        seen.append(batch)
        delivered.set()

    watcher = Watcher("C:\\x", on_changes, source=source, coalesce=0.05)
    watcher.start()
    try:
        assert delivered.wait(3.0), "a pending change was never flushed"
    finally:
        release.set()
        watcher.stop()
    assert seen[0][0].path == "a.bin"


def test_the_timer_does_not_emit_empty_batches():
    """A quiet watcher must stay quiet, not wake the UI twice a second."""
    seen = []
    release = threading.Event()

    def source():
        release.wait(10.0)
        return
        yield

    watcher = Watcher("C:\\x", seen.append, source=source, coalesce=0.02)
    watcher.start()
    time.sleep(0.2)                     # several windows with nothing pending
    release.set()
    watcher.stop()
    assert seen == []


# ---- allocated space and counts ----------------------------------------

def test_allocated_space_follows_the_size_delta(tmp_path):
    """Spec 5.5's Allocated-space mode reads `alloc`. A live update that moved
    only `size` left that whole mode frozen while the tree grew."""
    store, root = _tree(tmp_path)
    path = str(tmp_path / "top.bin")
    store.alloc[find_node(store, root, path)] = 4096
    rollup(store)
    before = store.alloc[root]

    with open(path, "wb") as handle:
        handle.write(b"x" * 9000)       # 3 clusters at 4096
    apply_change(store, root, path, bytes_per_cluster=4096)

    assert store.alloc[find_node(store, root, path)] == 12288
    assert store.alloc[root] == before + (12288 - 4096)


def test_allocated_space_is_left_alone_when_the_cluster_size_is_unknown(tmp_path):
    """A remote scan has no cluster geometry. Guessing one would report a
    number the volume never had; leaving `alloc` put is the honest option."""
    store, root = _tree(tmp_path)
    path = str(tmp_path / "top.bin")
    node = find_node(store, root, path)
    store.alloc[node] = 4096
    rollup(store)
    before = store.alloc[root]

    with open(path, "wb") as handle:
        handle.write(b"x" * 9000)
    apply_change(store, root, path)     # no bytes_per_cluster

    assert store.alloc[node] == 4096
    assert store.alloc[root] == before


def test_a_new_file_is_inserted_and_charged_to_its_parents(tmp_path):
    """A file copied into a watched folder must appear, with its bytes. Left
    unhandled it was invisible: find_node missed it and the delta was zero."""
    store, root = _tree(tmp_path)
    new = tmp_path / "sub" / "fresh.bin"
    new.write_bytes(b"z" * 500)
    files_before = store.file_count[root]
    size_before = store.size[root]

    apply_change(store, root, str(new), bytes_per_cluster=4096)

    node = find_node(store, root, str(new))
    assert node > 0, "the new file was never inserted"
    assert store.size[node] == 500
    assert store.alloc[node] == 4096
    assert store.size[root] == size_before + 500
    assert store.file_count[root] == files_before + 1


def test_a_new_file_is_charged_exactly_once(tmp_path):
    """The trap in charging an unknown path straight to its parent: the file
    is still not in the store, so the next notification charges it again."""
    store, root = _tree(tmp_path)
    new = tmp_path / "sub" / "fresh.bin"
    new.write_bytes(b"z" * 500)
    size_before = store.size[root]

    apply_change(store, root, str(new))
    apply_change(store, root, str(new))
    apply_change(store, root, str(new))

    assert store.size[root] == size_before + 500


def test_a_new_directory_counts_as_a_folder(tmp_path):
    store, root = _tree(tmp_path)
    (tmp_path / "made").mkdir()
    folders_before = store.folder_count[root]

    apply_change(store, root, str(tmp_path / "made"))

    node = find_node(store, root, str(tmp_path / "made"))
    assert node > 0 and store.attrs[node] & DIR
    assert store.folder_count[root] == folders_before + 1


def test_a_file_created_outside_the_scan_is_not_inserted(tmp_path):
    """No parent in the store means no place to hang it -- and inventing one
    would graft a stranger's bytes onto the scan."""
    store, root = _tree(tmp_path)
    outside = tmp_path.parent / "elsewhere.bin"
    outside.write_bytes(b"q" * 10)
    size_before = store.size[root]

    assert apply_change(store, root, str(outside)).delta == 0
    assert store.size[root] == size_before


def test_a_deleted_file_stops_being_counted(tmp_path):
    """Zeroing the size left a ghost row in the tree and kept it in the file
    count, so "Number of files" only ever went up."""
    store, root = _tree(tmp_path)
    path = str(tmp_path / "top.bin")
    node = find_node(store, root, path)
    files_before = store.file_count[root]
    os.remove(path)

    apply_change(store, root, path)

    assert store.attrs[node] & EXCLUDED
    assert store.size[root] == 200
    assert store.file_count[root] == files_before - 1


def test_a_deleted_file_is_decounted_exactly_once(tmp_path):
    store, root = _tree(tmp_path)
    path = str(tmp_path / "top.bin")
    files_before = store.file_count[root]
    os.remove(path)

    apply_change(store, root, path)
    apply_change(store, root, path)

    assert store.file_count[root] == files_before - 1
    assert store.size[root] == 200


def test_apply_change_reports_whether_structure_moved(tmp_path):
    """The model caches child lists, so the shell has to know the difference
    between "a number changed" and "a row appeared"."""
    store, root = _tree(tmp_path)
    grew = tmp_path / "sub" / "fresh.bin"
    grew.write_bytes(b"z" * 5)

    assert apply_change(store, root, str(grew)).structural is True
    with open(tmp_path / "top.bin", "wb") as handle:
        handle.write(b"x" * 300)
    assert apply_change(store, root, str(tmp_path / "top.bin")).structural is False


# ---- decoding FILE_NOTIFY_INFORMATION -----------------------------------

def _record(action, name, next_entry=None):
    encoded = name.encode("utf-16-le")
    body = struct.pack("<III", 0, action, len(encoded)) + encoded
    # Entries are 4-byte aligned and NextEntryOffset counts from the start of
    # THIS record, not from the end of it.
    pad = (-len(body)) % 4
    body += b"\x00" * pad
    if next_entry is None:
        return body
    return struct.pack("<III", len(body), action, len(encoded)) + encoded + b"\x00" * pad


def test_parse_decodes_action_and_name():
    """The whole notification payload was being read through a ctypes buffer
    that Python was free to collect before it was read, so every record came
    back as action 0 with an empty name -- pointing at the watched root, which
    apply_change then correctly decided had not changed. The feature reported
    nothing at all and looked, from the logs, like a quiet filesystem."""
    watcher = Watcher("C:\\root", lambda _c: None, source=lambda: iter(()))
    out = list(watcher._parse(_record(FILE_ACTION_MODIFIED, "a.bin")))
    assert out == [("C:\\root\\a.bin", FILE_ACTION_MODIFIED)]


def test_parse_walks_a_chain_of_records():
    watcher = Watcher("C:\\root", lambda _c: None, source=lambda: iter(()))
    raw = (_record(FILE_ACTION_ADDED, "one.bin", next_entry=True)
           + _record(FILE_ACTION_REMOVED, "two.bin"))
    out = list(watcher._parse(raw))
    assert out == [("C:\\root\\one.bin", FILE_ACTION_ADDED),
                   ("C:\\root\\two.bin", FILE_ACTION_REMOVED)]


def test_parse_keeps_a_subdirectory_path():
    """Names arrive relative to the watched root, separators included."""
    watcher = Watcher("C:\\root", lambda _c: None, source=lambda: iter(()))
    out = list(watcher._parse(_record(FILE_ACTION_MODIFIED, "sub\\deep.bin")))
    assert out == [("C:\\root\\sub\\deep.bin", FILE_ACTION_MODIFIED)]


def test_parse_stops_on_a_truncated_record():
    """The buffer is whatever the kernel filled; a short tail must not raise."""
    watcher = Watcher("C:\\root", lambda _c: None, source=lambda: iter(()))
    raw = _record(FILE_ACTION_MODIFIED, "a.bin")
    assert list(watcher._parse(raw[:9])) == []
    truncated_name = raw[:len(raw) - 4]
    assert len(list(watcher._parse(truncated_name))) <= 1
