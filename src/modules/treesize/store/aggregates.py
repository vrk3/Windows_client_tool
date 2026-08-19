"""Per-view aggregates over a subtree (spec 4.3).

Each right-panel view is one linear pass over the arrays, restricted to a
subtree by walking the child lists once and recording the index set. No view
builds its own traversal, so a subtree is walked once per navigation rather
than once per view.

Results are cached per (node, mode) so moving up and back down the tree does
not recompute. The cache is keyed by scan identity too -- a new scan must not
serve stale numbers for the same node index, which would be silent and wrong.
"""
import heapq
from collections import defaultdict
from dataclasses import dataclass

from .node_store import DIR, EXCLUDED, HARDLINK_DUP

# Pro's file groups. A file lands in the first group whose extension list
# claims it; anything unclaimed is "Other".
FILE_GROUPS: tuple[tuple[str, frozenset[str]], ...] = (
    ("Documents", frozenset({"doc", "docx", "pdf", "rtf", "txt", "odt", "xls",
                             "xlsx", "ppt", "pptx", "csv", "md"})),
    ("Pictures", frozenset({"jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff",
                            "webp", "heic", "raw", "svg", "ico"})),
    ("Music", frozenset({"mp3", "flac", "wav", "aac", "ogg", "wma", "m4a"})),
    ("Videos", frozenset({"mp4", "mkv", "avi", "mov", "wmv", "flv", "webm",
                          "m4v", "mpg", "mpeg"})),
    ("Archives", frozenset({"zip", "rar", "7z", "gz", "bz2", "xz", "tar",
                            "cab", "iso", "wim"})),
    ("Programs", frozenset({"exe", "dll", "sys", "msi", "com", "bat", "cmd",
                            "ps1", "so", "ocx", "drv"})),
    ("Temporary", frozenset({"tmp", "temp", "bak", "old", "log", "dmp",
                             "chk", "cache"})),
)
_GROUP_OF = {ext: name for name, extensions in FILE_GROUPS for ext in extensions}

# Pro's default Age of Files buckets, in days. The last is open-ended.
AGE_BUCKETS: tuple[tuple[str, float | None], ...] = (
    ("Today", 1), ("This week", 7), ("This month", 30),
    ("Last 6 months", 182), ("This year", 365), ("Older", None),
)

FILETIME_TICKS_PER_DAY = 24 * 60 * 60 * 10_000_000


@dataclass(frozen=True)
class Row:
    """One line in an aggregate view."""
    label: str
    count: int
    size: int
    alloc: int


def extension_of(name: str) -> str:
    """Lowercase extension without the dot, or "" when there is none.

    A leading dot is a whole name, not an extension: ".gitignore" has no
    extension, which is what Pro shows.
    """
    dot = name.rfind(".")
    if dot <= 0 or dot == len(name) - 1:
        return ""
    return name[dot + 1:].lower()


def subtree_files(store, root: int):
    """Yield every non-excluded FILE node beneath root, root included.

    Iterative, because a deep tree would otherwise overflow the stack -- the
    same reason rollup is iterative. Hardlink duplicates are skipped: they
    carry no size and counting them would inflate every view at once.
    """
    stack = [root]
    while stack:
        node = stack.pop()
        attrs = store.attrs[node]
        if attrs & EXCLUDED:
            continue
        if attrs & DIR:
            stack.extend(store.children(node))
        elif not (attrs & HARDLINK_DUP):
            yield node


def by_extension(store, root: int) -> list[Row]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for node in subtree_files(store, root):
        entry = counts[extension_of(store.name(node)) or "(no extension)"]
        entry[0] += 1
        entry[1] += store.size[node]
        entry[2] += store.alloc[node]
    return _sorted_rows(counts)


def by_file_group(store, root: int) -> list[Row]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for node in subtree_files(store, root):
        group = _GROUP_OF.get(extension_of(store.name(node)), "Other")
        entry = counts[group]
        entry[0] += 1
        entry[1] += store.size[node]
        entry[2] += store.alloc[node]
    return _sorted_rows(counts)


def by_owner(store, root: int) -> list[Row]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for node in subtree_files(store, root):
        owner = store.owner(store.owner_id[node]) or "(unknown)"
        entry = counts[owner]
        entry[0] += 1
        entry[1] += store.size[node]
        entry[2] += store.alloc[node]
    return _sorted_rows(counts)


def by_age(store, root: int, now: int, buckets=AGE_BUCKETS) -> list[Row]:
    """Histogram over modification time. Bucket order is chronological.

    Unlike the other views this is NOT sorted by size: an age histogram whose
    buckets jump around is unreadable.
    """
    counts: dict[str, list[int]] = {label: [0, 0, 0] for label, _ in buckets}
    for node in subtree_files(store, root):
        mtime = store.mtime[node]
        age_days = (now - mtime) / FILETIME_TICKS_PER_DAY if mtime else None
        entry = counts[_bucket_for(age_days, buckets)]
        entry[0] += 1
        entry[1] += store.size[node]
        entry[2] += store.alloc[node]
    return [Row(label, *counts[label]) for label, _ in buckets]


def _bucket_for(age_days, buckets) -> str:
    if age_days is None or age_days < 0:
        # No timestamp, or a stamp in the future. Both are "unknown age", and
        # the oldest bucket is where Pro puts them rather than inventing one.
        return buckets[-1][0]
    for label, limit in buckets:
        if limit is None or age_days < limit:
            return label
    return buckets[-1][0]


def top_files(store, root: int, limit: int = 100) -> list[tuple[int, int]]:
    """The `limit` largest files as (node, size), biggest first.

    A bounded heap, not a full sort: a whole-volume subtree is 400k+ files and
    only the top hundred are ever shown.
    """
    heap: list[tuple[int, int]] = []
    for node in subtree_files(store, root):
        size = store.size[node]
        if len(heap) < limit:
            heapq.heappush(heap, (size, node))
        elif size > heap[0][0]:
            heapq.heapreplace(heap, (size, node))
    return [(node, size) for size, node in sorted(heap, reverse=True)]


def _sorted_rows(counts) -> list[Row]:
    rows = [Row(label, c, s, a) for label, (c, s, a) in counts.items()]
    rows.sort(key=lambda r: r.size, reverse=True)
    return rows


class AggregateCache:
    """Memoises aggregates per (scan, node).

    Keyed on `id(store)` AND the node: reusing a node index across scans would
    otherwise serve last scan's numbers for this scan's folder, which is both
    wrong and completely silent.
    """

    def __init__(self) -> None:
        self._store_id = None
        self._cache: dict[tuple[str, int], object] = {}

    def get(self, store, root: int, name: str, compute):
        if store is None:
            return None
        if id(store) != self._store_id:
            self._store_id = id(store)
            self._cache.clear()
        key = (name, root)
        if key not in self._cache:
            self._cache[key] = compute(store, root)
        return self._cache[key]

    def clear(self) -> None:
        self._store_id = None
        self._cache.clear()
