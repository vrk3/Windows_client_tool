"""Object-store and API scan targets: S3, Azure Blob, Google Drive, SharePoint.

Spec 6.2's remaining backends, minus Outlook, which is MAPI and lives next
door. Every client is injectable, because what breaks here is never the SDK
call -- it is the tree assembly and the paging around it, and both can be
tested without an account.

Three shapes of remote, and the difference matters:

* **Object stores** (S3, Azure) have no folders. They return flat keys whose
  slashes mean nothing to the service, and `PrefixTreeBuilder` gives those
  slashes their conventional meaning.
* **Google Drive** has no paths either: every file names its parent by id, so
  the tree is assembled from a graph, the way the MFT one is.
* **SharePoint** does have folders, so it walks one directory at a time
  through `RemoteEnumerator` -- addressing children by item id rather than by
  path, which is what the walk's fifth tuple element is for.

Every one of them sets `alloc` equal to `size`: none has cluster geometry, and
rounding up to a block size the service never mentioned would be inventing
data.
"""
from ..store.node_store import DIR
from .base import (
    Credentials, PrefixTreeBuilder, RemoteEnumerator, ScanTarget, TargetError,
    register, retry_on_throttle, unix_to_filetime,
)

#: What Drive calls a folder. There is no other flag for it.
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

#: One Drive page. The API caps it at 1000 and defaults to 100; asking for
#: the cap turns a 400k-file account from 4000 round trips into 400.
DRIVE_PAGE_SIZE = 1000

DRIVE_FIELDS = ("nextPageToken, files(id, name, mimeType, size, "
                "quotaBytesUsed, modifiedTime, parents)")


def _rfc3339_to_filetime(value) -> int:
    if not value:
        return 0
    try:
        from datetime import datetime

        text = str(value).replace("Z", "+00:00")
        return unix_to_filetime(datetime.fromisoformat(text).timestamp())
    except (TypeError, ValueError):
        # A malformed timestamp is not worth failing a scan over; the file
        # still has a size, which is what this tool is about.
        return 0


def _datetime_to_filetime(value) -> int:
    if value is None:
        return 0
    try:
        return unix_to_filetime(value.timestamp())
    except (AttributeError, TypeError, ValueError, OSError):
        return 0


class S3Target(ScanTarget):
    """AWS S3, through `list_objects_v2` (spec 6.2)."""

    id = "s3"
    display_name = "AWS S3"
    icon = "☁"
    file_ops = False           # deleting objects from a disk-usage tool: no
    form_labels = {"host": "Bucket", "port": None,
                   "username": "Access key ID", "password": "Secret access key",
                   "root": "Prefix"}
    required_fields = ("host",)

    def __init__(self, credentials: Credentials | None = None, client=None) -> None:
        super().__init__(credentials)
        self._client = client

    @classmethod
    def is_available(cls):
        try:
            __import__("boto3")
        except ImportError:
            return False, ("boto3 is not installed. "
                           "Install it with: pip install boto3")
        return True, ""

    def authenticate(self) -> None:
        if self._client is not None:
            return
        ok, why = self.is_available()
        if not ok:
            raise TargetError(why)
        import boto3

        creds = self.credentials
        try:
            self._client = boto3.client(
                "s3",
                aws_access_key_id=creds.username or None,
                aws_secret_access_key=creds.password or None,
                region_name=creds.extra.get("region") or None)
        except Exception as exc:                    # noqa: BLE001
            raise TargetError(f"Could not open S3: {exc}") from exc

    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        self.authenticate()
        bucket = self.credentials.host
        if not bucket:
            raise TargetError("A bucket name is required.")
        prefix = (self.credentials.root or "").lstrip("/")
        if prefix in ("", "/"):
            prefix = ""
        builder = PrefixTreeBuilder(store, root)
        batch_start = len(store)
        token = None
        while True:
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            request = {"Bucket": bucket, "Prefix": prefix}
            if token:
                request["ContinuationToken"] = token
            try:
                # boto3 does its own throttle retries, so retry_on_throttle
                # would only double what botocore already handles.
                page = self._client.list_objects_v2(**request)
            except Exception as exc:                # noqa: BLE001
                raise TargetError(f"Listing {bucket} failed: {exc}") from exc
            for obj in page.get("Contents", ()) or ():
                key = obj.get("Key") or ""
                if prefix and key.startswith(prefix):
                    key = key[len(prefix):]
                builder.add(key.lstrip("/"), int(obj.get("Size") or 0),
                            _datetime_to_filetime(obj.get("LastModified")))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
            # A truncated page with no token would loop forever; both have to
            # agree before another round trip is made.
            if not page.get("IsTruncated") or not page.get(
                    "NextContinuationToken"):
                break
            token = page["NextContinuationToken"]
        builder.finish()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)


class AzureBlobTarget(ScanTarget):
    """Azure Blob Storage: the same prefix-to-tree synthesis as S3."""

    id = "azure"
    display_name = "Azure Blob Storage"
    icon = "☁"
    file_ops = False
    form_labels = {"host": "Account URL", "port": None,
                   "username": "Container", "password": "Access key or SAS",
                   "root": "Prefix"}
    required_fields = ("host", "username")

    def __init__(self, credentials: Credentials | None = None, client=None) -> None:
        super().__init__(credentials)
        self._client = client

    @classmethod
    def is_available(cls):
        try:
            __import__("azure.storage.blob")
        except ImportError:
            return False, ("azure-storage-blob is not installed. "
                           "Install it with: pip install azure-storage-blob")
        return True, ""

    def authenticate(self) -> None:
        if self._client is not None:
            return
        ok, why = self.is_available()
        if not ok:
            raise TargetError(why)
        from azure.storage.blob import BlobServiceClient

        creds = self.credentials
        container = creds.extra.get("container") or creds.username
        if not container:
            raise TargetError("A container name is required.")
        try:
            service = BlobServiceClient(account_url=creds.host,
                                        credential=creds.password or None)
            self._client = service.get_container_client(container)
        except Exception as exc:                    # noqa: BLE001
            raise TargetError(f"Could not open the container: {exc}") from exc

    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        self.authenticate()
        prefix = (self.credentials.root or "").lstrip("/")
        if prefix == "/":
            prefix = ""
        builder = PrefixTreeBuilder(store, root)
        batch_start = len(store)
        # The SDK's iterator pages transparently, so cancellation is checked
        # per blob rather than per page -- there is no page boundary to see.
        for blob in self._client.list_blobs(name_starts_with=prefix or None):
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            name = getattr(blob, "name", "") or ""
            if prefix and name.startswith(prefix):
                name = name[len(prefix):]
            builder.add(name.lstrip("/"), int(getattr(blob, "size", 0) or 0),
                        _datetime_to_filetime(
                            getattr(blob, "last_modified", None)))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
        builder.finish()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)


class GoogleDriveTarget(ScanTarget):
    """Google Drive v3: a parent-id graph, assembled into a tree."""

    id = "gdrive"
    display_name = "Google Drive"
    icon = "☁"
    file_ops = False
    form_labels = {"host": None, "port": None, "username": None,
                   "password": "OAuth token", "root": None}
    required_fields = ("password",)

    def __init__(self, credentials: Credentials | None = None, client=None) -> None:
        super().__init__(credentials)
        self._client = client

    @classmethod
    def is_available(cls):
        try:
            __import__("googleapiclient.discovery")
        except ImportError:
            return False, ("google-api-python-client is not installed. "
                           "Install it with: pip install "
                           "google-api-python-client google-auth-oauthlib")
        return True, ""

    def authenticate(self) -> None:
        if self._client is not None:
            return
        ok, why = self.is_available()
        if not ok:
            raise TargetError(why)
        try:
            from google.oauth2.credentials import Credentials as OAuthCreds
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise TargetError(str(exc)) from exc

        token = self.credentials.password or self.credentials.extra.get("token")
        if not token:
            raise TargetError(
                "Google Drive needs an OAuth token. Authorise the app and "
                "paste the token, or point at a saved credentials file.")
        try:
            self._client = build(
                "drive", "v3",
                credentials=OAuthCreds(token),
                cache_discovery=False)
        except Exception as exc:                    # noqa: BLE001
            raise TargetError(f"Could not open Drive: {exc}") from exc

    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        self.authenticate()
        records = self._fetch(should_cancel, wait_if_paused)
        return self._assemble(store, root, records, on_batch, batch_size)

    def _fetch(self, should_cancel=None, wait_if_paused=None) -> dict:
        """Every file in one query, keyed by id.

        Drive returns parents, not paths, so nothing can be placed in the tree
        until the whole listing is in hand: a file's parent may well arrive on
        a later page than the file.
        """
        records: dict[str, dict] = {}
        token = None
        while True:
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            request = {
                "pageSize": DRIVE_PAGE_SIZE,
                "fields": DRIVE_FIELDS,
                "q": "trashed = false",
            }
            if token:
                request["pageToken"] = token
            try:
                page = self._client.files().list(**request).execute()
            except Exception as exc:                # noqa: BLE001
                raise TargetError(f"Listing Drive failed: {exc}") from exc
            for record in page.get("files", ()) or ():
                if record.get("id"):
                    records[record["id"]] = record
            token = page.get("nextPageToken")
            if not token:
                break
        return records

    def _assemble(self, store, root: int, records: dict, on_batch=None,
                  batch_size: int = 500) -> int:
        from collections import deque

        children: dict[str, list] = {}
        tops: list[str] = []
        for file_id, record in records.items():
            parents = record.get("parents") or []
            parent = parents[0] if parents else None
            # A parent outside the listing -- shared in, or a drive the query
            # did not cover -- makes the file an orphan, NOT a file to drop.
            # Dropping it makes the total quietly wrong, which is the one
            # failure mode this tool cannot have.
            if parent and parent in records:
                children.setdefault(parent, []).append(file_id)
            else:
                tops.append(file_id)

        batch_start = len(store)
        queue = deque((file_id, root) for file_id in tops)
        while queue:
            file_id, parent_node = queue.popleft()
            record = records[file_id]
            is_folder = record.get("mimeType") == GOOGLE_FOLDER_MIME
            size = 0 if is_folder else _drive_size(record)
            node = store.add(parent_node, record.get("name") or file_id,
                             size=size, alloc=size,
                             mtime=_rfc3339_to_filetime(
                                 record.get("modifiedTime")),
                             attrs=DIR if is_folder else 0)
            for child_id in children.get(file_id, ()):
                queue.append((child_id, node))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
        store.build_child_lists()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)


def _drive_size(record: dict) -> int:
    """What the file costs the account, not what its content measures.

    `quotaBytesUsed` counts revisions and Docs-format overhead; `size` is the
    content length and is absent entirely for native Google formats.
    """
    for key in ("quotaBytesUsed", "size"):
        value = record.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 0


class SharePointTarget(ScanTarget):
    """SharePoint / OneDrive for Business through Microsoft Graph."""

    id = "sharepoint"
    display_name = "SharePoint (Microsoft Graph)"
    icon = "☁"
    file_ops = False
    form_labels = {"host": None, "port": None, "username": "Drive ID",
                   "password": "Access token", "root": None}
    required_fields = ("username", "password")

    GRAPH_ROOT = "https://graph.microsoft.com/v1.0"

    def __init__(self, credentials: Credentials | None = None, client=None) -> None:
        super().__init__(credentials)
        self._client = client
        self._owns_client = client is None

    @classmethod
    def is_available(cls):
        try:
            __import__("httpx")
        except ImportError:
            return False, ("httpx is not installed. "
                           "Install it with: pip install httpx")
        return True, ""

    def authenticate(self) -> None:
        if self._client is not None:
            return
        ok, why = self.is_available()
        if not ok:
            raise TargetError(why)
        import httpx

        token = self.credentials.password or self.credentials.extra.get("token")
        if not token:
            raise TargetError(
                "SharePoint needs an access token from your Entra ID app "
                "registration.")
        self._client = httpx.Client(
            base_url=self.GRAPH_ROOT,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30)

    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        self.authenticate()
        drive_id = (self.credentials.extra.get("drive_id")
                    or self.credentials.username)
        if not drive_id:
            raise TargetError("A drive id is required.")
        walker = _GraphWalker(self, self._client)
        self.errors = walker.errors
        return walker.walk(store, root, f"/drives/{drive_id}/root/children",
                           on_batch, should_cancel, wait_if_paused, batch_size)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:                       # noqa: BLE001
                pass
        self._client = None


class _GraphWalker(RemoteEnumerator):
    """One `children` request per folder, following `@odata.nextLink`."""

    def __init__(self, target, client) -> None:
        super().__init__(target)
        self._client = client

    def list_dir(self, url: str):
        while url:
            response = retry_on_throttle(lambda u=url: self._client.get(u))
            status = getattr(response, "status_code", 0)
            if status != 200:
                raise TargetError(f"{url} returned {status}")
            payload = response.json()
            for item in payload.get("value", ()) or ():
                is_dir = "folder" in item
                item_id = item.get("id") or ""
                yield (item.get("name") or item_id,
                       int(item.get("size") or 0),
                       is_dir,
                       _rfc3339_to_filetime(item.get("lastModifiedDateTime")),
                       # Graph addresses children by item id, never by path --
                       # this is what the walk's fifth element is for.
                       self._children_url(item_id))
            # A folder with more children than one page holds continues here
            # rather than at the caller: to the walk it is still one folder.
            url = payload.get("@odata.nextLink") or ""

    def _children_url(self, item_id: str) -> str:
        drive_id = (self.target.credentials.extra.get("drive_id")
                    or self.target.credentials.username)
        return f"/drives/{drive_id}/items/{item_id}/children"


register(S3Target)
register(AzureBlobTarget)
register(GoogleDriveTarget)
register(SharePointTarget)
