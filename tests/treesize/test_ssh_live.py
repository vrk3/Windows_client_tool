"""The SSH/SFTP backend against a REAL SFTP server, over a real socket.

Second of the five remote backends taken off the ledger's "never touched a
real service" list (WebDAV was the first). paramiko can act as a SERVER as
well as a client, so this stands one up in-process, serving a real directory,
and points the actual `SshTarget` at it.

What that covers which an injected client cannot: a real SSH transport and
key exchange, real password auth, the real `listdir_attr` round trip this
code relies on, and -- importantly -- the real host-key policy. The backend
uses `RejectPolicy`, deliberately, and that is a security property which would
silently regress if someone swapped in `AutoAddPolicy` to make a test pass.
"""
import os
import socket
import threading

import pytest

from modules.treesize.store.node_store import DIR, NodeStore
from modules.treesize.store.rollup import rollup
from modules.treesize.targets.base import Credentials, TargetError
from modules.treesize.targets.remote import SshTarget

paramiko = pytest.importorskip("paramiko")

USER, PASSWORD = "sftp-user", "sftp-pass"


def _host_key():
    """A throwaway host key. Ed25519 where available; RSA is the fallback."""
    for factory, bits in ((getattr(paramiko, "Ed25519Key", None), None),
                          (getattr(paramiko, "RSAKey", None), 2048)):
        if factory is None or not hasattr(factory, "generate"):
            continue
        try:
            return factory.generate() if bits is None else factory.generate(bits)
        except Exception:                           # noqa: BLE001
            continue
    pytest.skip("paramiko cannot generate a host key here")


class _Auth(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        if username == USER and password == PASSWORD:
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class _Sftp(paramiko.SFTPServerInterface):
    """Serves ROOT read-only. Only what a directory walk actually calls."""

    ROOT = ""

    def _real(self, path):
        cleaned = (path or "/").replace("\\", "/").lstrip("/")
        return os.path.join(self.ROOT, cleaned.replace("/", os.sep))

    def list_folder(self, path):
        target = self._real(path)
        try:
            out = []
            for name in os.listdir(target):
                attr = paramiko.SFTPAttributes.from_stat(
                    os.stat(os.path.join(target, name)))
                attr.filename = name
                out.append(attr)
            return out
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._real(path)))
        except OSError as exc:
            return paramiko.SFTPServer.convert_errno(exc.errno)

    lstat = stat


def _tree(root):
    os.makedirs(os.path.join(root, "docs", "nested"))
    os.makedirs(os.path.join(root, "empty"))
    with open(os.path.join(root, "top.bin"), "wb") as handle:
        handle.write(b"t" * 1000)
    with open(os.path.join(root, "docs", "a.txt"), "wb") as handle:
        handle.write(b"a" * 250)
    with open(os.path.join(root, "docs", "nested", "deep.dat"), "wb") as handle:
        handle.write(b"d" * 4000)
    with open(os.path.join(root, "docs", "sp ace & sign.txt"), "wb") as handle:
        handle.write(b"x" * 75)
    return 1000 + 250 + 4000 + 75


class _Server:
    def __init__(self, root_dir):
        self.key = _host_key()
        _Sftp.ROOT = root_dir
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self._running = True
        self._transports = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                conn, _addr = self.sock.accept()
            except OSError:
                return
            try:
                transport = paramiko.Transport(conn)
                transport.add_server_key(self.key)
                transport.set_subsystem_handler(
                    "sftp", paramiko.SFTPServer, _Sftp)
                transport.start_server(server=_Auth())
                self._transports.append(transport)
            except Exception:                       # noqa: BLE001
                try:
                    conn.close()
                except OSError:
                    pass

    def stop(self):
        self._running = False
        for transport in self._transports:
            try:
                transport.close()
            except Exception:                       # noqa: BLE001
                pass
        try:
            self.sock.close()
        except OSError:
            pass
        self._thread.join(5)


@pytest.fixture
def sftp(tmp_path, monkeypatch):
    served = tmp_path / "served"
    served.mkdir()
    total = _tree(str(served))
    server = _Server(str(served))

    # The backend calls load_system_host_keys() and then REJECTS anything
    # unknown. Standing in a known_hosts that trusts this throwaway key is how
    # a real user would have the host already known -- it does not weaken the
    # policy, which the next test checks is still in force.
    def _trust(self, filename=None):
        self.get_host_keys().add(f"[127.0.0.1]:{server.port}",
                                 server.key.get_name(), server.key)

    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys", _trust)
    try:
        yield server, total
    finally:
        server.stop()


def _scan(port, root="/", **kw):
    target = SshTarget(Credentials(host="127.0.0.1", port=port,
                                   username=USER, password=PASSWORD,
                                   root=root, **kw))
    store = NodeStore()
    node_root = store.add(-1, "sftp", attrs=DIR)
    try:
        target.enumerate(store, node_root)
    finally:
        target.close()
    store.build_child_lists()
    rollup(store)
    return store, node_root, target


# ---- the real thing -----------------------------------------------------

def test_it_walks_a_real_sftp_server_and_totals_match(sftp):
    """The number that matters: every byte the server is serving."""
    server, total = sftp
    store, root, _target = _scan(server.port)
    assert store.size[root] == total


def test_it_finds_every_file_and_folder(sftp):
    server, _total = sftp
    store, _root, _target = _scan(server.port)
    names = {store.name(i) for i in range(len(store))}
    assert {"top.bin", "a.txt", "deep.dat", "docs", "nested", "empty"} <= names


def test_an_awkward_filename_survives_the_protocol(sftp):
    server, _total = sftp
    store, _root, _target = _scan(server.port)
    assert "sp ace & sign.txt" in {store.name(i) for i in range(len(store))}


def test_directories_carry_no_size_of_their_own(sftp):
    """A directory's own st_size is filesystem bookkeeping, not content.
    Counting it inflates every folder on the volume."""
    server, total = sftp
    store, root, _target = _scan(server.port)
    docs = next(i for i in range(len(store)) if store.name(i) == "docs")
    # docs holds 250 + 4000 + 75 and nothing else.
    assert store.size[docs] == 4325
    assert store.size[root] == total


def test_timestamps_come_back_from_the_wire(sftp):
    server, _total = sftp
    store, _root, _target = _scan(server.port)
    node = next(i for i in range(len(store)) if store.name(i) == "top.bin")
    assert store.mtime[node] > 0


def test_an_empty_folder_is_stored_and_weighs_nothing(sftp):
    server, _total = sftp
    store, _root, _target = _scan(server.port)
    empty = next(i for i in range(len(store)) if store.name(i) == "empty")
    assert store.attrs[empty] & DIR and store.size[empty] == 0


# ---- auth and host keys -------------------------------------------------

def test_a_wrong_password_is_reported_not_silently_empty(sftp):
    """Authentication fails at CONNECT, before any walking, so unlike the
    per-directory failures this one really does raise."""
    server, _total = sftp
    with pytest.raises(TargetError, match="Could not connect"):
        target = SshTarget(Credentials(host="127.0.0.1", port=server.port,
                                       username=USER, password="wrong",
                                       root="/"))
        try:
            target.authenticate()
        finally:
            target.close()


def test_an_unknown_host_key_is_rejected(sftp, monkeypatch):
    """RejectPolicy is deliberate: AutoAddPolicy accepts an unknown host key
    silently, which defeats the point of host keys. Swapping it to make a
    connection test pass would be a silent security regression, so this
    asserts the refusal itself.
    """
    server, _total = sftp
    # Undo the fixture's trust: now the host really is unknown.
    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys",
                        lambda self, filename=None: None)
    target = SshTarget(Credentials(host="127.0.0.1", port=server.port,
                                   username=USER, password=PASSWORD, root="/"))
    with pytest.raises(TargetError, match="Could not connect"):
        try:
            target.authenticate()
        finally:
            target.close()


def test_the_policy_object_really_is_reject(monkeypatch):
    """Belt and braces, asserted on BEHAVIOUR rather than on source text.

    A first attempt at this grepped `authenticate` for "AutoAddPolicy" and
    failed on the comment that explains why it is not used -- which is what
    source-scanning tests are like. This captures the policy object actually
    handed to the client instead.
    """
    captured = []
    monkeypatch.setattr(paramiko.SSHClient, "set_missing_host_key_policy",
                        lambda self, policy: captured.append(policy))
    monkeypatch.setattr(paramiko.SSHClient, "load_system_host_keys",
                        lambda self, filename=None: None)

    target = SshTarget(Credentials(host="127.0.0.1", port=1, username="u",
                                   password="p", root="/"))
    with pytest.raises(TargetError):
        target.authenticate()          # nothing is listening on port 1

    assert captured, "no host-key policy was set at all"
    assert isinstance(captured[0], paramiko.RejectPolicy)
    assert not isinstance(captured[0], paramiko.AutoAddPolicy)
