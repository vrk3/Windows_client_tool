"""Spec 8.1 and 8.2: file search and the duplicate finder."""

from modules.treesize.store import duplicates, search
from modules.treesize.store.node_store import (
    NodeStore, DIR, EXCLUDED, HARDLINK_DUP, HIDDEN,
)
from modules.treesize.store.rollup import rollup
from modules.treesize.store.search import Query

DAY = 24 * 60 * 60 * 10_000_000
NOW = 140_000_000_000_000_000


def _store():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    alice = s.intern_owner("alice")
    bob = s.intern_owner("bob")
    docs = s.add(root, "Docs", attrs=DIR)
    s.add(docs, "invoice-2024.pdf", size=5000, mtime=NOW - 10 * DAY, owner_id=alice)
    s.add(docs, "invoice-2023.pdf", size=3000, mtime=NOW - 400 * DAY, owner_id=alice)
    s.add(docs, "notes.txt", size=100, mtime=NOW - 2 * DAY, owner_id=bob)
    s.add(root, "big.iso", size=900_000, mtime=NOW - 30 * DAY, owner_id=bob)
    s.add(root, "secret.dat", size=700, mtime=NOW, owner_id=alice, attrs=HIDDEN)
    s.add(root, "dropped.tmp", size=999_999, attrs=EXCLUDED)
    s.add(root, "alias.iso", size=0, attrs=HARDLINK_DUP)
    s.build_child_lists()
    rollup(s)
    return s, root


# ---- search -------------------------------------------------------------

def test_an_empty_query_returns_every_file():
    s, root = _store()
    names = {h.name for h in search.search(s, root, Query(), now=NOW)}
    assert names == {"invoice-2024.pdf", "invoice-2023.pdf", "notes.txt",
                     "big.iso", "secret.dat"}


def test_a_bare_word_matches_as_contains():
    """Typing 'invoice' into a search box means 'contains', not 'equals'."""
    s, root = _store()
    hits = search.search(s, root, Query(pattern="invoice"), now=NOW)
    assert {h.name for h in hits} == {"invoice-2024.pdf", "invoice-2023.pdf"}


def test_wildcards_are_honoured_when_present():
    s, root = _store()
    hits = search.search(s, root, Query(pattern="*.iso"), now=NOW)
    assert [h.name for h in hits] == ["big.iso"]


def test_results_come_back_largest_first():
    """The reason to search a disk-space tool is 'find the big thing called X'."""
    s, root = _store()
    hits = search.search(s, root, Query(pattern="*.pdf"), now=NOW)
    assert [h.size for h in hits] == [5000, 3000]


def test_regex_search():
    s, root = _store()
    hits = search.search(s, root, Query(pattern=r"invoice-20(23|24)", regex=True),
                         now=NOW)
    assert len(hits) == 2


def test_a_broken_regex_falls_back_instead_of_raising():
    """A bad pattern is a typo, not a crash."""
    s, root = _store()
    hits = search.search(s, root, Query(pattern="invoice(", regex=True), now=NOW)
    assert hits == [] or all("invoice(" in h.name for h in hits)


def test_size_range():
    s, root = _store()
    hits = search.search(s, root, Query(min_size=1000, max_size=6000), now=NOW)
    assert {h.name for h in hits} == {"invoice-2024.pdf", "invoice-2023.pdf"}


def test_age_filters():
    s, root = _store()
    recent = search.search(s, root, Query(newer_than_days=5), now=NOW)
    assert {h.name for h in recent} == {"notes.txt", "secret.dat"}
    ancient = search.search(s, root, Query(older_than_days=365), now=NOW)
    assert {h.name for h in ancient} == {"invoice-2023.pdf"}


def test_owner_filter():
    s, root = _store()
    hits = search.search(s, root, Query(owner="bob"), now=NOW)
    assert {h.name for h in hits} == {"notes.txt", "big.iso"}


def test_hidden_files_can_be_left_out():
    s, root = _store()
    hits = search.search(s, root, Query(include_hidden=False), now=NOW)
    assert "secret.dat" not in {h.name for h in hits}


def test_folders_are_off_by_default_and_can_be_included():
    s, root = _store()
    assert "Docs" not in {h.name for h in search.search(s, root, Query(), now=NOW)}
    with_folders = search.search(
        s, root, Query(include_folders=True, include_files=False), now=NOW)
    assert {h.name for h in with_folders} == {"Docs"}


def test_excluded_and_hardlink_nodes_never_appear():
    s, root = _store()
    names = {h.name for h in search.search(s, root, Query(), now=NOW)}
    assert "dropped.tmp" not in names
    assert "alias.iso" not in names


def test_the_limit_is_respected():
    s, root = _store()
    assert len(search.search(s, root, Query(limit=2), now=NOW)) == 2


def test_searching_an_empty_store_is_safe():
    assert search.search(NodeStore(), -1, Query()) == []


# ---- duplicates ---------------------------------------------------------

def _dup_store(tmp_path):
    """Three identical files, one same-size-but-different, one unique."""
    same = b"A" * 2048
    other = b"B" * 2048
    (tmp_path / "one.bin").write_bytes(same)
    (tmp_path / "two.bin").write_bytes(same)
    (tmp_path / "three.bin").write_bytes(same)
    (tmp_path / "decoy.bin").write_bytes(other)      # same size, different bytes
    (tmp_path / "unique.bin").write_bytes(b"C" * 99)

    s = NodeStore()
    root = s.add(-1, str(tmp_path), attrs=DIR)
    for name, size in (("one.bin", 2048), ("two.bin", 2048), ("three.bin", 2048),
                       ("decoy.bin", 2048), ("unique.bin", 99)):
        s.add(root, name, size=size)
    s.build_child_lists()
    rollup(s)
    return s, root


def test_only_shared_sizes_are_candidates(tmp_path):
    """A file is never hashed unless another shares its exact size."""
    s, root = _dup_store(tmp_path)
    groups = duplicates.candidates_by_size(s, root)
    assert set(groups) == {2048}
    assert len(groups[2048]) == 4


def test_identical_files_are_grouped_and_the_decoy_is_not(tmp_path):
    s, root = _dup_store(tmp_path)
    found = duplicates.find_duplicates(s, root)
    assert len(found) == 1
    assert found[0].count == 3
    assert {p.rsplit("\\", 1)[-1] for p in found[0].paths} == {
        "one.bin", "two.bin", "three.bin"}


def test_wasted_space_counts_all_but_one_copy(tmp_path):
    s, root = _dup_store(tmp_path)
    group = duplicates.find_duplicates(s, root)[0]
    assert group.wasted == 2048 * 2


def test_nothing_is_hashed_when_no_size_is_shared(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    (tmp_path / "b.bin").write_bytes(b"y" * 20)
    s = NodeStore()
    root = s.add(-1, str(tmp_path), attrs=DIR)
    s.add(root, "a.bin", size=10)
    s.add(root, "b.bin", size=20)
    s.build_child_lists()
    rollup(s)

    hashed = []

    def spy(path, limit=None):
        hashed.append(path)
        return "x"

    assert duplicates.find_duplicates(s, root, hasher=spy) == []
    assert hashed == [], "no shared size means no I/O at all"


def test_hardlink_aliases_are_not_offered_as_duplicates(tmp_path):
    """They already share their bytes; offering them would promise space that
    cannot be freed."""
    (tmp_path / "real.bin").write_bytes(b"x" * 2048)
    s = NodeStore()
    root = s.add(-1, str(tmp_path), attrs=DIR)
    s.add(root, "real.bin", size=2048)
    s.add(root, "alias.bin", size=2048, attrs=HARDLINK_DUP)
    s.build_child_lists()
    rollup(s)
    assert duplicates.candidates_by_size(s, root) == {}


def test_an_unreadable_file_is_skipped_not_guessed(tmp_path):
    s, root = _dup_store(tmp_path)

    def refusing(path, limit=None):
        if path.endswith("two.bin"):
            return None
        return duplicates._hash_file(path, limit)

    found = duplicates.find_duplicates(s, root, hasher=refusing)
    assert found[0].count == 2
    assert not any(p.endswith("two.bin") for p in found[0].paths)


def test_cancelling_stops_and_returns_what_was_found(tmp_path):
    s, root = _dup_store(tmp_path)
    found = duplicates.find_duplicates(s, root, should_cancel=lambda: True)
    assert found == []


def test_progress_is_reported(tmp_path):
    s, root = _dup_store(tmp_path)
    seen = []
    duplicates.find_duplicates(s, root, on_progress=seen.append)
    assert seen and max(seen) <= 100


def test_keep_one_keeps_the_shortest_path():
    group = duplicates.DuplicateGroup(
        "d", 10, ("C:\\a.bin", "C:\\backup\\old\\a.bin", "C:\\copies\\a.bin"))
    removals = duplicates.keep_one(group)
    assert "C:\\a.bin" not in removals
    assert len(removals) == 2
