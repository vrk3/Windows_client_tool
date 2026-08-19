"""Include/exclude rules applied during the scan pass.

Excluded nodes are never added to the store, so an exclusion costs nothing
downstream -- no view, aggregate, or export has to know about it. Excluding a
directory therefore drops its whole subtree: the walk never descends into a
node it did not store.

The ``attrs`` argument is a *node* flag word from ``node_store``, not a raw
Win32 FILE_ATTRIBUTE_* word. The two overlap numerically (Win32 HIDDEN is 0x2,
which is node REPARSE) so mixing them silently filters the wrong entries.
"""
import fnmatch
import threading
from dataclasses import dataclass, field

from ..store.node_store import DIR, HIDDEN


@dataclass
class FilterSet:
    exclude_globs: tuple[str, ...] = ()
    min_size: int = 0
    max_size: int | None = None
    exclude_hidden: bool = False
    excluded_count: int = field(default=0, init=False)
    # `excluded_count += 1` is a read-modify-write. CPython's GIL makes it
    # safe today -- a 10-thread test could not lose an update -- but the walk
    # scanner is meant to be threaded (deferred out of phase 1) and that
    # guarantee does not survive a free-threaded build. The lock is taken only
    # on the exclusion branch, so the common path pays nothing.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False,
                                  repr=False, compare=False)

    def reset(self) -> None:
        """Zero the running tally so one FilterSet can drive repeated scans."""
        with self._lock:
            self.excluded_count = 0

    def excludes(self, name: str, size: int, attrs: int) -> bool:
        lowered = name.lower()
        hit = any(fnmatch.fnmatch(lowered, pattern.lower())
                  for pattern in self.exclude_globs)
        if not hit and self.exclude_hidden and (attrs & HIDDEN):
            hit = True
        # Size rules apply to files only: a folder's size is unknown until
        # its subtree is rolled up, so filtering on it here would be wrong.
        if not hit and not (attrs & DIR):
            if size < self.min_size:
                hit = True
            elif self.max_size is not None and size > self.max_size:
                hit = True
        if hit:
            with self._lock:
                self.excluded_count += 1
        return hit
