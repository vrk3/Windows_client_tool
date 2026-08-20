"""Spec 6.2: the object-store, API and MAPI backends.

No network and no SDK: every client is injected. What is tested is the part
that actually breaks -- turning flat keys or a parent-id graph into a tree,
following pagination to the end, and not dropping what does not fit.
"""
import pytest

from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup
from modules.treesize.targets import base
from modules.treesize.targets.base import Credentials, PrefixTreeBuilder


def _store():
    store = NodeStore()
    return store, store.add(-1, "bucket", attrs=DIR)


# ---- prefix synthesis ---------------------------------------------------

def test_flat_keys_become_a_folder_tree():
    """S3 has no folders. "a/b/c.txt" has to become three nodes, and the two
    folders have to be created once however many keys sit under them."""
    store, root = _store()
    builder = PrefixTreeBuilder(store, root)
    builder.add("a/b/c.txt", 100)
    builder.add("a/b/d.txt", 200)
    builder.add("a/e.txt", 50)
    builder.finish()
    rollup(store)
    names = [store.name(i) for i in range(len(store))]
    assert names.count("b") == 1
    assert set(names) == {"bucket", "a", "b", "c.txt", "d.txt", "e.txt"}
    assert store.size[root] == 350


def test_a_synthesized_folder_is_a_folder():
    store, root = _store()
    builder = PrefixTreeBuilder(store, root)
    builder.add("a/c.txt", 1)
    builder.finish()
    folder = next(i for i in range(len(store)) if store.name(i) == "a")
    assert store.attrs[folder] & DIR
    assert store.size[folder] == 0, "a folder's own size is never its children's"


def test_a_folder_marker_key_does_not_become_a_file():
    """Consoles write a zero-byte "a/" key to fake an empty folder. Treating
    it as a file puts a nameless 0-byte entry in every such folder."""
    store, root = _store()
    builder = PrefixTreeBuilder(store, root)
    builder.add("a/", 0)
    builder.add("a/c.txt", 5)
    builder.finish()
    assert [store.name(i) for i in range(len(store))] == ["bucket", "a", "c.txt"]


def test_a_key_at_the_top_has_no_folder():
    store, root = _store()
    builder = PrefixTreeBuilder(store, root)
    builder.add("top.txt", 7)
    builder.finish()
    node = next(i for i in range(len(store)) if store.name(i) == "top.txt")
    assert store.parent[node] == root


def test_allocated_equals_size_because_there_is_no_cluster_geometry():
    store, root = _store()
    builder = PrefixTreeBuilder(store, root)
    builder.add("a/c.txt", 4097)
    builder.finish()
    node = next(i for i in range(len(store)) if store.name(i) == "c.txt")
    assert store.alloc[node] == store.size[node] == 4097


def test_duplicate_keys_do_not_duplicate_nodes():
    store, root = _store()
    builder = PrefixTreeBuilder(store, root)
    builder.add("a/c.txt", 10)
    builder.add("a/c.txt", 10)
    builder.finish()
    assert [store.name(i) for i in range(len(store))].count("c.txt") == 1


# ---- S3 -----------------------------------------------------------------

class _FakeS3:
    """list_objects_v2, including its continuation-token paging."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def list_objects_v2(self, **kwargs):
        self.calls.append(kwargs)
        index = 0
        if kwargs.get("ContinuationToken"):
            index = int(kwargs["ContinuationToken"])
        return self.pages[index]


def _page(contents, next_token=None):
    page = {"Contents": contents}
    if next_token is not None:
        page["IsTruncated"] = True
        page["NextContinuationToken"] = next_token
    else:
        page["IsTruncated"] = False
    return page


def test_s3_builds_a_tree_from_object_keys():
    from modules.treesize.targets.cloud import S3Target

    client = _FakeS3([_page([
        {"Key": "logs/a.log", "Size": 10},
        {"Key": "logs/b.log", "Size": 20},
    ])])
    store, root = _store()
    target = S3Target(Credentials(host="my-bucket"), client=client)
    target.enumerate(store, root)
    rollup(store)
    assert store.size[root] == 30
    assert client.calls[0]["Bucket"] == "my-bucket"


def test_s3_follows_every_page():
    """Stopping at the first page is a silent 1000-object ceiling -- the tree
    looks complete and is wrong, which is the worst failure this tool has."""
    from modules.treesize.targets.cloud import S3Target

    client = _FakeS3([
        _page([{"Key": "a.txt", "Size": 1}], next_token="1"),
        _page([{"Key": "b.txt", "Size": 2}]),
    ])
    store, root = _store()
    S3Target(Credentials(host="b"), client=client).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 3
    assert len(client.calls) == 2


def test_s3_stops_when_cancelled():
    from modules.treesize.targets.cloud import S3Target

    client = _FakeS3([
        _page([{"Key": "a.txt", "Size": 1}], next_token="1"),
        _page([{"Key": "b.txt", "Size": 2}]),
    ])
    store, root = _store()
    S3Target(Credentials(host="b"), client=client).enumerate(
        store, root, should_cancel=lambda: True)
    assert len(client.calls) <= 1


def test_s3_scopes_to_a_prefix_when_one_is_given():
    from modules.treesize.targets.cloud import S3Target

    client = _FakeS3([_page([{"Key": "logs/a.log", "Size": 1}])])
    store, root = _store()
    S3Target(Credentials(host="b", root="logs/"), client=client).enumerate(
        store, root)
    assert client.calls[0]["Prefix"] == "logs/"


# ---- Azure Blob ---------------------------------------------------------

class _FakeBlob:
    def __init__(self, name, size, last_modified=None):
        self.name, self.size, self.last_modified = name, size, last_modified


class _FakeContainer:
    def __init__(self, blobs):
        self._blobs = blobs
        self.kwargs = None

    def list_blobs(self, **kwargs):
        self.kwargs = kwargs
        return iter(self._blobs)


def test_azure_synthesizes_the_same_tree_from_blob_names():
    from modules.treesize.targets.cloud import AzureBlobTarget

    container = _FakeContainer([_FakeBlob("a/b.txt", 12), _FakeBlob("a/c.txt", 8)])
    store, root = _store()
    AzureBlobTarget(Credentials(host="acct", root=""),
                    client=container).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 20
    folder = next(i for i in range(len(store)) if store.name(i) == "a")
    assert store.attrs[folder] & DIR


def test_azure_reports_no_file_operations():
    from modules.treesize.targets.cloud import AzureBlobTarget

    assert not AzureBlobTarget().supports_file_ops()


# ---- Google Drive -------------------------------------------------------

class _FakeDrive:
    """files().list(...).execute(), with its pageToken paging."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self._index = 0

    def files(self):
        return self

    def list(self, **kwargs):
        self.calls.append(kwargs)
        self._index = 1 if kwargs.get("pageToken") else 0
        return self

    def execute(self):
        return self.pages[self._index]


FOLDER = "application/vnd.google-apps.folder"


def test_drive_assembles_a_tree_from_parent_ids():
    """Drive has no paths: every file names its parent by id, so the tree is
    assembled the way the MFT one is."""
    from modules.treesize.targets.cloud import GoogleDriveTarget

    pages = [{"files": [
        {"id": "root", "name": "My Drive", "mimeType": FOLDER, "parents": []},
        {"id": "f1", "name": "Docs", "mimeType": FOLDER, "parents": ["root"]},
        {"id": "a", "name": "a.txt", "size": "100", "parents": ["f1"]},
        {"id": "b", "name": "b.txt", "size": "50", "parents": ["root"]},
    ]}]
    store, root = _store()
    GoogleDriveTarget(Credentials(), client=_FakeDrive(pages)).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 150
    docs = next(i for i in range(len(store)) if store.name(i) == "Docs")
    assert store.size[docs] == 100


def test_drive_keeps_an_orphan_rather_than_dropping_it():
    """A file whose parent was not returned -- shared, trashed, or outside the
    query -- still occupies space. Dropping it makes the total quietly wrong."""
    from modules.treesize.targets.cloud import GoogleDriveTarget

    pages = [{"files": [
        {"id": "a", "name": "orphan.txt", "size": "70", "parents": ["missing"]},
    ]}]
    store, root = _store()
    GoogleDriveTarget(Credentials(), client=_FakeDrive(pages)).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 70
    node = next(i for i in range(len(store)) if store.name(i) == "orphan.txt")
    assert store.parent[node] == root


def test_drive_follows_page_tokens():
    from modules.treesize.targets.cloud import GoogleDriveTarget

    pages = [
        {"files": [{"id": "a", "name": "a.txt", "size": "1", "parents": []}],
         "nextPageToken": "2"},
        {"files": [{"id": "b", "name": "b.txt", "size": "2", "parents": []}]},
    ]
    client = _FakeDrive(pages)
    store, root = _store()
    GoogleDriveTarget(Credentials(), client=client).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 3
    assert len(client.calls) == 2


def test_drive_prefers_the_quota_figure_over_the_reported_size():
    """quotaBytesUsed is what the file actually costs the account; `size` is
    the content length, and the two differ for anything with revisions."""
    from modules.treesize.targets.cloud import GoogleDriveTarget

    pages = [{"files": [
        {"id": "a", "name": "a.txt", "size": "100", "quotaBytesUsed": "250",
         "parents": []},
    ]}]
    store, root = _store()
    GoogleDriveTarget(Credentials(), client=_FakeDrive(pages)).enumerate(store, root)
    node = next(i for i in range(len(store)) if store.name(i) == "a.txt")
    assert store.size[node] == 250


def test_a_google_folder_is_a_folder_even_with_no_children():
    from modules.treesize.targets.cloud import GoogleDriveTarget

    pages = [{"files": [
        {"id": "f", "name": "Empty", "mimeType": FOLDER, "parents": []},
    ]}]
    store, root = _store()
    GoogleDriveTarget(Credentials(), client=_FakeDrive(pages)).enumerate(store, root)
    node = next(i for i in range(len(store)) if store.name(i) == "Empty")
    assert store.attrs[node] & DIR


# ---- SharePoint ---------------------------------------------------------

class _GraphResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}

    def json(self):
        return self._payload


class _FakeGraph:
    """One canned reply per requested URL."""

    def __init__(self, replies):
        self.replies = replies
        self.requested = []

    def get(self, url, **_kwargs):
        self.requested.append(url)
        return _GraphResponse(self.replies.get(url, {"value": []}))


def test_sharepoint_walks_children_by_item_id():
    from modules.treesize.targets.cloud import SharePointTarget

    replies = {
        "/drives/d1/root/children": {"value": [
            {"id": "i1", "name": "Docs", "folder": {"childCount": 1}},
            {"id": "i2", "name": "top.txt", "size": 10, "file": {}},
        ]},
        "/drives/d1/items/i1/children": {"value": [
            {"id": "i3", "name": "deep.txt", "size": 40, "file": {}},
        ]},
    }
    client = _FakeGraph(replies)
    store, root = _store()
    SharePointTarget(Credentials(extra={"drive_id": "d1"}),
                     client=client).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 50
    docs = next(i for i in range(len(store)) if store.name(i) == "Docs")
    assert store.size[docs] == 40


def test_sharepoint_follows_the_next_link():
    from modules.treesize.targets.cloud import SharePointTarget

    replies = {
        "/drives/d1/root/children": {
            "value": [{"id": "a", "name": "a.txt", "size": 1, "file": {}}],
            "@odata.nextLink": "/drives/d1/root/children?skip=1"},
        "/drives/d1/root/children?skip=1": {
            "value": [{"id": "b", "name": "b.txt", "size": 2, "file": {}}]},
    }
    store, root = _store()
    SharePointTarget(Credentials(extra={"drive_id": "d1"}),
                     client=_FakeGraph(replies)).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 3


def test_sharepoint_records_a_folder_it_cannot_read_and_keeps_going():
    from modules.treesize.targets.cloud import SharePointTarget

    class _Refusing(_FakeGraph):
        def get(self, url, **kwargs):
            if "i1" in url:
                return _GraphResponse({"error": "forbidden"}, status=403)
            return super().get(url, **kwargs)

    replies = {"/drives/d1/root/children": {"value": [
        {"id": "i1", "name": "Locked", "folder": {}},
        {"id": "i2", "name": "ok.txt", "size": 5, "file": {}},
    ]}}
    store, root = _store()
    target = SharePointTarget(Credentials(extra={"drive_id": "d1"}),
                              client=_Refusing(replies))
    target.enumerate(store, root)
    rollup(store)
    assert store.size[root] == 5
    assert target.errors, "an unreadable folder has to be reported, not hidden"


# ---- Outlook ------------------------------------------------------------

class _FakeItem:
    def __init__(self, subject, size):
        self.Subject, self.Size = subject, size


class _FakeItems:
    def __init__(self, items):
        self._items = items
        self.Count = len(items)

    def __iter__(self):
        return iter(self._items)


class _FakeFolder:
    def __init__(self, name, items=(), folders=()):
        self.Name = name
        self.Items = _FakeItems(list(items))
        self.Folders = list(folders)


def test_outlook_maps_folders_and_item_sizes():
    from modules.treesize.targets.outlook import OutlookTarget

    inbox = _FakeFolder("Inbox", items=[_FakeItem("Hello", 1000),
                                        _FakeItem("Re: Hello", 2000)])
    archive = _FakeFolder("Archive", items=[_FakeItem("Old", 500)])
    root_folder = _FakeFolder("Mailbox", folders=[inbox, archive])
    store, root = _store()
    OutlookTarget(client=root_folder).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 3500
    inbox_node = next(i for i in range(len(store)) if store.name(i) == "Inbox")
    assert store.size[inbox_node] == 3000


def test_outlook_is_read_only():
    """Pro reads a mailbox; it does not delete mail from a disk-usage tool."""
    from modules.treesize.targets.base import TargetError
    from modules.treesize.targets.outlook import OutlookTarget

    target = OutlookTarget()
    assert not target.supports_file_ops()
    with pytest.raises(TargetError):
        target.open_stream("Inbox/Hello")


def test_an_item_without_a_subject_still_counts():
    from modules.treesize.targets.outlook import OutlookTarget

    folder = _FakeFolder("Inbox", items=[_FakeItem("", 900)])
    store, root = _store()
    OutlookTarget(client=folder).enumerate(store, root)
    rollup(store)
    assert store.size[root] == 900


def test_an_unreadable_outlook_folder_does_not_end_the_scan():
    from modules.treesize.targets.outlook import OutlookTarget

    class _Exploding:
        Name = "Broken"
        Folders = ()

        @property
        def Items(self):
            raise OSError("MAPI said no")

    root_folder = _FakeFolder("Mailbox", folders=[
        _Exploding(), _FakeFolder("Fine", items=[_FakeItem("x", 7)])])
    store, root = _store()
    target = OutlookTarget(client=root_folder)
    target.enumerate(store, root)
    rollup(store)
    assert store.size[root] == 7
    assert target.errors


# ---- registration and availability --------------------------------------

def test_every_spec_backend_is_registered():
    """Spec 6.2 lists eight targets. Local is the pane's own path; the other
    seven are here."""
    import modules.treesize.targets  # noqa: F401  (registers them)

    ids = {cls.id for cls, _ok, _why in base.available_targets()}
    assert {"ssh", "webdav", "s3", "azure", "gdrive", "sharepoint",
            "outlook"} <= ids


def test_a_backend_with_no_sdk_says_which_package_it_wants():
    import modules.treesize.targets  # noqa: F401

    for cls, ok, why in base.available_targets():
        assert ok or "pip install" in why or "pywin32" in why, cls.id


# ---- the connect dialog, per backend ------------------------------------

def test_the_dialog_opens_on_a_backend_that_can_actually_be_used(qapp):
    """Backends sort alphabetically and AWS S3 comes first. Opening with a
    greyed-out entry preselected makes the dialog look broken before the user
    has done anything."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    target_id = dialog.backend.currentData()
    _cls, usable, _why = dialog._classes[target_id]
    assert usable or not any(ok for _c, ok, _w in base.available_targets())


def test_the_form_is_labelled_for_the_chosen_backend(qapp):
    """"Host" is wrong for a bucket and meaningless for a mailbox. Spec 6.1
    keeps one dialog for every backend, so the fields have to say what the
    chosen backend actually wants."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    dialog.select_backend("s3")
    assert dialog.label_for("host").text().startswith("Bucket")
    assert dialog.label_for("username").text().startswith("Access key")
    assert not dialog.port.isVisible() or not dialog.isVisible()
    assert not dialog.row_is_used("port"), "S3 has no port to set"


def test_a_backend_that_needs_no_host_does_not_demand_one(qapp):
    """Google Drive has no host at all. Refusing to proceed without one makes
    the backend unreachable through its own dialog."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    dialog.select_backend("gdrive")
    assert not dialog.row_is_used("host")
    dialog.password.setText("a-token")
    target, message = dialog.selected()
    if target is None:
        assert "not installed" in message or "pip install" in message
    else:
        assert target.credentials.password == "a-token"


def test_a_missing_required_field_names_itself(qapp):
    """"A host is required" is the wrong sentence when the field on screen
    says Server URL. WebDAV rather than S3 because an unavailable backend is
    refused for its missing package first, which is the more useful message."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    if not dialog.select_backend("webdav") or not dialog._classes["webdav"][1]:
        pytest.skip("httpx is not installed on this machine")
    dialog.host.setText("")
    target, message = dialog.selected()
    assert target is None
    assert "Server URL" in message, message


def test_outlook_asks_for_nothing_at_all(qapp):
    """A local mailbox needs no credentials; every field is optional."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    dialog.select_backend("outlook")
    assert dialog.required_fields() == ()
    target, message = dialog.selected()
    assert target is not None, message


def test_an_object_store_prefix_does_not_default_to_a_slash(qapp):
    """A leading "/" is a real prefix in S3 and matches nothing: object keys
    do not start with one. The path default belongs to path-shaped backends."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    dialog.select_backend("s3")
    assert dialog.root.text() == ""
    dialog.select_backend("ssh")
    assert dialog.root.text() == "/"


def test_switching_backends_keeps_what_the_user_typed(qapp):
    """Picking the wrong entry from the Type list must not clear the form."""
    from modules.treesize.ui.remote_dialog import RemoteTargetDialog

    dialog = RemoteTargetDialog()
    dialog.select_backend("s3")
    dialog.root.setText("logs/")
    dialog.select_backend("azure")
    assert dialog.root.text() == "logs/"
