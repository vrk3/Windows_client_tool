"""Duplicate finder (spec 8.2).

Three passes, each cheaper than the one it protects:

1. Group by SIZE, from the store. No I/O at all.
2. Within each same-size group, hash the leading 64 KB to split it.
3. Hash in full with BLAKE2b, only for whatever still collides.

**A file is never hashed unless another file shares its exact size**, which
eliminates the overwhelming majority of the I/O on a real volume — most files
are a unique length and can be ruled out for free.

Progress and cancel are callbacks, so this runs on a worker without knowing
anything about Qt.
"""
import hashlib
from collections import defaultdict
from dataclasses import dataclass

from .node_store import DIR, EXCLUDED, HARDLINK_DUP

HEAD_BYTES = 64 * 1024
CHUNK = 1024 * 1024


@dataclass(frozen=True)
class DuplicateGroup:
    digest: str
    size: int
    paths: tuple

    @property
    def count(self) -> int:
        return len(self.paths)

    @property
    def wasted(self) -> int:
        """Space recoverable by keeping one copy."""
        return self.size * (self.count - 1)


def candidates_by_size(store, root: int, min_size: int = 1) -> dict:
    """size -> [node], for sizes shared by two or more files.

    Hard-link duplicates are excluded: they already share their bytes on disk,
    so reporting them as duplicates would offer to free space that does not
    exist.
    """
    by_size = defaultdict(list)
    stack = [root]
    while stack:
        node = stack.pop()
        attrs = store.attrs[node]
        if attrs & EXCLUDED:
            continue
        if attrs & DIR:
            stack.extend(store.children(node))
            continue
        if attrs & HARDLINK_DUP:
            continue
        size = store.size[node]
        if size >= min_size:
            by_size[size].append(node)
    return {size: nodes for size, nodes in by_size.items() if len(nodes) > 1}


def _hash_file(path: str, limit: int | None = None) -> str | None:
    """BLAKE2b of a file, or of its first `limit` bytes. None if unreadable."""
    digest = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as handle:
            if limit is not None:
                digest.update(handle.read(limit))
            else:
                while True:
                    block = handle.read(CHUNK)
                    if not block:
                        break
                    digest.update(block)
    except OSError:
        # Locked, denied, or gone since the scan. Skipping it is right: a file
        # that cannot be read cannot be confirmed as a duplicate, and guessing
        # would put it on a list people delete from.
        return None
    return digest.hexdigest()


def find_duplicates(store, root: int, min_size: int = 1,
                    on_progress=None, should_cancel=None,
                    hasher=_hash_file) -> list:
    """Groups of files with identical content, most wasted space first."""
    groups = candidates_by_size(store, root, min_size)
    total = sum(len(nodes) for nodes in groups.values())
    done = 0
    results: list[DuplicateGroup] = []

    for size, nodes in groups.items():
        if should_cancel and should_cancel():
            break
        paths = [store.path(node) for node in nodes]

        # Pass 2: the head is enough to separate most same-size files, and
        # costs one seek each rather than reading whole files.
        by_head = defaultdict(list)
        for path in paths:
            if should_cancel and should_cancel():
                return _sorted(results)
            digest = hasher(path, HEAD_BYTES)
            done += 1
            if on_progress and total:
                on_progress(int(done * 100 / total))
            if digest is not None:
                by_head[digest].append(path)

        # Pass 3: only whatever still collides gets read in full.
        for head_digest, same_head in by_head.items():
            if len(same_head) < 2:
                continue
            if size <= HEAD_BYTES:
                # Already hashed in full by the head pass; reading again would
                # be pure waste.
                results.append(DuplicateGroup(head_digest, size,
                                              tuple(same_head)))
                continue
            by_full = defaultdict(list)
            for path in same_head:
                if should_cancel and should_cancel():
                    return _sorted(results)
                digest = hasher(path, None)
                if digest is not None:
                    by_full[digest].append(path)
            for digest, identical in by_full.items():
                if len(identical) > 1:
                    results.append(DuplicateGroup(digest, size,
                                                  tuple(identical)))
    return _sorted(results)


def _sorted(groups) -> list:
    return sorted(groups, key=lambda g: g.wasted, reverse=True)


def keep_one(group: DuplicateGroup) -> tuple:
    """The paths to remove if one copy is kept.

    Keeps the SHORTEST path, which is usually the original rather than a copy
    buried in a backup folder. It is a heuristic and the UI must let it be
    overridden, but it beats keeping whichever happened to be scanned first.
    """
    if group.count < 2:
        return ()
    keeper = min(group.paths, key=lambda p: (len(p), p.lower()))
    return tuple(p for p in group.paths if p != keeper)
