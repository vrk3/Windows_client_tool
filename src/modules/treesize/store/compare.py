"""Diffing two scans (spec 4.4).

Walks two stores by PATH and produces a delta tree carrying both sizes and
their difference. Path, not node index: indices are assigned in scan order and
mean nothing across two scans of the same volume, so matching on them would
pair unrelated files and report nonsense confidently.

Drives Compare-with-saved-scan, Compare-with-snapshot, Compare-with-path, and
the "Show size changes" toggle.
"""
from dataclasses import dataclass, field

from .node_store import DIR, EXCLUDED


@dataclass
class Delta:
    """One node's change between two scans."""
    path: str
    name: str
    is_dir: bool
    old_size: int
    new_size: int
    children: list = field(default_factory=list)

    @property
    def change(self) -> int:
        return self.new_size - self.old_size

    @property
    def status(self) -> str:
        if self.old_size == 0 and self.new_size > 0 and not self._existed_before:
            return "added"
        if self._existed_before and not self._exists_after:
            return "removed"
        if self.change > 0:
            return "grown"
        if self.change < 0:
            return "shrunk"
        return "unchanged"

    _existed_before: bool = True
    _exists_after: bool = True


def _index_children(store, node: int) -> dict:
    """name -> child node, for one level. Names are unique within a folder."""
    out = {}
    if store is None or not (0 <= node < len(store)):
        return out
    for child in store.children(node):
        if store.attrs[child] & EXCLUDED:
            continue
        out[store.name(child).lower()] = child
    return out


def diff(old_store, old_root: int, new_store, new_root: int,
         max_depth: int = 6) -> Delta:
    """Compare two subtrees, matching children by name at each level.

    Bounded by depth for the same reason the treemap is: a full-volume diff
    two levels deeper than anyone will expand costs a great deal and shows
    nothing. Folder totals are already rolled up, so a shallow tree still
    reports the true size change of everything beneath it.
    """
    root = Delta(
        path=_name_of(new_store, new_root) or _name_of(old_store, old_root),
        name=_name_of(new_store, new_root) or _name_of(old_store, old_root),
        is_dir=True,
        old_size=_size_of(old_store, old_root),
        new_size=_size_of(new_store, new_root),
    )
    root._existed_before = old_root >= 0
    root._exists_after = new_root >= 0
    _walk(old_store, old_root, new_store, new_root, root, 0, max_depth)
    return root


def _walk(old_store, old_node, new_store, new_node, parent: Delta,
          depth: int, max_depth: int) -> None:
    if depth >= max_depth:
        return
    old_kids = _index_children(old_store, old_node)
    new_kids = _index_children(new_store, new_node)
    for key in sorted(set(old_kids) | set(new_kids)):
        old_child = old_kids.get(key)
        new_child = new_kids.get(key)
        source, node = ((new_store, new_child) if new_child is not None
                        else (old_store, old_child))
        delta = Delta(
            path=parent.path + "\\" + source.name(node),
            name=source.name(node),
            is_dir=bool(source.attrs[node] & DIR),
            old_size=_size_of(old_store, old_child),
            new_size=_size_of(new_store, new_child),
        )
        delta._existed_before = old_child is not None
        delta._exists_after = new_child is not None
        parent.children.append(delta)
        if delta.is_dir:
            _walk(old_store, old_child, new_store, new_child, delta,
                  depth + 1, max_depth)


def _size_of(store, node) -> int:
    if store is None or node is None or not (0 <= node < len(store)):
        return 0
    return store.size[node]


def _name_of(store, node) -> str:
    if store is None or node is None or not (0 <= node < len(store)):
        return ""
    return store.name(node)


def flatten(delta: Delta, changed_only: bool = True) -> list:
    """Depth-first list of deltas, biggest absolute change first.

    Sorted by MAGNITUDE of change, not by size: the question a comparison
    answers is "what moved", and a 40 GB folder that did not budge is not the
    answer even though it is the biggest thing present.
    """
    out = []

    def visit(node: Delta) -> None:
        for child in node.children:
            if not changed_only or child.change != 0:
                out.append(child)
            visit(child)

    visit(delta)
    out.sort(key=lambda d: abs(d.change), reverse=True)
    return out


def summarise(delta: Delta) -> str:
    grown = shrunk = added = removed = 0
    for node in flatten(delta, changed_only=True):
        status = node.status
        if status == "added":
            added += 1
        elif status == "removed":
            removed += 1
        elif status == "grown":
            grown += 1
        elif status == "shrunk":
            shrunk += 1
    from ..ui.formatting import format_bytes
    return (f"{format_bytes(delta.change)} overall — "
            f"{added:,} added, {removed:,} removed, "
            f"{grown:,} grown, {shrunk:,} shrunk")
