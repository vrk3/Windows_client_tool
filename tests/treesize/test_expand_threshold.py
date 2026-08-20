"""Spec 5.4: "Expand offers levels 1/2/3, Full expand, and
expand-to-size-threshold, matching Pro."

The menu shipped with the levels and Full expand. The threshold entry -- the
one that answers "show me everything worth looking at and nothing else" --
was never built.
"""
import pytest
from PyQt6.QtCore import QModelIndex

from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.directory_tree import DirectoryTree


def _scan():
    """A root holding one fat branch and one thin one, three levels deep."""
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    fat = s.add(root, "fat", attrs=DIR)
    fatter = s.add(fat, "fatter", attrs=DIR)
    s.add(fatter, "huge.bin", size=800)
    thin = s.add(root, "thin", attrs=DIR)
    thinner = s.add(thin, "thinner", attrs=DIR)
    s.add(thinner, "small.bin", size=4)
    s.build_child_lists()
    rollup(s)
    return s, root


@pytest.fixture
def tree(qapp):
    t = DirectoryTree()
    store, root = _scan()
    t.set_scan(store, root)
    return t


def _expanded_names(tree):
    """Every expanded folder, by name."""
    out = []
    store = tree.tree_model._store

    def walk(parent):
        for row in range(tree.tree_model.rowCount(parent)):
            index = tree.tree_model.index(row, 0, parent)
            if tree.isExpanded(index):
                out.append(store.name(int(index.internalId()) - 1))
                walk(index)

    walk(QModelIndex())
    return out


def test_it_expands_the_branch_above_the_threshold(tree):
    tree.expand_to_size(500)
    names = _expanded_names(tree)
    assert "fat" in names and "fatter" in names


def test_it_leaves_the_branch_below_the_threshold_shut(tree):
    """The whole point: everything worth looking at, and nothing else."""
    tree.expand_to_size(500)
    names = _expanded_names(tree)
    assert "thin" not in names and "thinner" not in names


def test_a_threshold_of_zero_expands_everything(tree):
    tree.expand_to_size(0)
    names = _expanded_names(tree)
    assert {"fat", "fatter", "thin", "thinner"} <= set(names)


def test_it_returns_how_many_it_opened(tree):
    assert tree.expand_to_size(500) == len(_expanded_names(tree))


def test_a_threshold_above_everything_opens_nothing_below_the_root(tree):
    tree.collapseAll()
    tree.expand_to_size(10 ** 12)
    assert _expanded_names(tree) == []


def test_it_stops_at_the_limit(tree):
    """"Everything over 1 MB" on a real volume is hundreds of thousands of
    rows. Expanding them all is a freeze, not a view."""
    assert tree.expand_to_size(0, limit=2) == 2


def test_it_survives_an_empty_tree(qapp):
    assert DirectoryTree().expand_to_size(500) == 0


def test_a_folder_is_judged_on_the_current_mode(tree):
    """Under Number of files a threshold means files, not bytes -- the column
    the user is looking at is the one the threshold applies to."""
    from modules.treesize.ui.formatting import Mode
    tree.tree_model.set_mode(Mode.FILES)
    tree.collapseAll()
    tree.expand_to_size(1)
    assert "fat" in _expanded_names(tree)


def test_percent_mode_falls_back_to_size(tree):
    """percent-of-parent is not monotonic down a branch -- a lone child of a
    tiny folder is 100% of it. A percentage prunes nothing, and a threshold
    that prunes nothing expands the whole volume."""
    from modules.treesize.ui.formatting import Mode
    tree.tree_model.set_mode(Mode.PERCENT)
    tree.collapseAll()
    tree.expand_to_size(500)
    names = _expanded_names(tree)
    assert "fat" in names
    assert "thin" not in names, "a percentage threshold expanded the thin branch"
