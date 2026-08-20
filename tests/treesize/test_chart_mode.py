"""Spec 5.5: Mode is PANE state, and the chart is part of the pane.

"Mode -- Size, Allocated space, Number of files, Percent -- selects what the
tree bars, the chart, and the size columns represent. It is pane state, not
per-view state."

The tree honoured it from the beginning. The chart never did: every treemap
tile, pie slice and bar was weighted by `store.size` no matter which mode was
selected, so switching to Allocated space on a volume whose sparse and
compressed files make size and allocated differ by 240 GB redrew exactly the
same picture.
"""
import pytest

from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.formatting import Mode, files_of, weight_value
from modules.treesize.ui.treemap import build_treemap


def _tree():
    """`big` is large but sparse; `small` is small but fully allocated.

    Under Size the order is big, small. Under Allocated space it reverses --
    which is the entire point of having the mode.
    """
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    a = s.add(root, "sparse", attrs=DIR)
    s.add(a, "big.vhd", size=900, alloc=100)
    b = s.add(root, "dense", attrs=DIR)
    s.add(b, "one.bin", size=100, alloc=900)
    s.add(b, "two.bin", size=1, alloc=100)
    s.build_child_lists()
    rollup(s)
    return s, root, a, b


# ---- the weighting ------------------------------------------------------

def test_weight_value_follows_the_mode():
    s, root, sparse, dense = _tree()
    assert weight_value(s, sparse, Mode.SIZE) == 900
    assert weight_value(s, sparse, Mode.ALLOCATED) == 100
    assert weight_value(s, dense, Mode.SIZE) == 101
    assert weight_value(s, dense, Mode.ALLOCATED) == 1000


def test_percent_weights_by_size():
    """A slice's share of its parent IS its percent, so a percent-weighted
    chart is a size-weighted chart with different labels -- not an empty one."""
    s, root, sparse, _dense = _tree()
    assert weight_value(s, sparse, Mode.PERCENT) == weight_value(s, sparse, Mode.SIZE)


def test_a_file_counts_as_one_file():
    """rollup charges a file to its PARENT, so file_count on a file itself is
    0. Weighting a chart by that leaves every leaf with zero area and draws
    nothing at all; showing it in the tree reads "0" for a file, which is not
    a count but an artefact."""
    s, root, _sparse, dense = _tree()
    leaf = next(iter(s.children(dense)))
    assert not (s.attrs[leaf] & DIR)
    assert files_of(s, leaf) == 1
    assert weight_value(s, leaf, Mode.FILES) == 1
    assert files_of(s, dense) == 2       # a folder keeps its subtree total


# ---- the treemap --------------------------------------------------------

def _area_by_name(store, rects, parent_depth=1):
    return {store.name(r.node): r.w * r.h
            for r in rects if r.depth == parent_depth}


def test_the_treemap_reweights_under_allocated_space():
    s, root, _sparse, _dense = _tree()
    by_size = _area_by_name(s, build_treemap(s, root, 400.0, 400.0,
                                             mode=Mode.SIZE))
    by_alloc = _area_by_name(s, build_treemap(s, root, 400.0, 400.0,
                                              mode=Mode.ALLOCATED))
    assert by_size["sparse"] > by_size["dense"]
    assert by_alloc["dense"] > by_alloc["sparse"]


def test_the_treemap_defaults_to_size():
    """No mode argument must keep the picture every existing caller drew."""
    s, root, _sparse, _dense = _tree()
    assert (_area_by_name(s, build_treemap(s, root, 400.0, 400.0))
            == _area_by_name(s, build_treemap(s, root, 400.0, 400.0,
                                              mode=Mode.SIZE)))


def test_the_treemap_draws_something_under_number_of_files():
    """Weighting leaves by file_count without the files_of correction gives
    every one of them zero area, and the chart goes blank."""
    s, root, _sparse, _dense = _tree()
    rects = build_treemap(s, root, 400.0, 400.0, mode=Mode.FILES)
    leaves = [r for r in rects if r.depth == 2]
    assert leaves and all(r.w * r.h > 0 for r in leaves)


def test_an_excluded_node_stays_out_in_every_mode():
    s, root, _sparse, dense = _tree()
    for child in s.children(dense):
        s.attrs[child] |= EXCLUDED
    for mode in Mode:
        names = {s.name(r.node) for r in build_treemap(s, root, 400.0, 400.0,
                                                       mode=mode)}
        assert "one.bin" not in names, mode
