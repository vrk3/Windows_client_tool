"""Blocklist matcher for Windows Update / winget items.

Ported from Update Center's Test-UcBlocked: an item is blocked if its name OR
id matches any pattern (case-insensitive). Patterns support '*' as a wildcard;
a bare pattern with no '*' is auto-wrapped as '*pattern*' (substring match).
Blank lines and lines starting with '#' are treated as comments and ignored.
"""
import fnmatch
from typing import List


def normalize_patterns(raw_text: str) -> List[str]:
    """Split textarea content into a clean pattern list (strip, drop blanks/#comments)."""
    patterns = []
    for line in (raw_text or "").splitlines():
        p = line.strip()
        if not p or p.startswith("#"):
            continue
        patterns.append(p)
    return patterns


def add_pattern(app, pattern: str) -> None:
    """Append `pattern` to app.config's updates.blocklist_patterns (no duplicates)."""
    pattern = (pattern or "").strip()
    if not pattern:
        return
    patterns = list(app.config.get("updates.blocklist_patterns", []))
    if pattern not in patterns:
        patterns.append(pattern)
        app.config.set("updates.blocklist_patterns", patterns)


def is_blocked(name: str, id_: str, patterns: List[str]) -> bool:
    """Return True if `name` or `id_` matches any pattern in `patterns`."""
    if not patterns:
        return False
    name = (name or "").lower()
    id_ = (id_ or "").lower()
    for raw in patterns:
        p = (raw or "").strip()
        if not p or p.startswith("#"):
            continue
        p = p.lower()
        if "*" not in p:
            p = f"*{p}*"
        if id_ and fnmatch.fnmatch(id_, p):
            return True
        if name and fnmatch.fnmatch(name, p):
            return True
    return False
