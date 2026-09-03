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
    Credentials, RemoteEnumerator, TargetError,
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
    """SSH cannot connect to nothing, and finding that out from paramiko is
    a worse experience than being told in the dialog."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    dialog = RemoteTargetDialog()
    index = next((i for i in range(dialog.backend.count())
                  if dialog.backend.itemData(i) == "ssh"), None)
    if index is None or not dialog._classes["ssh"][1]:
        pytest.skip("paramiko is not installed on this machine")
    dialog.backend.setCurrentIndex(index)
    dialog.host.setText("   ")
    target, message = dialog.selected()
    assert target is None
    assert "required" in message


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


# ---- credential storage (spec 6.2) --------------------------------------

class _FakeVault:
    """Stands in for Windows Credential Manager: same three operations."""

    def __init__(self) -> None:
        self.entries: dict[str, tuple[str, str]] = {}

    def write(self, key, username, secret):
        self.entries[key] = (username, secret)

    def read(self, key):
        return self.entries.get(key)

    def erase(self, key):
        self.entries.pop(key, None)


def test_a_saved_password_comes_back():
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    store = CredentialStore(vault)
    store.save("ssh", Credentials(host="box", username="ana", password="s3cret"))
    assert store.load("ssh", "box", "ana") == ("ana", "s3cret")


def test_credentials_are_keyed_by_backend_host_and_user():
    """Two accounts on one host, and one account on two hosts, must not
    overwrite each other -- a single key per backend would do exactly that."""
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    store = CredentialStore(vault)
    store.save("ssh", Credentials(host="box", username="ana", password="one"))
    store.save("ssh", Credentials(host="box", username="bo", password="two"))
    store.save("webdav", Credentials(host="box", username="ana", password="three"))
    assert store.load("ssh", "box", "ana")[1] == "one"
    assert store.load("ssh", "box", "bo")[1] == "two"
    assert store.load("webdav", "box", "ana")[1] == "three"


def test_an_unknown_credential_is_absent_not_an_error():
    from modules.treesize.targets.credential_store import CredentialStore

    store = CredentialStore(_FakeVault())
    assert store.load("ssh", "nothing-here", "nobody") is None


def test_forgetting_a_credential_removes_it():
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    store = CredentialStore(vault)
    store.save("ssh", Credentials(host="box", username="ana", password="s3cret"))
    store.forget("ssh", "box", "ana")
    assert store.load("ssh", "box", "ana") is None


def test_an_empty_password_is_not_written_to_the_vault():
    """Saving an empty secret would shadow a real stored one on the next load."""
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    store = CredentialStore(vault)
    store.save("ssh", Credentials(host="box", username="ana", password=""))
    assert vault.entries == {}


def test_a_vault_that_refuses_does_not_break_the_scan():
    """Credential Manager can be locked down by policy. A scan that would
    otherwise run must not die because the password could not be cached."""
    from modules.treesize.targets.credential_store import CredentialStore

    class _Broken:
        def write(self, *_a):
            raise OSError("policy")

        def read(self, *_a):
            raise OSError("policy")

        def erase(self, *_a):
            raise OSError("policy")

    store = CredentialStore(_Broken())
    store.save("ssh", Credentials(host="box", username="ana", password="x"))
    assert store.load("ssh", "box", "ana") is None
    store.forget("ssh", "box", "ana")


# ---- throttling (spec 6.2) ----------------------------------------------

class _Throttleable:
    def __init__(self, status, headers=None):
        self.status_code = status
        self.headers = headers or {}


def test_a_throttled_call_is_retried_with_a_doubling_delay():
    from modules.treesize.targets.base import retry_on_throttle

    replies = [_Throttleable(429), _Throttleable(503), _Throttleable(207)]
    slept: list[float] = []
    result = retry_on_throttle(lambda: replies.pop(0), base_delay=0.5,
                               sleep=slept.append)
    assert result.status_code == 207
    assert slept == [0.5, 1.0]


def test_a_retry_after_header_wins_over_the_computed_delay():
    """The server knows when it will be ready; we are guessing."""
    from modules.treesize.targets.base import retry_on_throttle

    replies = [_Throttleable(429, {"Retry-After": "7"}), _Throttleable(200)]
    slept: list[float] = []
    retry_on_throttle(lambda: replies.pop(0), base_delay=0.5, sleep=slept.append)
    assert slept == [7.0]


def test_a_nonsense_retry_after_falls_back_to_the_computed_delay():
    from modules.treesize.targets.base import retry_on_throttle

    replies = [_Throttleable(503, {"Retry-After": "Tue, 01 Jan 2030 00:00:00 GMT"}),
               _Throttleable(200)]
    slept: list[float] = []
    retry_on_throttle(lambda: replies.pop(0), base_delay=0.25, sleep=slept.append)
    assert slept == [0.25]


def test_giving_up_returns_the_throttled_response_rather_than_raising():
    """The caller already reports a bad status as a per-directory error; a
    raise here would end the whole scan on one busy folder."""
    from modules.treesize.targets.base import retry_on_throttle

    slept: list[float] = []
    result = retry_on_throttle(lambda: _Throttleable(429), attempts=3,
                               base_delay=0.1, sleep=slept.append)
    assert result.status_code == 429
    assert len(slept) == 2, "no sleep after the last attempt"


def test_a_successful_call_never_sleeps():
    from modules.treesize.targets.base import retry_on_throttle

    slept: list[float] = []
    retry_on_throttle(lambda: _Throttleable(207), sleep=slept.append)
    assert slept == []


def test_webdav_retries_a_throttled_propfind(qapp):
    """The one backend that can actually be throttled today."""
    class _Client:
        def __init__(self):
            self.calls = 0

        def request(self, *_a, **_k):
            self.calls += 1
            if self.calls == 1:
                return _Throttleable(429)
            reply = _Throttleable(207)
            reply.text = (
                '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">'
                '<d:response><d:href>/dav/f.txt</d:href><d:propstat><d:prop>'
                '<d:resourcetype/><d:getcontentlength>12</d:getcontentlength>'
                "</d:prop></d:propstat></d:response></d:multistatus>")
            return reply

    client = _Client()
    walker = remote._WebDavWalker(
        WebDavTarget(Credentials(host="http://x")), client)
    walker.sleep = lambda _seconds: None
    entries = list(walker.list_dir("/dav"))
    assert client.calls == 2
    assert entries == [("f.txt", 12, False, 0)]


# ---- remembering a password from the dialog (spec 6.2) ------------------

def _usable_backend(dialog):
    """A usable backend that actually HAS a password to remember.

    Outlook is usable wherever pywin32 is and has no password field at all,
    so "the first usable one" is not the same question.
    """
    for i in range(dialog.backend.count()):
        target_id = dialog.backend.itemData(i)
        target_class, usable, _why = dialog._classes[target_id]
        if usable and target_class.form_labels.get("password"):
            dialog.select_backend(target_id)
            return target_id
    return None


def test_the_dialog_offers_to_remember_a_password(qapp):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    from modules.treesize.targets.credential_store import CredentialStore

    dialog = RemoteTargetDialog(credential_store=CredentialStore(_FakeVault()))
    assert not dialog.remember.isChecked(), (
        "storing a secret is opt-in, not something that happens because the "
        "user connected once")


def test_a_remembered_password_reaches_the_vault(qapp):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    from modules.treesize.targets.credential_store import (
        CredentialStore, credential_key,
    )

    vault = _FakeVault()
    dialog = RemoteTargetDialog(credential_store=CredentialStore(vault))
    target_id = _usable_backend(dialog)
    if target_id is None:
        pytest.skip("no remote backend is installed on this machine")
    dialog.host.setText("example.test")
    dialog.username.setText("ana")
    dialog.password.setText("s3cret")
    dialog.remember.setChecked(True)
    target, _label = dialog.selected()
    assert target is not None
    key = credential_key(target_id, "example.test", "ana")
    assert vault.entries[key] == ("ana", "s3cret")


def test_unticking_remember_clears_a_previously_stored_password(qapp):
    """Otherwise the only way to forget a password is Credential Manager."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    dialog = RemoteTargetDialog(credential_store=CredentialStore(vault))
    target_id = _usable_backend(dialog)
    if target_id is None:
        pytest.skip("no remote backend is installed on this machine")
    CredentialStore(vault).save(
        target_id, Credentials(host="example.test", username="ana",
                               password="old"))
    dialog.host.setText("example.test")
    dialog.username.setText("ana")
    dialog.password.setText("old")
    dialog.remember.setChecked(False)
    dialog.selected()
    assert vault.entries == {}


def test_a_stored_password_is_offered_back(qapp):
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    dialog = RemoteTargetDialog(credential_store=CredentialStore(vault))
    target_id = _usable_backend(dialog)
    if target_id is None:
        pytest.skip("no remote backend is installed on this machine")
    CredentialStore(vault).save(
        target_id, Credentials(host="example.test", username="ana",
                               password="s3cret"))
    dialog.host.setText("example.test")
    dialog.username.setText("ana")
    dialog.recall_password()
    assert dialog.password.text() == "s3cret"
    assert dialog.remember.isChecked()


def test_recall_leaves_a_typed_password_alone(qapp):
    """Overwriting what the user just typed with a stale stored secret is how
    a rotated password produces an unexplainable auth failure."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog
    from modules.treesize.targets.credential_store import CredentialStore

    vault = _FakeVault()
    dialog = RemoteTargetDialog(credential_store=CredentialStore(vault))
    target_id = _usable_backend(dialog)
    if target_id is None:
        pytest.skip("no remote backend is installed on this machine")
    CredentialStore(vault).save(
        target_id, Credentials(host="example.test", username="ana",
                               password="stored"))
    dialog.host.setText("example.test")
    dialog.username.setText("ana")
    dialog.password.setText("typed")
    dialog.recall_password()
    assert dialog.password.text() == "typed"
