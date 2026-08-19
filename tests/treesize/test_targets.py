"""Spec 6: scan targets.

No network, no server. Clients are injected, so what gets tested is the part
that actually breaks: tree building, timestamps, error handling and
cancellation.
"""
import stat

import pytest

from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup
from modules.treesize.targets import base, remote
from modules.treesize.targets.base import (
    Credentials, RemoteEnumerator, ScanTarget, TargetError,
)
from modules.treesize.targets.remote import (
    SshTarget, WebDavTarget, unix_to_filetime,
)


# ---- the interface ------------------------------------------------------

def test_targets_register_themselves():
    ids = {cls.id for cls, _ok, _why in base.available_targets()}
    assert {"ssh", "webdav"} <= ids


def test_availability_explains_a_missing_package():
    for cls in (SshTarget, WebDavTarget):
        ok, why = cls.is_available()
        assert ok or "pip install" in why


def test_unix_timestamps_become_filetime():
    # 2001-09-09T01:46:40Z, a round Unix billion.
    assert unix_to_filetime(1_000_000_000) == 126_444_736_000_000_000
    assert unix_to_filetime(0) == 0
    assert unix_to_filetime(-5) == 0


def test_open_stream_is_refused_rather_than_silently_empty():
    target = WebDavTarget(Credentials(host="http://x"))
    with pytest.raises(TargetError):
        target.open_stream("/whatever")


# ---- the shared walk ----------------------------------------------------

class _FakeWalker(RemoteEnumerator):
    def __init__(self, tree, fail=()):
        super().__init__(target=None)
        self._tree = tree
        self._fail = set(fail)

    def list_dir(self, path):
        if path in self._fail:
            raise OSError("permission denied")
        return self._tree.get(path, [])


TREE = {
    "/": [("docs", 0, True, 10), ("big.iso", 5000, False, 20)],
    "/docs": [("a.txt", 100, False, 30), ("sub", 0, True, 40)],
    "/docs/sub": [("deep.bin", 700, False, 50)],
}


def _walk(tree, fail=()):
    store = NodeStore()
    root = store.add(-1, "/", attrs=DIR)
    walker = _FakeWalker(tree, fail)
    walker.walk(store, root, "/")
    rollup(store)
    return store, root, walker


def test_the_walk_builds_the_whole_tree():
    store, root, _ = _walk(TREE)
    names = {store.name(i) for i in range(len(store))}
    assert {"docs", "big.iso", "a.txt", "sub", "deep.bin"} <= names


def test_sizes_roll_up_through_remote_folders():
    store, root, _ = _walk(TREE)
    assert store.size[root] == 5800


def test_allocated_equals_size_because_there_is_no_cluster_geometry():
    """Rounding up to a cluster the remote end never mentioned would be
    inventing data."""
    store, root, _ = _walk(TREE)
    node = next(i for i in range(len(store)) if store.name(i) == "big.iso")
    assert store.alloc[node] == store.size[node] == 5000


def test_folders_carry_no_size_of_their_own():
    store, root, _ = _walk(TREE)
    docs = next(i for i in range(len(store)) if store.name(i) == "docs")
    assert store.file_count[docs] == 2


def test_one_unreadable_directory_does_not_end_the_scan():
    store, root, walker = _walk(TREE, fail={"/docs/sub"})
    names = {store.name(i) for i in range(len(store))}
    assert "a.txt" in names, "the rest of the tree must still be walked"
    assert "deep.bin" not in names
    assert walker.error_count == 1
    assert "permission denied" in walker.errors[0][1]


def test_the_error_list_is_capped_but_the_count_is_not():
    walker = _FakeWalker({})
    for i in range(150):
        walker.record_error(f"/p{i}", "nope")
    assert walker.error_count == 150
    assert len(walker.errors) == 100


def test_cancellation_stops_the_walk():
    store = NodeStore()
    root = store.add(-1, "/", attrs=DIR)
    walker = _FakeWalker(TREE)
    walker.walk(store, root, "/", should_cancel=lambda: True)
    assert len(store) == 1, "nothing below the root should be added"


def test_batches_are_emitted():
    store = NodeStore()
    root = store.add(-1, "/", attrs=DIR)
    seen = []
    _FakeWalker(TREE).walk(store, root, "/", on_batch=seen.append, batch_size=1)
    assert seen
    assert seen[-1][1] == len(store)


def test_paths_are_joined_posix_style_not_windows():
    assert base._join("/docs", "a.txt") == "/docs/a.txt"
    assert base._join("/", "x") == "/x"
    assert base._join("", "x") == "x"


# ---- SSH ----------------------------------------------------------------

class _Attr:
    def __init__(self, name, size, mode, mtime):
        self.filename = name
        self.st_size = size
        self.st_mode = mode
        self.st_mtime = mtime


class _FakeSftp:
    def __init__(self, listing):
        self._listing = listing
        self.calls = []

    def listdir_attr(self, path):
        self.calls.append(path)
        if path not in self._listing:
            raise OSError(f"no such directory: {path}")
        return self._listing[path]


def test_ssh_builds_a_tree_from_one_round_trip_per_directory():
    listing = {
        ".": [_Attr("data", 0, stat.S_IFDIR | 0o755, 100),
              _Attr("dump.sql", 4096, stat.S_IFREG | 0o644, 200)],
        "./data": [_Attr("rows.csv", 900, stat.S_IFREG | 0o644, 300)],
    }
    sftp = _FakeSftp(listing)
    target = SshTarget(Credentials(host="h", root="."), client=sftp)
    store = NodeStore()
    root = store.add(-1, "h:.", attrs=DIR)
    target.enumerate(store, root)
    rollup(store)

    assert store.size[root] == 4996
    assert sftp.calls == [".", "./data"], "one listing per directory, no stats"


def test_ssh_translates_timestamps():
    listing = {".": [_Attr("f.bin", 1, stat.S_IFREG | 0o644, 1_000_000_000)]}
    target = SshTarget(Credentials(root="."), client=_FakeSftp(listing))
    store = NodeStore()
    root = store.add(-1, "h", attrs=DIR)
    target.enumerate(store, root)
    node = next(i for i in range(len(store)) if store.name(i) == "f.bin")
    assert store.mtime[node] == unix_to_filetime(1_000_000_000)


def test_ssh_skips_dot_entries():
    listing = {".": [_Attr(".", 0, stat.S_IFDIR, 0),
                     _Attr("..", 0, stat.S_IFDIR, 0),
                     _Attr("real.bin", 5, stat.S_IFREG, 0)]}
    target = SshTarget(Credentials(root="."), client=_FakeSftp(listing))
    store = NodeStore()
    root = store.add(-1, "h", attrs=DIR)
    target.enumerate(store, root)
    assert len(store) == 2


def test_ssh_reports_file_ops_as_unsupported():
    assert not SshTarget().supports_file_ops()


# ---- WebDAV -------------------------------------------------------------

MULTISTATUS = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response>
    <d:href>/share/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/share/notes.txt</d:href>
    <d:propstat><d:prop>
      <d:resourcetype/>
      <d:getcontentlength>1234</d:getcontentlength>
      <d:getlastmodified>Wed, 09 Sep 2001 01:46:40 GMT</d:getlastmodified>
    </d:prop></d:propstat>
  </d:response>
  <d:response>
    <d:href>/share/photos/</d:href>
    <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
    </d:prop></d:propstat>
  </d:response>
</d:multistatus>"""

EMPTY = """<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/share/photos/</d:href>
  <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
  </d:prop></d:propstat></d:response></d:multistatus>"""


class _Response:
    def __init__(self, text, status=207):
        self.text = text
        self.status_code = status


class _FakeHttp:
    def __init__(self, pages):
        self._pages = pages
        self.requests = []

    def request(self, method, path, **kwargs):
        self.requests.append((method, path, kwargs.get("headers", {})))
        return self._pages.get(path, _Response("", 404))


def _webdav_store():
    client = _FakeHttp({"/share": _Response(MULTISTATUS),
                        "/share/photos": _Response(EMPTY)})
    target = WebDavTarget(Credentials(host="http://h", root="/share"),
                          client=client)
    store = NodeStore()
    root = store.add(-1, "/share", attrs=DIR)
    target.enumerate(store, root)
    rollup(store)
    return store, root, client


def test_webdav_parses_a_multistatus_response():
    store, root, _ = _webdav_store()
    names = {store.name(i) for i in range(len(store))}
    assert "notes.txt" in names
    assert "photos" in names
    assert store.size[root] == 1234


def test_webdav_does_not_add_a_collection_as_its_own_child():
    """A PROPFIND listing always includes the collection itself first; adding
    it would make every folder its own child."""
    store, root, _ = _webdav_store()
    names = [store.name(i) for i in range(len(store))]
    assert names == ["/share", "notes.txt", "photos"]
    assert store.name(root) not in [store.name(c) for c in store.children(root)]


def test_webdav_asks_for_depth_one():
    """Depth infinity is refused by most servers and streams whole trees on
    the rest."""
    _store, _root, client = _webdav_store()
    assert all(headers.get("Depth") == "1"
               for _method, _path, headers in client.requests)
    assert all(method == "PROPFIND" for method, _p, _h in client.requests)


def test_webdav_parses_http_dates():
    store, _root, _ = _webdav_store()
    node = next(i for i in range(len(store)) if store.name(i) == "notes.txt")
    assert store.mtime[node] == unix_to_filetime(1_000_000_000)


def test_webdav_survives_a_malformed_date():
    from modules.treesize.targets.remote import _http_date_to_filetime
    assert _http_date_to_filetime("not a date") == 0
    assert _http_date_to_filetime(None) == 0


def test_webdav_reports_a_bad_status_as_an_error_not_a_crash():
    client = _FakeHttp({})            # every path 404s
    target = WebDavTarget(Credentials(host="http://h", root="/share"),
                          client=client)
    store = NodeStore()
    root = store.add(-1, "/share", attrs=DIR)
    target.enumerate(store, root)
    assert target.errors and "404" in target.errors[0][1]


def test_webdav_percent_decodes_names():
    xml = MULTISTATUS.replace("/share/notes.txt", "/share/my%20file.txt")
    client = _FakeHttp({"/share": _Response(xml),
                        "/share/photos": _Response(EMPTY)})
    target = WebDavTarget(Credentials(host="http://h", root="/share"),
                          client=client)
    store = NodeStore()
    root = store.add(-1, "/share", attrs=DIR)
    target.enumerate(store, root)
    assert "my file.txt" in {store.name(i) for i in range(len(store))}


# ---- the connect dialog -------------------------------------------------

def test_dialog_lists_every_backend_even_unusable_ones(qapp):
    """'SSH is not listed' sends people hunting; 'SSH needs paramiko' tells
    them what to do."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    dialog = RemoteTargetDialog()
    ids = [dialog.backend.itemData(i) for i in range(dialog.backend.count())]
    assert {"ssh", "webdav"} <= set(ids)


def test_an_unusable_backend_is_disabled_with_a_reason(qapp):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    dialog = RemoteTargetDialog()
    for i in range(dialog.backend.count()):
        target_id = dialog.backend.itemData(i)
        _cls, usable, _why = dialog._classes[target_id]
        assert dialog.backend.model().item(i).isEnabled() == usable


def test_a_missing_host_is_refused_before_connecting(qapp):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    dialog = RemoteTargetDialog()
    dialog.host.setText("   ")
    target, message = dialog.selected()
    if target is None and "host is required" not in message:
        pytest.skip("selected backend is unavailable on this machine")
    assert target is None


def test_a_filled_in_dialog_produces_a_usable_target(qapp):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    dialog = RemoteTargetDialog()
    index = next((i for i in range(dialog.backend.count())
                  if dialog._classes[dialog.backend.itemData(i)][1]), None)
    if index is None:
        pytest.skip("no remote backend is installed on this machine")
    dialog.backend.setCurrentIndex(index)
    dialog.host.setText("example.test")
    dialog.root.setText("/data")
    target, label = dialog.selected()
    assert target is not None
    assert target.credentials.host == "example.test"
    assert target.credentials.root == "/data"
    assert "example.test" in label
