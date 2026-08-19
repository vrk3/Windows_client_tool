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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


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


class ScanTarget(ABC):
    id: str = ""
    display_name: str = ""
    icon: str = ""
    #: False for anything read-only or remote without a delete story.
    file_ops: bool = False

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
        from ..store.node_store import DIR

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
            for name, size, is_dir, mtime in entries:
                attrs = DIR if is_dir else 0
                child = store.add(node, name, size=0 if is_dir else size,
                                  # No cluster geometry remotely, so allocated
                                  # equals real size rather than a guess.
                                  alloc=0 if is_dir else size,
                                  mtime=mtime, attrs=attrs)
                if is_dir:
                    queue.append((child, _join(path, name)))
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


_REGISTRY: dict = {}


def register(target_class) -> None:
    _REGISTRY[target_class.id] = target_class


def available_targets() -> list:
    """Every registered target, with whether this machine can use it."""
    return [(cls, *cls.is_available()) for cls in _REGISTRY.values()]


def get_target(target_id: str):
    return _REGISTRY.get(target_id)
