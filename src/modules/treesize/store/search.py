"""File search over an already-scanned store (spec 8.1).

Pro ships this as a separate application; here it is a query over the same
store. One linear pass over the arrays, so results are effectively instant on a
volume that has already been scanned — the expensive part happened during the
scan, and re-walking the disk to find a filename would throw that away.

No Qt, so the matching rules are testable without a display.
"""
import fnmatch
import re
from dataclasses import dataclass, field

from .node_store import DIR, EXCLUDED, HARDLINK_DUP, HIDDEN

FILETIME_TICKS_PER_DAY = 24 * 60 * 60 * 10_000_000


@dataclass
class Query:
    """What to look for. Every field is optional; an empty query matches all."""
    pattern: str = ""
    regex: bool = False
    min_size: int = 0
    max_size: int | None = None
    newer_than_days: float | None = None
    older_than_days: float | None = None
    owner: str = ""
    include_files: bool = True
    include_folders: bool = False
    include_hidden: bool = True
    limit: int = 5000
    _compiled: object = field(default=None, init=False, repr=False)

    def matcher(self):
        """Return a predicate over a name, compiled once per query.

        A bad regular expression is a user typo, not a crash: it falls back to
        a literal substring match so the search still answers something.
        """
        if not self.pattern:
            return lambda name: True
        if self.regex:
            try:
                compiled = re.compile(self.pattern, re.IGNORECASE)
            except re.error:
                needle = self.pattern.lower()
                return lambda name: needle in name.lower()
            return lambda name: compiled.search(name) is not None
        pattern = self.pattern.lower()
        # A pattern with no wildcard is treated as "contains", which is what
        # people mean when they type "invoice" into a search box.
        if not any(c in pattern for c in "*?["):
            return lambda name: pattern in name.lower()
        return lambda name: fnmatch.fnmatch(name.lower(), pattern)


@dataclass(frozen=True)
class Hit:
    node: int
    name: str
    size: int
    is_dir: bool


def search(store, root: int, query: Query, now: int | None = None) -> list[Hit]:
    """Every node under `root` matching `query`, largest first.

    Sorted by size because the reason to search a disk-space tool is almost
    always "find the big thing called X", not "find them alphabetically".
    """
    if store is None or root < 0 or not len(store):
        return []
    if now is None:
        from ..scan.filters import filetime_now
        now = filetime_now()

    matches_name = query.matcher()
    hits: list[Hit] = []
    stack = [root]
    while stack:
        node = stack.pop()
        attrs = store.attrs[node]
        if attrs & EXCLUDED:
            continue
        is_dir = bool(attrs & DIR)
        if is_dir:
            stack.extend(store.children(node))
        if node == root:
            continue
        if attrs & HARDLINK_DUP:
            continue                    # another name for a file already seen
        if is_dir and not query.include_folders:
            continue
        if not is_dir and not query.include_files:
            continue
        if not query.include_hidden and (attrs & HIDDEN):
            continue

        size = store.size[node]
        if size < query.min_size:
            continue
        if query.max_size is not None and size > query.max_size:
            continue
        if not _matches_age(store.mtime[node], now, query):
            continue
        if query.owner:
            owner = store.owner(store.owner_id[node]) or ""
            if query.owner.lower() not in owner.lower():
                continue
        if not matches_name(store.name(node)):
            continue

        hits.append(Hit(node, store.name(node), size, is_dir))

    hits.sort(key=lambda h: h.size, reverse=True)
    return hits[:query.limit] if query.limit else hits


def _matches_age(mtime: int, now: int, query: Query) -> bool:
    if query.newer_than_days is None and query.older_than_days is None:
        return True
    if not mtime:
        return False                    # no timestamp: an age rule cannot pass
    age_days = (now - mtime) / FILETIME_TICKS_PER_DAY
    if query.newer_than_days is not None and age_days > query.newer_than_days:
        return False
    if query.older_than_days is not None and age_days < query.older_than_days:
        return False
    return True
