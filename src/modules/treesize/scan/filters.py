"""Include/exclude rules applied during the scan pass.

Excluded nodes are never added to the store on the walk path, so an exclusion
costs nothing downstream -- no view, aggregate, or export has to know about it.
Excluding a directory therefore drops its whole subtree: the walk never descends
into a node it did not store. The MFT path cannot filter as it goes and prunes
the assembled tree instead; see prune.py.

The ``attrs`` argument is a *node* flag word from ``node_store``, not a raw
Win32 FILE_ATTRIBUTE_* word. The two overlap numerically (Win32 HIDDEN is 0x2,
which is node REPARSE) so mixing them silently filters the wrong entries.

Rules that need information the caller cannot supply are inert rather than
guessing. A path glob with no path, or an age rule with no timestamp, does not
fire -- silently dropping files on a rule that could not actually be evaluated
is the worst available behaviour for a tool that deletes things.
"""
import fnmatch
import threading
import time
from dataclasses import dataclass, field

from ..store.node_store import DIR, HIDDEN

# FILETIME counts 100-nanosecond ticks from 1601-01-01; Unix time counts
# seconds from 1970-01-01. 11,644,473,600 is the gap in seconds.
FILETIME_TICKS_PER_SECOND = 10_000_000
FILETIME_EPOCH_OFFSET_SECONDS = 11_644_473_600
SECONDS_PER_DAY = 24 * 60 * 60


def filetime_now() -> int:
    """Current time as a Windows FILETIME, to compare against node mtimes."""
    return int((time.time() + FILETIME_EPOCH_OFFSET_SECONDS)
               * FILETIME_TICKS_PER_SECOND)


def days_to_filetime(days: float) -> int:
    """A duration in days as FILETIME ticks. Not a point in time."""
    return int(days * SECONDS_PER_DAY * FILETIME_TICKS_PER_SECOND)


@dataclass
class FilterSet:
    exclude_globs: tuple[str, ...] = ()
    exclude_path_globs: tuple[str, ...] = ()
    min_size: int = 0
    max_size: int | None = None
    exclude_hidden: bool = False
    # Age is measured against `now`, captured once per FilterSet so that a long
    # scan cannot have entries near the threshold fall on different sides of it
    # depending on when they happened to be reached.
    min_age_days: float | None = None
    max_age_days: float | None = None
    now: int = field(default_factory=filetime_now)
    excluded_count: int = field(default=0, init=False)
    # `excluded_count += 1` is a read-modify-write. CPython's GIL makes it
    # safe today, but that does not survive a free-threaded build. The lock is
    # taken only on the exclusion branch, so the common path pays nothing.
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False,
                                  repr=False, compare=False)

    def reset(self) -> None:
        """Zero the running tally so one FilterSet can drive repeated scans."""
        with self._lock:
            self.excluded_count = 0

    def _matches_age(self, mtime: int) -> bool:
        if not mtime:
            return False            # no timestamp: the rule cannot be evaluated
        age = self.now - mtime
        if self.min_age_days is not None and age < days_to_filetime(self.min_age_days):
            return True
        if self.max_age_days is not None and age > days_to_filetime(self.max_age_days):
            return True
        return False

    def excludes(self, name: str, size: int, attrs: int, mtime: int = 0,
                 path: str | None = None) -> bool:
        hit = any(fnmatch.fnmatch(name.lower(), pattern.lower())
                  for pattern in self.exclude_globs)
        if not hit and self.exclude_path_globs and path:
            lowered = path.lower()
            hit = any(fnmatch.fnmatch(lowered, pattern.lower())
                      for pattern in self.exclude_path_globs)
        if not hit and self.exclude_hidden and (attrs & HIDDEN):
            hit = True
        # Size and age rules apply to files only. A folder's size is unknown
        # until its subtree is rolled up, and its timestamp says nothing about
        # what is inside it -- filtering either would drop the whole subtree on
        # evidence about the folder alone.
        if not hit and not (attrs & DIR):
            if size < self.min_size:
                hit = True
            elif self.max_size is not None and size > self.max_size:
                hit = True
            elif self._matches_age(mtime):
                hit = True
        if hit:
            with self._lock:
                self.excluded_count += 1
        return hit
