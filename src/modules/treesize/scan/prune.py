"""Apply filters to an already-assembled tree.

The walk engine filters as it goes: it meets an entry, asks the FilterSet, and
simply never stores it -- so an excluded directory is never descended into and
its subtree costs nothing.

The MFT engine cannot work that way. Records arrive in MFT order, which carries
no guarantee that a parent is seen before its children, so a directory dropped
at feed time would leave its children unparented. They would be reunited under
[Orphaned files] instead of disappearing: still counted, and now misfiled,
which is worse than not filtering at all.

So MFT filtering is a second pass over the finished tree. Excluded nodes are
marked rather than deleted -- removing a row from a columnar store means
rewriting every parallel array and rewriting every parent index that points
past it, which costs far more than the flag does. `rollup` skips flagged nodes,
so they contribute no size and no count.
"""
from ..store.node_store import NodeStore, EXCLUDED


def prune_excluded(store: NodeStore, root: int, filters) -> int:
    """Mark every node the filters reject, and everything beneath it.

    Returns the number of subtree roots excluded. Descendants of an excluded
    node are marked but NOT re-tested and NOT counted again: excluding
    `node_modules` is one exclusion, not one per file inside it.

    The root is never excluded. Filtering away the thing you asked to scan is
    never what was meant, and it would leave the caller with a total of zero
    and no explanation.
    """
    excluded_roots = 0
    stack = [(child, False) for child in store.children(root)]
    while stack:
        node, inherited = stack.pop()
        if inherited:
            store.attrs[node] |= EXCLUDED
            drop = True
        else:
            drop = filters.excludes(store.name(node), store.size[node],
                                    store.attrs[node])
            if drop:
                store.attrs[node] |= EXCLUDED
                excluded_roots += 1
        for child in store.children(node):
            stack.append((child, drop))
    return excluded_roots
