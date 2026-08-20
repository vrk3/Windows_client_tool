"""Shared bounded thread pool for long-running background operations —
DISM component-store cleanup/analyze, "Compact WinSxS", WU deep clean, and
similar multi-minute subprocess calls.

`QThreadPool.globalInstance()` is what nearly every module uses for quick
scans/refreshes (`App.thread_pool` is that same instance — see app.py). Its
max thread count defaults to the CPU core count, and it's shared by the
entire app. A single 10-30 minute DISM run occupying one of those slots is
fine; several of them (or one plus a burst of "Scan All" workers on a
low-core machine) can eat into the slots everything else is waiting on,
making unrelated tabs feel hung. Routing long ops through a small pool of
their own keeps that contention out of the shared pool.

Module-level singleton (mirrors QThreadPool.globalInstance()'s own pattern)
rather than an App attribute, so call sites that don't already carry an
`app` reference (cleanup tab widgets are plain QWidgets, not BaseModules)
can use it without new plumbing.
"""
from typing import Optional

from PyQt6.QtCore import QThreadPool

_pool: Optional[QThreadPool] = None

# Small on purpose — these operations are inherently sequential from the
# user's point of view (you don't want two DISM /StartComponentCleanup runs
# fighting over the component store at once) and this pool exists to bound
# their impact on the rest of the app, not to parallelize them.
MAX_THREADS = 2


def get_long_op_pool() -> QThreadPool:
    global _pool
    if _pool is None:
        _pool = QThreadPool()
        _pool.setMaxThreadCount(MAX_THREADS)
    return _pool
