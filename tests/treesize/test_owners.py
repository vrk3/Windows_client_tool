"""Spec 5.8: the Users view is per-owner, so somebody has to read owners.

Nothing here touches a real ACL: the two Win32 steps -- path to SID, SID to
account name -- are injected, because what breaks is the caching, the
fallbacks and the counting, not the two API calls.
"""
from modules.treesize.scan.owners import OwnerResolver, resolve_sampled_owners
from modules.treesize.scan.walk_scanner import WalkScanner
from modules.treesize.store.node_store import NodeStore, DIR


class _FakeAcl:
    """path -> sid, and sid -> account name, with the calls counted."""

    def __init__(self, sids: dict, names: dict) -> None:
        self.sids, self.names = sids, names
        self.sid_calls: list[str] = []
        self.name_calls: list[str] = []

    def sid_of_path(self, path):
        self.sid_calls.append(path)
        if path not in self.sids:
            raise OSError("access denied")
        return self.sids[path], self.sids[path]

    def name_of_sid(self, sid):
        self.name_calls.append(sid)
        if sid not in self.names:
            raise OSError("no mapping")
        return self.names[sid]


def _resolver(acl):
    return OwnerResolver(sid_of_path=acl.sid_of_path,
                         name_of_sid=acl.name_of_sid)


def test_an_owner_resolves_to_an_account_name():
    acl = _FakeAcl({r"C:\a.txt": "S-1-5-21-7"}, {"S-1-5-21-7": r"HOME\ana"})
    assert _resolver(acl).for_path(r"C:\a.txt") == r"HOME\ana"


def test_a_sid_is_looked_up_once_however_many_files_carry_it():
    """One LookupAccountSid per distinct SID. Per FILE would put a domain
    round trip on the hot path of a half-million-node scan."""
    acl = _FakeAcl({r"C:\a": "S-1-5-21-7", r"C:\b": "S-1-5-21-7",
                    r"C:\c": "S-1-5-21-7"},
                   {"S-1-5-21-7": r"HOME\ana"})
    resolver = _resolver(acl)
    for path in (r"C:\a", r"C:\b", r"C:\c"):
        assert resolver.for_path(path) == r"HOME\ana"
    assert acl.name_calls == ["S-1-5-21-7"]
    assert len(acl.sid_calls) == 3, "the SID still has to be read per file"


def test_an_unmappable_sid_falls_back_to_the_sid_itself():
    """Orphaned SIDs are ordinary on a disk that outlived an account. The raw
    SID is still useful in the Users view; an empty string is not."""
    acl = _FakeAcl({r"C:\a": "S-1-5-21-999"}, {})
    assert _resolver(acl).for_path(r"C:\a") == "S-1-5-21-999"


def test_a_failed_lookup_is_cached_too():
    acl = _FakeAcl({r"C:\a": "S-1-5-21-999", r"C:\b": "S-1-5-21-999"}, {})
    resolver = _resolver(acl)
    resolver.for_path(r"C:\a")
    resolver.for_path(r"C:\b")
    assert acl.name_calls == ["S-1-5-21-999"], "a failure must not retry per file"


def test_an_unreadable_path_has_no_owner_rather_than_an_exception():
    acl = _FakeAcl({}, {})
    assert _resolver(acl).for_path(r"C:\locked") == ""


# ---- the walk engine ----------------------------------------------------

def test_the_walk_records_owners_when_asked(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), owner_resolver=_FixedResolver(r"HOME\ana"))
    scanner.scan(store)
    node = next(i for i in range(len(store)) if store.name(i) == "a.txt")
    assert store.owner(store.owner_id[node]) == r"HOME\ana"


def test_the_walk_leaves_owners_alone_by_default(tmp_path):
    """One security call per file is what makes owner collection a choice."""
    (tmp_path / "a.txt").write_bytes(b"x")
    store = NodeStore()
    WalkScanner(str(tmp_path)).scan(store)
    node = next(i for i in range(len(store)) if store.name(i) == "a.txt")
    assert store.owner_id[node] == -1


def test_the_scan_root_gets_an_owner_too(tmp_path):
    store = NodeStore()
    scanner = WalkScanner(str(tmp_path), owner_resolver=_FixedResolver(r"HOME\ana"))
    scanner.scan(store)
    assert store.owner(store.owner_id[scanner.root]) == r"HOME\ana"


def test_an_unreadable_owner_leaves_the_node_unattributed(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"x")
    store = NodeStore()
    WalkScanner(str(tmp_path), owner_resolver=_FixedResolver("")).scan(store)
    node = next(i for i in range(len(store)) if store.name(i) == "a.txt")
    assert store.owner_id[node] == -1, (
        "interning an empty name would give the Users view a nameless bucket")


class _FixedResolver:
    def __init__(self, name: str) -> None:
        self._name = name

    def for_path(self, _path: str) -> str:
        return self._name


# ---- the MFT path -------------------------------------------------------

def _mft_like_store():
    """What an MFT scan leaves behind: $SECURE placeholders, not names."""
    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    first = store.intern_owner("$SECURE:256")
    second = store.intern_owner("$SECURE:257")
    store.add(root, "a.txt", size=1, owner_id=first)
    store.add(root, "b.txt", size=1, owner_id=first)
    store.add(root, "c.txt", size=1, owner_id=second)
    store.build_child_lists()
    return store


def test_placeholder_owners_become_names_from_one_sample_each():
    """A whole-volume scan has a handful of distinct security ids and half a
    million files. Sampling one path per id costs a handful of calls; asking
    per file costs half a million."""
    store = _mft_like_store()
    acl = _FakeAcl({r"C:\a.txt": "S-1-5-21-7", r"C:\c.txt": "S-1-5-21-8"},
                   {"S-1-5-21-7": r"HOME\ana", "S-1-5-21-8": r"HOME\bo"})
    resolved = resolve_sampled_owners(store, _resolver(acl))
    assert resolved == 2
    assert store.owner(store.owner_id[1]) == r"HOME\ana"
    assert store.owner(store.owner_id[3]) == r"HOME\bo"
    assert len(acl.sid_calls) == 2, "one sample per distinct owner, not per file"


def test_a_sample_that_cannot_be_read_keeps_its_placeholder():
    """Better an honest $SECURE id than a name guessed from another file."""
    store = _mft_like_store()
    acl = _FakeAcl({}, {})
    assert resolve_sampled_owners(store, _resolver(acl)) == 0
    assert store.owner(store.owner_id[1]) == "$SECURE:256"


def test_already_named_owners_are_not_resampled():
    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    named = store.intern_owner(r"HOME\ana")
    store.add(root, "a.txt", size=1, owner_id=named)
    store.build_child_lists()
    acl = _FakeAcl({}, {})
    assert resolve_sampled_owners(store, _resolver(acl)) == 0
    assert acl.sid_calls == []


# ---- orchestration ------------------------------------------------------

def test_the_scanner_collects_owners_when_asked(tmp_path):
    from modules.treesize.scan.scanner import Scanner

    (tmp_path / "a.txt").write_bytes(b"x")
    result = Scanner(str(tmp_path), collect_owners=True).scan()
    node = next(i for i in range(len(result.store))
                if result.store.name(i) == "a.txt")
    assert result.store.owner(result.store.owner_id[node]) != "", (
        "an owner on a file this process just created should be readable")


def test_the_scanner_leaves_owners_alone_by_default(tmp_path):
    from modules.treesize.scan.scanner import Scanner

    (tmp_path / "a.txt").write_bytes(b"x")
    result = Scanner(str(tmp_path)).scan()
    node = next(i for i in range(len(result.store))
                if result.store.name(i) == "a.txt")
    assert result.store.owner_id[node] == -1


# ---- the pane -----------------------------------------------------------

def test_the_scan_options_actually_reach_the_scan(qapp):
    """`charge_all_hardlinks` had been an Options checkbox since phase 2 and
    had never once reached a Scanner: start_scan built the worker with the
    filters alone. An option nobody passes is a lie told in a dialog."""
    from modules.treesize.ui.shell import TreeSizeShell

    shell = TreeSizeShell()
    shell._settings["charge_all_hardlinks"] = True
    shell._settings["collect_owners"] = True
    worker = shell.make_scan_worker("C:\\", None)
    assert worker.scanner.charge_all_hardlinks
    assert worker.scanner.collect_owners


def test_owner_collection_is_off_unless_it_is_switched_on(qapp):
    from modules.treesize.ui.options_dialog import DEFAULTS
    from modules.treesize.ui.shell import TreeSizeShell

    assert DEFAULTS["collect_owners"] is False
    shell = TreeSizeShell()
    assert not shell.make_scan_worker("C:\\", None).scanner.collect_owners


def test_the_options_dialog_carries_the_owner_toggle(qapp):
    from modules.treesize.ui.options_dialog import DEFAULTS, OptionsDialog

    settings = dict(DEFAULTS)
    dialog = OptionsDialog(settings)
    dialog.collect_owners.setChecked(True)
    assert dialog.values()["collect_owners"] is True


def test_the_users_view_explains_an_unattributed_scan(qapp):
    """One "(unknown)" bucket holding the whole volume is not an answer. The
    view has to say that owners were never read and where to turn that on."""
    from modules.treesize.store.aggregates import AggregateCache
    from modules.treesize.ui.views.tables import UsersView

    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    store.add(root, "a.txt", size=10)
    store.build_child_lists()
    from modules.treesize.store.rollup import rollup
    rollup(store)

    view = UsersView()
    view.show_subtree(store, root, AggregateCache())
    assert view.topLevelItemCount() == 1
    assert "Options" in view.topLevelItem(0).text(0)


def test_the_users_view_shows_owners_it_was_given(qapp):
    from modules.treesize.store.aggregates import AggregateCache
    from modules.treesize.store.rollup import rollup
    from modules.treesize.ui.views.tables import UsersView

    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    ana = store.intern_owner(r"HOME\ana")
    store.add(root, "a.txt", size=10, owner_id=ana)
    store.build_child_lists()
    rollup(store)

    view = UsersView()
    view.show_subtree(store, root, AggregateCache())
    assert [view.topLevelItem(i).text(0)
            for i in range(view.topLevelItemCount())] == [r"HOME\ana"]
