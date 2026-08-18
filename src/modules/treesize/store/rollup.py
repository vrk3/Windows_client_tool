"""Bottom-up aggregation of folder subtotals.

Two linear passes, no recursion. An MFT record number carries no ordering
guarantee relative to its parent, so depth is resolved iteratively and
nodes are then processed deepest-first via a counting sort.
"""
import array

from .node_store import NodeStore, DIR

_UNVISITED = -1
_IN_PROGRESS = -2


def compute_depths(store: NodeStore) -> array.array:
    n = len(store)
    depth = array.array("i", [-1]) * n if n else array.array("i")
    for i in range(n):
        if depth[i] >= 0:
            continue
        chain = []
        j = i
        while j >= 0 and j < n and depth[j] == _UNVISITED:
            depth[j] = _IN_PROGRESS
            chain.append(j)
            nxt = store.parent[j]
            j = nxt if (0 <= nxt < n and nxt != j) else -1
        # If we stopped on a node with depth == _IN_PROGRESS, we detected a cycle; treat as root
        if 0 <= j < n and depth[j] == _IN_PROGRESS:
            base = -1
        else:
            base = depth[j] if (0 <= j < n) else -1
        for k in reversed(chain):
            base += 1
            depth[k] = base
    return depth


def _order_by_depth(depth: array.array, n: int) -> list[int]:
    """Counting sort: indices ascending by depth. O(n), not O(n log n)."""
    if n == 0:
        return []
    max_d = max(depth)
    counts = [0] * (max_d + 2)
    for d in depth:
        counts[d + 1] += 1
    for i in range(1, len(counts)):
        counts[i] += counts[i - 1]
    order = [0] * n
    for i in range(n):
        d = depth[i]
        order[counts[d]] = i
        counts[d] += 1
    return order


def rollup(store: NodeStore) -> None:
    n = len(store)
    if n == 0:
        return
    depth = compute_depths(store)
    order = _order_by_depth(depth, n)
    for i in reversed(order):
        p = store.parent[i]
        if not (0 <= p < n) or p == i:
            continue
        # On a cycle, depth[p] >= depth[i]; skip to prevent double-counting.
        # Legitimate children are always exactly one level deeper than their parent.
        if depth[p] >= depth[i]:
            continue
        store.size[p] += store.size[i]
        store.alloc[p] += store.alloc[i]
        if store.attrs[i] & DIR:
            store.folder_count[p] += 1 + store.folder_count[i]
            store.file_count[p] += store.file_count[i]
        else:
            store.file_count[p] += 1
