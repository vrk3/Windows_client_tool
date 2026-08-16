import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from modules.treesize.disk_scanner import DiskNode


def _make_tree():
    """root
         -> big_folder (size set only via children; starts as a stub-like
            structure with two nested levels, deliberately built out of order
            so a shallow sort would leave the deeper levels untouched)
             -> deep_small (size 10)
             -> deep_big   (size 900)
         -> small_folder
             -> tiny (size 5)
         -> loose_file (size 50)
    """
    root = DiskNode(path="/root", name="root", size=0, is_dir=True)

    big_folder = DiskNode(path="/root/big_folder", name="big_folder", size=910, is_dir=True, parent=root)
    deep_small = DiskNode(path="/root/big_folder/deep_small", name="deep_small", size=10, is_dir=False, parent=big_folder)
    deep_big = DiskNode(path="/root/big_folder/deep_big", name="deep_big", size=900, is_dir=False, parent=big_folder)
    big_folder.children = [deep_small, deep_big]  # deliberately unsorted (small before big)

    small_folder = DiskNode(path="/root/small_folder", name="small_folder", size=5, is_dir=True, parent=root)
    tiny = DiskNode(path="/root/small_folder/tiny", name="tiny", size=5, is_dir=False, parent=small_folder)
    small_folder.children = [tiny]

    loose_file = DiskNode(path="/root/loose_file", name="loose_file", size=50, is_dir=False, parent=root)

    root.children = [small_folder, loose_file, big_folder]  # deliberately unsorted
    return root


def test_sort_recurses_into_nested_children_not_just_one_level():
    """Regression test: sort() used to only reorder self._roots and its direct
    children, leaving anything nested deeper untouched — so re-sorting after
    navigating into a subfolder had no visible effect there. It must recurse
    all the way down."""
    from modules.treesize.disk_tree_model import DiskTreeModel, COL_SIZE
    from PyQt6.QtCore import Qt

    root = _make_tree()
    model = DiskTreeModel()
    model.add_batch([root])

    model.sort(COL_SIZE, Qt.SortOrder.DescendingOrder)

    # Folders first (big_folder 910, small_folder 5), then the loose file (50)
    # last — see test_sort_groups_folders_before_files_like_treesize below
    # for the dedicated check of that grouping.
    assert [c.name for c in model.get_roots()[0].children] == [
        "big_folder", "small_folder", "loose_file"]

    # Nested level, two folders deep: deep_big (900) must sort before
    # deep_small (10) — this is exactly the level the old one-level-deep
    # sort() never touched.
    sorted_big_folder = model.get_roots()[0].children[0]
    assert [c.name for c in sorted_big_folder.children] == ["deep_big", "deep_small"]


def test_sort_ascending_also_recurses():
    from modules.treesize.disk_tree_model import DiskTreeModel, COL_SIZE
    from PyQt6.QtCore import Qt

    root = _make_tree()
    model = DiskTreeModel()
    model.add_batch([root])

    model.sort(COL_SIZE, Qt.SortOrder.AscendingOrder)

    # Folders group stays first even ascending (small_folder 5, big_folder
    # 910) — only the order *within* the folder group flips; the file
    # (loose_file, 50) still comes after all folders regardless of its size.
    assert [c.name for c in model.get_roots()[0].children] == [
        "small_folder", "big_folder", "loose_file"]

    sorted_big_folder = model.get_roots()[0].children[1]
    assert sorted_big_folder.name == "big_folder"
    assert [c.name for c in sorted_big_folder.children] == ["deep_small", "deep_big"]


def test_sort_groups_folders_before_files_like_treesize():
    """The actual bug report: folders must always lead the list when sorted,
    with files following after — like real TreeSize — regardless of a huge
    file outranking a small folder in raw byte size, and regardless of
    ascending vs descending."""
    from modules.treesize.disk_tree_model import DiskTreeModel, COL_SIZE
    from PyQt6.QtCore import Qt

    root = DiskNode(path="/root", name="root", size=0, is_dir=True)
    huge_file = DiskNode(path="/root/huge.iso", name="huge.iso", size=10_000, is_dir=False, parent=root)
    tiny_folder = DiskNode(path="/root/tiny_folder", name="tiny_folder", size=1, is_dir=True, parent=root)
    root.children = [huge_file, tiny_folder]

    model = DiskTreeModel()
    model.add_batch([root])

    model.sort(COL_SIZE, Qt.SortOrder.DescendingOrder)
    names = [c.name for c in model.get_roots()[0].children]
    assert names == ["tiny_folder", "huge.iso"], (
        "the 1-byte folder must still lead the 10,000-byte file — folders "
        "are a fixed group ahead of files, not merged into one flat size sort"
    )


def test_pie_chart_ranks_by_size_not_display_order():
    """The pie chart must always show the biggest folders, independent of
    whatever column the tree view happens to be sorted by at the moment
    set_data() is called (e.g. Name) — it used to just take the first N
    children in whatever order they arrived in."""
    from modules.treesize.treesize_module import _PieChart
    from modules.treesize.disk_scanner import DiskNode

    root = DiskNode(path="/root", name="root", size=0, is_dir=True)
    # Deliberately alphabetical (NOT size) order, unlike a real size-sorted tree
    a = DiskNode(path="/root/a_small", name="a_small", size=10, is_dir=True, parent=root)
    b = DiskNode(path="/root/b_huge", name="b_huge", size=1000, is_dir=True, parent=root)
    c = DiskNode(path="/root/c_medium", name="c_medium", size=100, is_dir=True, parent=root)
    root.children = [a, b, c]

    chart = _PieChart()
    chart.set_data([root])

    names_in_order = [d[0] for d in chart._data]
    assert names_in_order[0] == "b_huge"
    assert names_in_order[1] == "c_medium"
    assert names_in_order[2] == "a_small"


def test_pie_chart_folds_overflow_into_other_bucket():
    """More directories than there are distinct colors for must fold into one
    'Other' slice with a reserved neutral color, rather than either cycling
    colors (reusing a hue for an unrelated folder) or silently dropping them
    (which also broke the percentages summing to 100%)."""
    from modules.treesize.treesize_module import _PieChart
    from modules.treesize.disk_scanner import DiskNode

    root = DiskNode(path="/root", name="root", size=0, is_dir=True)
    n = _PieChart._MAX_SLICES + 5
    children = [
        DiskNode(path=f"/root/d{i}", name=f"d{i}", size=(n - i) * 10, is_dir=True, parent=root)
        for i in range(n)
    ]
    root.children = children

    chart = _PieChart()
    chart.set_data([root])

    assert len(chart._data) == _PieChart._MAX_SLICES + 1  # top slices + one "Other"
    other_name, other_size, other_color, other_frac = chart._data[-1]
    assert other_name.startswith("Other")
    assert other_color == _PieChart._OTHER_COLOR
    # No real category color was reused for the "Other" bucket
    assert other_color not in [d[2] for d in chart._data[:-1]]
    # Percentages across all slices (including Other) sum to ~100%
    assert abs(sum(d[3] for d in chart._data) - 1.0) < 1e-9
