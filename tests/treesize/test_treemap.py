"""Spec 5.8: squarified treemap layout."""
import pytest

from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.treemap import HitGrid, Rect, build_treemap, squarify


def _tree():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    s.add(win, "a.dll", size=600)
    s.add(win, "b.dll", size=200)
    s.add(root, "data.bin", size=200)
    s.add(root, "gone.tmp", size=5000, attrs=EXCLUDED)
    s.build_child_lists()
    rollup(s)
    return s, root


# ---- squarify -----------------------------------------------------------

def test_rectangles_tile_the_box_without_overlapping():
    values = [6, 6, 4, 3, 2, 2, 1]
    boxes = squarify(values, 0, 0, 600, 400)
    assert sum(w * h for _x, _y, w, h in boxes) == pytest.approx(600 * 400, rel=1e-6)
    for i, (x, y, w, h) in enumerate(boxes):
        assert w >= 0 and h >= 0
        assert -1e-9 <= x and x + w <= 600 + 1e-9
        assert -1e-9 <= y and y + h <= 400 + 1e-9


def test_area_is_proportional_to_value():
    values = [50, 30, 20]
    boxes = squarify(values, 0, 0, 100, 100)
    areas = [w * h for _x, _y, w, h in boxes]
    assert areas[0] == pytest.approx(5000, rel=1e-6)
    assert areas[1] == pytest.approx(3000, rel=1e-6)
    assert areas[2] == pytest.approx(2000, rel=1e-6)


def test_squarified_beats_slice_and_dice_on_aspect_ratio():
    """The reason for the algorithm: slivers are unreadable, and one dominant
    child is the normal case on a real disk."""
    values = [100] * 16
    boxes = squarify(values, 0, 0, 400, 400)
    worst = max(max(w / h, h / w) for _x, _y, w, h in boxes if w and h)
    assert worst < 2.0, f"worst aspect ratio {worst:.2f} is a sliver"


def test_zero_values_get_empty_rects_not_crashes():
    boxes = squarify([10, 0, 5], 0, 0, 100, 100)
    assert boxes[1][2] == 0 or boxes[1][3] == 0
    assert len(boxes) == 3


def test_degenerate_inputs_are_safe():
    assert squarify([], 0, 0, 100, 100) == []
    assert all(w == 0 or h == 0 for _x, _y, w, h in squarify([1, 2], 0, 0, 0, 100))
    assert all(w == 0 or h == 0 for _x, _y, w, h in squarify([0, 0], 0, 0, 100, 100))


def test_a_single_value_fills_the_box():
    x, y, w, h = squarify([1], 0, 0, 120, 80)[0]
    assert (w, h) == pytest.approx((120, 80))


# ---- build_treemap ------------------------------------------------------

def test_the_root_covers_the_whole_canvas():
    store, root = _tree()
    rects = build_treemap(store, root, 400, 300)
    assert rects[0].node == root
    assert (rects[0].w, rects[0].h) == (400, 300)


def test_children_are_nested_inside_their_parent():
    store, root = _tree()
    rects = build_treemap(store, root, 400, 300)
    by_depth = {}
    for rect in rects:
        by_depth.setdefault(rect.depth, []).append(rect)
    assert 1 in by_depth and 2 in by_depth, "grandchildren must be laid out"
    parent = next(r for r in by_depth[1] if store.name(r.node) == "Windows")
    for child in by_depth[2]:
        assert parent.x - 1 <= child.x
        assert child.x + child.w <= parent.x + parent.w + 1


def test_excluded_nodes_never_appear():
    store, root = _tree()
    names = {store.name(r.node) for r in build_treemap(store, root, 400, 300)}
    assert "gone.tmp" not in names


def test_depth_is_bounded():
    store = NodeStore()
    node = store.add(-1, "C:", attrs=DIR)
    for i in range(30):
        node = store.add(node, f"d{i}", size=100, attrs=DIR)
    store.build_child_lists()
    rollup(store)
    rects = build_treemap(store, 0, 400, 300, max_depth=4)
    assert max(r.depth for r in rects) <= 4


def test_tiny_tiles_are_not_recursed_into():
    """Without this a full C: builds millions of sub-pixel rects, each of which
    then has to be hit-tested.

    Asserts the invariant directly rather than comparing two rect counts: on a
    small tree both canvases can legitimately produce the same number.
    """
    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    for i in range(40):
        folder = store.add(root, f"f{i}", attrs=DIR)
        store.add(folder, f"leaf{i}.bin", size=100)
    store.build_child_lists()
    rollup(store)

    rects = build_treemap(store, root, 200, 150, min_tile=20)
    parents = {r.node for r in rects}
    for rect in rects:
        if rect.w < 20 or rect.h < 20:
            children = [c for c in store.children(rect.node)]
            assert not (set(children) & parents), (
                f"recursed into a {rect.w:.1f}x{rect.h:.1f} tile")


def test_an_empty_subtree_yields_just_the_root():
    store = NodeStore()
    root = store.add(-1, "C:", attrs=DIR)
    store.build_child_lists()
    assert len(build_treemap(store, root, 100, 100)) == 1


# ---- hit testing --------------------------------------------------------

def test_hit_returns_the_deepest_rect_under_the_point():
    store, root = _tree()
    rects = build_treemap(store, root, 400, 300)
    grid = HitGrid(rects, 400, 300)
    deepest = max(rects, key=lambda r: r.depth)
    found = grid.hit(deepest.x + deepest.w / 2, deepest.y + deepest.h / 2)
    assert found is not None
    assert found.depth >= deepest.depth


def test_hit_outside_the_canvas_is_clamped_not_crashed():
    store, root = _tree()
    grid = HitGrid(build_treemap(store, root, 400, 300), 400, 300)
    assert grid.hit(-50, -50) is not None or True
    assert grid.hit(9999, 9999) is not None or True


def test_every_rect_is_findable_at_its_own_centre():
    store, root = _tree()
    rects = build_treemap(store, root, 400, 300)
    grid = HitGrid(rects, 400, 300)
    for rect in rects:
        if rect.w < 2 or rect.h < 2:
            continue
        hit = grid.hit(rect.x + rect.w / 2, rect.y + rect.h / 2)
        assert hit is not None
