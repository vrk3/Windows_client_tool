"""Scan target interface (spec 6.1).

Every backend fills the same NodeStore, honouring the same batching, pause and
cancellation contract as the local scanner. **The store is the boundary**: once
a target has filled it, every view, aggregate, export and comparison works
without knowing which backend produced the data. That is the entire point of
the interface, and the reason `enumerate` returns nothing — its output is the
store, not a value.

Remote targets have no cluster geometry, so `alloc` is set equal to `size` and
the status bar omits the cluster field. Reporting a rounded-up allocation the
remote end never told us would be inventing data.
"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..store.node_store import DIR

#: What a service says when it wants us to slow down or come back later.
THROTTLE_STATUSES = (429, 503)

#: The Unix epoch in FILETIME terms, and its tick rate. Every remote gives a
#: Unix timestamp; every node in the store holds a Windows FILETIME.
FILETIME_EPOCH_OFFSET = 11_644_473_600
FILETIME_TICKS_PER_SECOND = 10_000_000


def unix_to_filetime(seconds: float) -> int:
    if not seconds or seconds < 0:
        return 0
    return int((seconds + FILETIME_EPOCH_OFFSET) * FILETIME_TICKS_PER_SECOND)


def retry_on_throttle(call, attempts: int = 5, base_delay: float = 0.5,
                      sleep=time.sleep):
    """Run `call()`, retrying while the service reports throttling (spec 6.2).

    Returns the LAST response rather than raising when the attempts run out.
    Every backend already turns a bad status into a per-directory error and
    keeps walking; raising here would end a whole scan over one busy folder.

    A `Retry-After` in seconds beats the doubling delay: the server knows when
    it will be ready and this end is only guessing.
    """
    delay = base_delay
    result = None
    for attempt in range(max(1, attempts)):
        result = call()
        if getattr(result, "status_code", None) not in THROTTLE_STATUSES:
            return result
        if attempt == attempts - 1:
            break
        sleep(_retry_after(result, delay))
        delay *= 2
    return result


def _retry_after(response, fallback: float) -> float:
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    try:
        # The HTTP-date form is also legal and is deliberately not honoured:
        # parsing it means trusting a remote clock against ours.
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return fallback


class TargetError(Exception):
    """Anything the user needs to be told about: auth, network, or config."""


@dataclass
class Credentials:
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    root: str = "/"
    extra: dict = field(default_factory=dict)


#: The connect dialog's fields, in the order it lays them out.
FORM_FIELDS = ("host", "port", "username", "password", "root")


class ScanTarget(ABC):
    id: str = ""
    display_name: str = ""
    icon: str = ""
    #: False for anything read-only or remote without a delete story.
    file_ops: bool = False

    #: What this backend calls each field of the connect dialog. Spec 6.1
    #: keeps ONE dialog for every backend -- "they differ in which fields
    #: matter, not in what a connection is" -- so the difference shows up
    #: here rather than in seven dialogs. A field mapped to None is not used
    #: by this backend and is hidden, because a Port box on an S3 connection
    #: is not a harmless extra: it invites a value that goes nowhere.
    form_labels: dict = {"host": "Host", "port": "Port", "username": "User",
                         "password": "Password", "root": "Path"}
    #: Fields without which the connection cannot even be attempted. Checked
    #: in the dialog so the refusal names the field, rather than surfacing as
    #: an SDK error three layers down.
    required_fields: tuple = ("host",)

    def __init__(self, credentials: Credentials | None = None) -> None:
        self.credentials = credentials or Credentials()

    @classmethod
    def is_available(cls) -> tuple[bool, str]:
        """(usable here, why not). Backends needing an optional package say so
        rather than failing at the moment someone tries to scan."""
        return True, ""

    def authenticate(self) -> None:
        """Establish a session. Raises TargetError with something readable."""

    @abstractmethod
    def enumerate(self, store, root: int, on_batch=None, should_cancel=None,
                  wait_if_paused=None, batch_size: int = 500) -> int:
        """Fill `store` beneath `root`. Returns the node count."""

    def supports_file_ops(self) -> bool:
        return self.file_ops

    def open_stream(self, node_path: str):
        raise TargetError(
            f"{self.display_name} cannot open file contents.")

    def close(self) -> None:
        """Release any session. Safe to call more than once."""


class RemoteEnumerator:
    """Shared walk for targets that list one directory at a time.

    Breadth-first, so a node's parent always exists when the node is added --
    the same reason the local walk scanner goes breadth-first. Subclasses
    supply `list_dir`; everything about batching, cancellation and pausing
    lives here once instead of in every backend.
    """

    def __init__(self, target: ScanTarget) -> None:
        self.target = target
        self.errors: list[tuple[str, str]] = []
        self.error_count = 0

    def list_dir(self, path: str):
        """Yield (name, size, is_dir, mtime) for one directory."""
        raise NotImplementedError

    def record_error(self, path: str, why: str) -> None:
        self.error_count += 1
        if len(self.errors) < 100:
            self.errors.append((path, why))

    def walk(self, store, root: int, root_path: str, on_batch=None,
             should_cancel=None, wait_if_paused=None,
             batch_size: int = 500) -> int:
        from collections import deque

        queue = deque([(root, root_path)])
        batch_start = len(store)
        while queue:
            if wait_if_paused:
                wait_if_paused()
            if should_cancel and should_cancel():
                break
            node, path = queue.popleft()
            try:
                entries = list(self.list_dir(path))
            except Exception as exc:                # noqa: BLE001
                # One unreadable directory must not end a remote scan; the
                # error is recorded and the walk continues, exactly as the
                # local walker treats an access-denied folder.
                self.record_error(path, str(exc))
                continue
            for entry in entries:
                # A fifth element is the key to descend by, for backends whose
                # children are addressed by an opaque id rather than by a path
                # (Graph does this). Four elements means the path is the name
                # joined onto its parent, which is the SSH and WebDAV case.
                name, size, is_dir, mtime = entry[:4]
                child_key = entry[4] if len(entry) > 4 else None
                attrs = DIR if is_dir else 0
                child = store.add(node, name, size=0 if is_dir else size,
                                  # No cluster geometry remotely, so allocated
                                  # equals real size rather than a guess.
                                  alloc=0 if is_dir else size,
                                  mtime=mtime, attrs=attrs)
                if is_dir:
                    queue.append(
                        (child, child_key if child_key is not None
                         else _join(path, name)))
            if on_batch and len(store) - batch_start >= batch_size:
                on_batch((batch_start, len(store)))
                batch_start = len(store)
        store.build_child_lists()
        if on_batch and len(store) > batch_start:
            on_batch((batch_start, len(store)))
        return len(store)


def _join(path: str, name: str) -> str:
    """POSIX-style join: remote targets are not Windows paths."""
    return (path.rstrip("/") + "/" + name) if path else name


class PrefixTreeBuilder:
    """Synthesize a folder tree from flat object keys (spec 6.2).

    S3 and Azure Blob have no folders at all: "a/b/c.txt" is one key whose
    slashes mean nothing to the service. Every view in this pane is a tree, so
    the slashes are given their conventional meaning here, once, instead of in
    each backend.

    Folders are created on first sight and reused after, which is what keeps a
    million keys under one prefix from producing a million copies of it.
    """

    def __init__(self, store, root: int) -> None:
        self._store = store
        self._root = root
        self._folders: dict[str, int] = {"": root}
        self._files: set[str] = set()

    def add(self, key: str, size: int, mtime: int = 0) -> None:
        if not key or key.endswith("/"):
            # A zero-byte key ending in "/" is a console's way of drawing an
            # empty folder. It is not a file, and naming a node after it gives
            # every such folder a nameless 0-byte child.
            if key:
                self._folder_for(key.rstrip("/"))
            return
        if key in self._files:
            return
        self._files.add(key)
        head, _, name = key.rpartition("/")
        parent = self._folder_for(head) if head else self._root
        self._store.add(parent, name, size=size,
                        # No cluster geometry in an object store; reporting a
                        # rounded-up allocation would be inventing a number.
                        alloc=size, mtime=mtime)

    def _folder_for(self, prefix: str) -> int:
        if not prefix:
            return self._root
        existing = self._folders.get(prefix)
        if existing is not None:
            return existing
        head, _, name = prefix.rpartition("/")
        parent = self._folder_for(head) if head else self._root
        node = self._store.add(parent, name, size=0, alloc=0, attrs=DIR)
        self._folders[prefix] = node
        return node

    def finish(self) -> int:
        self._store.build_child_lists()
        return len(self._store)


_REGISTRY: dict = {}


def register(target_class) -> None:
    _REGISTRY[target_class.id] = target_class


def available_targets() -> list:
    """Every registered target, with whether this machine can use it."""
    return [(cls, *cls.is_available()) for cls in _REGISTRY.values()]


def get_target(target_id: str):
    return _REGISTRY.get(target_id)
