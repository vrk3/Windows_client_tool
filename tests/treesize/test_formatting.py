"""Spec 5.5: modes and units."""
import pytest

from modules.treesize.ui.formatting import (
    Mode, Unit, bar_fraction, format_bytes, format_count, format_percent,
    format_value, node_value, percent_of_parent,
)
from modules.treesize.store.node_store import NodeStore, DIR
from modules.treesize.store.rollup import rollup


def _store():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    docs = s.add(root, "Docs", attrs=DIR)
    s.add(docs, "a.bin", size=750, alloc=1024)
    s.add(root, "b.bin", size=250, alloc=256)
    s.build_child_lists()
    rollup(s)
    return s, root, docs


def test_auto_picks_the_largest_unit_that_fits():
    assert format_bytes(999) == "999 B"
    assert format_bytes(1536) == "1.5 KB"
    assert format_bytes(5 * 1024 ** 3) == "5.0 GB"
    assert format_bytes(3 * 1024 ** 4) == "3.0 TB"


def test_auto_produces_mixed_units_which_is_the_point():
    """Pro's columns mix units row to row; that is Auto doing its job."""
    assert format_bytes(2048) == "2.0 KB"
    assert format_bytes(2 * 1024 ** 2) == "2.0 MB"


def test_an_explicit_unit_overrides_auto():
    assert format_bytes(5 * 1024 ** 3, Unit.MB) == "5,120.0 MB"
    assert format_bytes(1536, Unit.B) == "1,536 B"


def test_decimals_are_configurable():
    assert format_bytes(1536, Unit.KB, decimals=0) == "2 KB"
    assert format_bytes(1536, Unit.KB, decimals=3) == "1.500 KB"


def test_bytes_are_never_shown_fractionally():
    assert format_bytes(999, Unit.B, decimals=3) == "999 B"


def test_zero_and_negative_values():
    assert format_bytes(0) == "0 B"
    assert format_bytes(-1536) == "-1.5 KB", "size deltas keep their sign"


def test_counts_and_percents():
    assert format_count(1234567) == "1,234,567"
    assert format_percent(12.345) == "12.3%"


def test_node_value_follows_the_mode():
    s, root, docs = _store()
    assert node_value(s, root, Mode.SIZE) == 1000
    assert node_value(s, root, Mode.ALLOCATED) == 1280
    assert node_value(s, root, Mode.FILES) == 2


def test_percent_of_parent():
    s, root, docs = _store()
    assert percent_of_parent(s, docs) == pytest.approx(75.0)
    assert percent_of_parent(s, root) == 100.0, "a root is the whole of itself"


def test_percent_of_a_zero_sized_parent_is_zero_not_a_crash():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    child = s.add(root, "empty", attrs=DIR)
    s.build_child_lists()
    rollup(s)
    assert percent_of_parent(s, child) == 0.0


def test_format_value_switches_representation_with_the_mode():
    s, root, docs = _store()
    assert format_value(s, docs, Mode.SIZE) == "750 B"
    assert format_value(s, docs, Mode.ALLOCATED) == "1.0 KB"
    assert format_value(s, docs, Mode.FILES) == "1"
    assert format_value(s, docs, Mode.PERCENT) == "75.0%"


def test_bar_fraction_is_relative_to_the_parent():
    s, root, docs = _store()
    assert bar_fraction(s, docs, Mode.SIZE) == pytest.approx(0.75)
    assert bar_fraction(s, root, Mode.SIZE) == 1.0


def test_bar_fraction_follows_the_mode():
    s, root, docs = _store()
    assert bar_fraction(s, docs, Mode.FILES) == pytest.approx(0.5)


def test_bar_fraction_is_clamped_and_safe_on_empty_parents():
    s = NodeStore()
    root = s.add(-1, "C:", attrs=DIR)
    child = s.add(root, "x", attrs=DIR)
    s.build_child_lists()
    rollup(s)
    assert bar_fraction(s, child, Mode.SIZE) == 0.0


def test_unknown_mode_is_rejected_rather_than_guessed():
    s, root, _ = _store()
    with pytest.raises(ValueError):
        node_value(s, root, "nonsense")
