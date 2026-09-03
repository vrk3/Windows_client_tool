"""The WebDAV backend against a REAL WebDAV server, over a real socket.

The ledger's standing caveat is that no remote backend has ever touched a real
service -- every one is tested against an injected client. WebDAV is plain
HTTP, so that caveat is fixable here rather than owed to the user: this file
stands up a small PROPFIND server over stdlib `http.server`, points the actual
`WebDavTarget` at it, and checks the store it builds against the directory on
disk that the server is serving.

What that covers which an injected client cannot: the real httpx client, real
Basic auth, the real PROPFIND request this code sends, real XML off a socket,
real URL quoting of awkward names, and the real 429 back-off path.
"""
import base64
import os
import threading
import urllib.parse
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from modules.treesize.store.node_store import DIR, NodeStore
from modules.treesize.store.rollup import rollup
from modules.treesize.targets.base import Credentials
from modules.treesize.targets.remote import WebDavTarget

pytest.importorskip("httpx")

USER, PASSWORD = "dav-user", "dav-pass"


class _DavHandler(BaseHTTPRequestHandler):
    """Just enough WebDAV to answer a Depth-1 PROPFIND from a real directory."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    # -- helpers ------------------------------------------------------------

    def _authorised(self) -> bool:
        if not self.server.require_auth:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        raw = base64.b64decode(header[6:]).decode("utf-8", "replace")
        return raw == f"{USER}:{PASSWORD}"

    def _send(self, status, body=b"", headers=()):
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _local_path(self, url_path: str) -> str:
        rel = urllib.parse.unquote(url_path).strip("/")
        return os.path.join(self.server.root_dir, rel.replace("/", os.sep))

    # -- PROPFIND -----------------------------------------------------------

    def do_PROPFIND(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)

        self.server.seen.append(("PROPFIND", self.path,
                                 self.headers.get("Depth")))

        if not self._authorised():
            self._send(401, b"", [("WWW-Authenticate", 'Basic realm="dav"')])
            return

        # Throttle the first N calls, so the real retry_on_throttle path runs.
        if self.server.throttle_left > 0:
            self.server.throttle_left -= 1
            self._send(429, b"busy", [("Retry-After", "0")])
            return

        local = self._local_path(self.path)
        if not os.path.exists(local):
            self._send(404)
            return

        entries = [(self.path, local, True)]
        if os.path.isdir(local) and self.headers.get("Depth") == "1":
            for name in sorted(os.listdir(local)):
                child = os.path.join(local, name)
                href = (self.path.rstrip("/") + "/"
                        + urllib.parse.quote(name))
                entries.append((href, child, os.path.isdir(child)))

        parts = ['<?xml version="1.0" encoding="utf-8"?>',
                 '<d:multistatus xmlns:d="DAV:">']
        for href, path, is_dir in entries:
            if is_dir:
                kind = "<d:collection/>"
                size = ""
            else:
                kind = ""
                size = (f"<d:getcontentlength>{os.path.getsize(path)}"
                        f"</d:getcontentlength>")
            modified = formatdate(os.path.getmtime(path), usegmt=True)
            parts.append(
                f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
                f"<d:resourcetype>{kind}</d:resourcetype>{size}"
                f"<d:getlastmodified>{modified}</d:getlastmodified>"
                f"</d:prop><d:status>HTTP/1.1 200 OK</d:status>"
                f"</d:propstat></d:response>")
        parts.append("</d:multistatus>")
        self._send(207, "".join(parts).encode("utf-8"),
                   [("Content-Type", "application/xml; charset=utf-8")])


def _tree(root):
    """A directory whose byte totals are known exactly."""
    os.makedirs(os.path.join(root, "docs", "nested"))
    os.makedirs(os.path.join(root, "empty"))
    with open(os.path.join(root, "top.bin"), "wb") as handle:
        handle.write(b"t" * 1000)
    with open(os.path.join(root, "docs", "a.txt"), "wb") as handle:
        handle.write(b"a" * 250)
    with open(os.path.join(root, "docs", "nested", "deep.dat"), "wb") as handle:
        handle.write(b"d" * 4000)
    # A name that MUST survive URL quoting on the wire and come back intact.
    with open(os.path.join(root, "docs", "a file & sign.txt"), "wb") as handle:
        handle.write(b"x" * 75)
    return 1000 + 250 + 4000 + 75


@pytest.fixture
def dav(tmp_path):
    total = _tree(str(tmp_path))
    server = HTTPServer(("127.0.0.1", 0), _DavHandler)
    server.root_dir = str(tmp_path)
    server.seen = []
    server.throttle_left = 0
    server.require_auth = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, f"http://127.0.0.1:{server.server_port}", total
    finally:
        server.shutdown()
        thread.join(5)
        server.server_close()


def _scan(base_url, **cred_kwargs):
    target = WebDavTarget(Credentials(host=base_url, root="/", **cred_kwargs))
    store = NodeStore()
    root = store.add(-1, base_url, attrs=DIR)
    try:
        target.enumerate(store, root)
    finally:
        target.close()
    store.build_child_lists()
    rollup(store)
    return store, root, target


# ---- the real thing -----------------------------------------------------

def test_it_walks_a_real_server_and_totals_match_the_disk(dav):
    """The number that matters. Every byte the server is serving, and no
    others -- the failure this project keeps hitting is a plausible total."""
    _server, base, total = dav
    store, root, _target = _scan(base)
    assert store.size[root] == total


def test_it_finds_every_file_and_folder(dav):
    _server, base, _total = dav
    store, root, _target = _scan(base)
    names = {store.name(i) for i in range(len(store))}
    assert {"top.bin", "a.txt", "deep.dat", "docs", "nested", "empty"} <= names


def test_a_folder_is_not_listed_inside_itself(dav):
    """The collection is always the first entry of its own PROPFIND. Counting
    it makes every folder its own child and the tree recurse forever."""
    _server, base, _total = dav
    store, root, _target = _scan(base)
    docs = next(i for i in range(len(store)) if store.name(i) == "docs")
    assert "docs" not in {store.name(c) for c in store.children(docs)}


def test_a_quoted_name_survives_the_round_trip(dav):
    """"a file & sign.txt" is quoted on the wire and must come back intact --
    a mangled name is a file the user cannot then act on."""
    _server, base, _total = dav
    store, root, _target = _scan(base)
    assert "a file & sign.txt" in {store.name(i) for i in range(len(store))}


def test_it_descends_with_one_request_per_directory(dav):
    """Depth 1, per spec 6.2. Depth infinity is refused by most servers and
    streams a whole tree into memory on the rest."""
    server, base, _total = dav
    _scan(base)
    depths = {depth for _method, _path, depth in server.seen}
    assert depths == {"1"}
    # root, docs, nested, empty -- and nothing twice.
    assert len(server.seen) == 4


def test_an_empty_folder_is_stored_and_weighs_nothing(dav):
    _server, base, _total = dav
    store, root, _target = _scan(base)
    empty = next(i for i in range(len(store)) if store.name(i) == "empty")
    assert store.attrs[empty] & DIR
    assert store.size[empty] == 0


def test_timestamps_come_back_from_the_wire(dav):
    """getlastmodified is an HTTP date; a zero here means the parse failed."""
    _server, base, _total = dav
    store, root, _target = _scan(base)
    node = next(i for i in range(len(store)) if store.name(i) == "top.bin")
    assert store.mtime[node] > 0


# ---- auth ---------------------------------------------------------------

def test_basic_auth_is_actually_sent(dav):
    server, base, total = dav
    server.require_auth = True
    store, root, _target = _scan(base, username=USER, password=PASSWORD)
    assert store.size[root] == total


def test_a_wrong_password_is_recorded_not_silently_empty(dav):
    """An empty tree and a refused login look identical from the outside, and
    reporting a whole drive as 0 bytes is the worse of the two.

    It does NOT raise, and that is deliberate: `walk` records a per-directory
    failure and keeps going, because one unreadable folder must not end a
    remote scan. The safety property is therefore that the 401 is RECORDED --
    the shell turns a non-empty `errors` into `complete = False` and the
    status bar says INCOMPLETE, which is what stops a 0-byte total being read
    as a measurement.
    """
    server, base, _total = dav
    server.require_auth = True
    target = WebDavTarget(Credentials(host=base, root="/",
                                      username=USER, password="wrong"))
    store = NodeStore()
    root = store.add(-1, base, attrs=DIR)
    try:
        target.enumerate(store, root)
    finally:
        target.close()

    assert store.size[root] == 0
    assert target.errors, "a refused login produced a silent empty scan"
    assert "401" in target.errors[0][1]


# ---- throttling ---------------------------------------------------------

def test_a_429_is_retried_and_the_scan_still_completes(dav):
    """Spec 6.2's back-off, against a server really returning 429. A shared
    WebDAV server throttles a whole-tree walk long before it refuses one;
    retrying is the difference between a slow scan and a tree full of holes."""
    server, base, total = dav
    server.throttle_left = 3

    target = WebDavTarget(Credentials(host=base, root="/"))
    store = NodeStore()
    root = store.add(-1, base, attrs=DIR)
    try:
        target.enumerate(store, root)
    finally:
        target.close()
    store.build_child_lists()
    rollup(store)

    assert store.size[root] == total, "the scan lost data to throttling"
    assert len(server.seen) > 4, "nothing was actually retried"
