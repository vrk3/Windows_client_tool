"""SSH and WebDAV scan targets (spec 6.2).

The two the spec says to build first, and the two that need no OAuth dance.

Both take an injectable client, so the tree-building, error handling and
cancellation are tested without a server — which is the part that actually
breaks. `paramiko` and `httpx` are optional: a missing one is reported by
`is_available()` so the UI can grey the target out rather than failing at the
moment someone tries to use it.
"""
import logging
import time
from xml.etree import ElementTree

from .base import (
    Credentials, FILETIME_EPOCH_OFFSET, FILETIME_TICKS_PER_SECOND,
    RemoteEnumerator, ScanTarget, TargetError, register, retry_on_throttle,
    unix_to_filetime,
)

logger = logging.getLogger(__name__)


class SshTarget(ScanTarget):
    id = "ssh"
    display_name = "SSH / SFTP"
    icon = "🔐"
    file_ops = False           # deleting over SFTP is a separate decision

    def __init__(self, credentials: Credentials | None = None, client=None) -> None:
        super().__init__(credentials)
        self._client = client
        self._sftp = client
        self._owns_client = client is None

    @classmethod
    def is_available(cls):
        try:
            __import__("paramiko")
        except ImportError:
            return False, ("paramiko is not installed. "
                           "Install it with: pip install paramiko")
        return True, ""

    def authenticate(self) -> None:
        if self._sftp is not None:
            return
        ok, why = self.is_available()
        if not ok:
            raise TargetError(why)
        import paramiko

        creds = self.credentials
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        # AutoAddPolicy accepts an unknown host key silently, which defeats the
        # point of host keys. RejectPolicy means an unknown host fails loudly
        # and the user decides, rather than the app deciding for them.
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(creds.host, port=creds.port or 22,
                           username=creds.username, password=creds.password or None,
                           timeout=20)
            self._sftp = client.open_sftp()
        except Exception as exc:                    # noqa: BLE001
            raise TargetError(f"Could not connect to {creds.host}: {exc}") from exc
        self._client = client

    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        self.authenticate()
        walker = _SftpWalker(self, self._sftp)
        self.errors = walker.errors
        return walker.walk(store, root, self.credentials.root or ".",
                           on_batch, should_cancel, wait_if_paused, batch_size)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:                       # noqa: BLE001
                logger.debug("close: cleanup failed while unwinding", exc_info=True)
                pass
        self._client = self._sftp = None


class _SftpWalker(RemoteEnumerator):
    def __init__(self, target, sftp) -> None:
        super().__init__(target)
        self._sftp = sftp

    def list_dir(self, path: str):
        import stat as stat_module
        for entry in self._sftp.listdir_attr(path):
            if entry.filename in (".", ".."):
                continue
            # listdir_attr gives size, mode and mtime in ONE round trip, which
            # is the whole reason to use it over listdir plus a stat each.
            is_dir = stat_module.S_ISDIR(entry.st_mode or 0)
            yield (entry.filename, int(entry.st_size or 0), is_dir,
                   unix_to_filetime(entry.st_mtime or 0))


class WebDavTarget(ScanTarget):
    id = "webdav"
    display_name = "WebDAV"
    icon = "🌐"
    file_ops = False
    form_labels = {"host": "Server URL", "port": None, "username": "User",
                   "password": "Password", "root": "Path"}

    DAV = "{DAV:}"
    PROPFIND_BODY = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:propfind xmlns:d="DAV:"><d:prop>'
        "<d:resourcetype/><d:getcontentlength/><d:getlastmodified/>"
        "</d:prop></d:propfind>"
    )

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

        creds = self.credentials
        auth = ((creds.username, creds.password)
                if creds.username else None)
        self._client = httpx.Client(base_url=creds.host, auth=auth, timeout=30)

    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        self.authenticate()
        walker = _WebDavWalker(self, self._client)
        self.errors = walker.errors
        return walker.walk(store, root, self.credentials.root or "/",
                           on_batch, should_cancel, wait_if_paused, batch_size)

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:                       # noqa: BLE001
                logger.debug("close: cleanup failed while unwinding", exc_info=True)
                pass
        self._client = None


class _WebDavWalker(RemoteEnumerator):
    def __init__(self, target, client) -> None:
        super().__init__(target)
        self._client = client
        #: Overridable so the tests do not actually wait out a backoff.
        self.sleep = time.sleep

    def _propfind(self, path: str):
        return self._client.request(
            "PROPFIND", path,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=WebDavTarget.PROPFIND_BODY)

    def list_dir(self, path: str):
        # Depth 1: one request per directory. Depth "infinity" is refused by
        # most servers and would stream the whole tree into memory on the ones
        # that allow it.
        # A shared WebDAV server throttles a whole-tree walk long before it
        # refuses one; retrying is the difference between a slow scan and a
        # tree full of holes (spec 6.2).
        response = retry_on_throttle(lambda: self._propfind(path),
                                     sleep=self.sleep)
        status = getattr(response, "status_code", 0)
        if status not in (207, 200):
            raise TargetError(f"PROPFIND {path} returned {status}")
        yield from self._parse(response.text, path)

    def _parse(self, xml: str, path: str):
        root = ElementTree.fromstring(xml)
        base = path.rstrip("/")
        for response in root.findall(f"{WebDavTarget.DAV}response"):
            href = response.findtext(f"{WebDavTarget.DAV}href") or ""
            name = href.rstrip("/").rsplit("/", 1)[-1]
            from urllib.parse import unquote
            name = unquote(name)
            # The collection itself is always the first entry of its own
            # listing; including it would make every folder its own child.
            if not name or href.rstrip("/").endswith(base.rstrip("/")) and \
                    href.rstrip("/") == base:
                continue
            props = response.find(
                f"{WebDavTarget.DAV}propstat/{WebDavTarget.DAV}prop")
            if props is None:
                continue
            is_dir = props.find(
                f"{WebDavTarget.DAV}resourcetype/"
                f"{WebDavTarget.DAV}collection") is not None
            size = int(props.findtext(
                f"{WebDavTarget.DAV}getcontentlength") or 0)
            yield name, size, is_dir, _http_date_to_filetime(
                props.findtext(f"{WebDavTarget.DAV}getlastmodified"))


def _http_date_to_filetime(value) -> int:
    if not value:
        return 0
    try:
        from email.utils import parsedate_to_datetime
        return unix_to_filetime(parsedate_to_datetime(value).timestamp())
    except (TypeError, ValueError):
        # A malformed date is not worth failing a scan over; the file still
        # has a size, which is what this tool is actually about.
        return 0


register(SshTarget)
register(WebDavTarget)
