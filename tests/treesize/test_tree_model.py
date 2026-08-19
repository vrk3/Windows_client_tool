"""Spec 5.4: the directory tree model."""
import pytest
from PyQt6.QtCore import QModelIndex, Qt

from modules.treesize.store.node_store import NodeStore, DIR, EXCLUDED
from modules.treesize.store.rollup import rollup
from modules.treesize.ui.formatting import Mode, Unit
from modules.treesize.ui.tree_model import (
    BarFractionRole, COLUMN_NAME, COLUMN_VALUE, DirectoryTreeModel, NodeIndexRole,
)


def _scan():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    win = s.add(root, "Windows", attrs=DIR)
    s.add(win, "big.dll", size=800, alloc=1024)
    s.add(win, "small.dll", size=100, alloc=256)
    s.add(root, "pagefile.sys", size=100, alloc=100)
    s.build_child_lists()
    rollup(s)
    return s, root


@pytest.fixture
def model(qapp):
    m = DirectoryTreeModel()
    store, root = _scan()
    m.set_scan(store, root)
    return m


def test_the_scan_root_is_the_single_top_level_row(model):
    assert model.rowCount(QModelIndex()) == 1
    root_index = model.index(0, 0, QModelIndex())
    assert model.data(root_index, Qt.ItemDataRole.DisplayRole) == "C:"


def test_node_zero_is_addressable(model):
    """internalId 0 is indistinguishable from unset, so ids are node+1.

    The scan root IS node 0, so this is the common case, not an edge case.
    """
    root_index = model.index(0, 0, QModelIndex())
    assert model.data(root_index, NodeIndexRole) == 0


def test_children_and_parents_round_trip(model):
    root_index = model.index(0, 0, QModelIndex())
    assert model.rowCount(root_index) == 2
    child = model.index(0, 0, root_index)
    assert model.data(child, Qt.ItemDataRole.DisplayRole) == "Windows"
    assert model.parent(child) == root_index
    grandchild = model.index(0, 0, child)
    assert model.parent(grandchild) == child


def test_the_root_has_no_parent(model):
    root_index = model.index(0, 0, QModelIndex())
    assert not model.parent(root_index).isValid()


def test_files_report_no_children(model):
    root_index = model.index(0, 0, QModelIndex())
    pagefile = model.index(1, 0, root_index)
    assert model.data(pagefile, Qt.ItemDataRole.DisplayRole) == "pagefile.sys"
    assert not model.hasChildren(pagefile)


def test_value_column_follows_the_mode(model):
    root_index = model.index(0, 0, QModelIndex())
    value = model.index(0, COLUMN_VALUE, root_index)
    assert model.data(value, Qt.ItemDataRole.DisplayRole) == "900 B"
    model.set_mode(Mode.FILES)
    assert model.data(value, Qt.ItemDataRole.DisplayRole) == "2"
    model.set_mode(Mode.ALLOCATED)
    assert model.data(value, Qt.ItemDataRole.DisplayRole) == "1.2 KB"


def test_the_value_header_names_the_active_mode(model):
    assert model.headerData(COLUMN_VALUE, Qt.Orientation.Horizontal,
                            Qt.ItemDataRole.DisplayRole) == "Size"
    model.set_mode(Mode.ALLOCATED)
    assert model.headerData(COLUMN_VALUE, Qt.Orientation.Horizontal,
                            Qt.ItemDataRole.DisplayRole) == "Allocated space"


def test_unit_override_changes_rendering_without_moving_rows(model):
    root_index = model.index(0, 0, QModelIndex())
    value = model.index(0, COLUMN_VALUE, root_index)
    model.set_unit(Unit.KB, decimals=2)
    assert model.data(value, Qt.ItemDataRole.DisplayRole) == "0.88 KB"


def test_bar_fraction_is_exposed_to_the_delegate(model):
    root_index = model.index(0, 0, QModelIndex())
    windows = model.index(0, 0, root_index)
    assert model.data(windows, BarFractionRole) == pytest.approx(0.9)


def test_sorting_reorders_without_a_reset(model):
    """A reset would collapse the tree and discard expansion state."""
    resets = []
    model.modelAboutToBeReset.connect(lambda: resets.append("reset"))
    layouts = []
    model.layoutChanged.connect(lambda *a: layouts.append("layout"))

    root_index = model.index(0, 0, QModelIndex())
    model.rowCount(root_index)                      # materialise the children
    model.sort(COLUMN_VALUE, Qt.SortOrder.AscendingOrder)

    assert layouts, "sorting must signal a layout change"
    assert not resets, "sorting must never reset the model"
    first = model.index(0, 0, root_index)
    assert model.data(first, Qt.ItemDataRole.DisplayRole) == "pagefile.sys"


def test_sorting_descending_puts_the_largest_first(model):
    root_index = model.index(0, 0, QModelIndex())
    model.rowCount(root_index)
    model.sort(COLUMN_VALUE, Qt.SortOrder.DescendingOrder)
    first = model.index(0, 0, root_index)
    assert model.data(first, Qt.ItemDataRole.DisplayRole) == "Windows"


def test_sorting_by_name_is_case_insensitive(model):
    root_index = model.index(0, 0, QModelIndex())
    model.rowCount(root_index)
    model.sort(COLUMN_NAME, Qt.SortOrder.AscendingOrder)
    first = model.index(0, 0, root_index)
    assert model.data(first, Qt.ItemDataRole.DisplayRole) == "pagefile.sys"


def test_excluded_nodes_are_not_shown(qapp):
    """Filtered nodes stay in the store but must never reach the view."""
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    s.add(root, "keep.bin", size=10)
    s.add(root, "dropped.tmp", size=99, attrs=EXCLUDED)
    s.build_child_lists()
    rollup(s)
    m = DirectoryTreeModel()
    m.set_scan(s, root)
    root_index = m.index(0, 0, QModelIndex())
    assert m.rowCount(root_index) == 1
    assert m.data(m.index(0, 0, root_index), Qt.ItemDataRole.DisplayRole) == "keep.bin"


def test_an_empty_model_is_safe_to_query(qapp):
    m = DirectoryTreeModel()
    assert m.rowCount(QModelIndex()) == 0
    assert not m.index(0, 0, QModelIndex()).isValid()
    assert m.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None
