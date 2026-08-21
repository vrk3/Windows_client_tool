"""Where a module name should take you.

Kept apart from MainWindow so the rule can be tested without an App singleton
and a real window: this is pure name resolution, no Qt.
"""
from typing import Dict, Optional, Set, Tuple


def resolve_target(
    name: str,
    sidebar_names: Set[str],
    routes: Dict[str, Tuple[str, Optional[int]]],
) -> Tuple[Optional[str], Optional[int]]:
    """Resolve `name` to `(module to select, tab index or None)`.

    A real sidebar entry always wins, so a composite child cannot shadow a
    module that still has its own entry. Anything unknown resolves to
    `(None, None)` and the caller does nothing — the same as today's miss.
    """
    if name in sidebar_names:
        return name, None
    host, tab = routes.get(name, (None, None))
    if host is None:
        return None, None
    return host, tab
