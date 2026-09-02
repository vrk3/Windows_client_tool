"""The Details table's layout persistence (W5-01).

Task Manager's polish: the columns someone turns on, drags into an order,
and resizes to fit their eye stay that way on the next launch. The
visible-set has always persisted; what these tests add is that WIDTHS and
ORDER persist too -- and that a restore does not re-save itself (which
would clobber the very values being restored).
"""
import tempfile

import pytest

from core.config_manager import ConfigManager
from modules.dashboard.details_tab import ORDER_KEY, WIDTHS_KEY, DetailsTab
from core.procengine.columns import COLUMNS, DEFAULT_KEYS


def _column_index(tab, key):
    for section, column in enumerate(tab.model.columns()):
        if column.key == key:
            return section
    raise AssertionError(f"{key} is not shown")


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = ConfigManager(config_dir=tmpdir, defaults={"version": 1})
        cfg.load()
        yield cfg


class _FakeApp:
    def __init__(self, config):
        self.config = config
        self.thread_pool = None


def _fresh(config, qapp):
    """A tab wired to a real config, fully built and returned."""
    widget = DetailsTab()
    widget.set_app(_FakeApp(config))
    widget.refresh()
    return widget


# ---- widths persist -----------------------------------------------------

def test_a_resized_column_is_saved(qapp, manager):
    widget = _fresh(manager, qapp)
    try:
        header = widget.table.horizontalHeader()
        section = _column_index(widget, "name")
        header.resizeSection(section, 400)
        saved = manager.get(WIDTHS_KEY) or {}
        assert saved.get("name") == 400
    finally:
        widget.stop()
        widget.deleteLater()


def test_a_saved_width_is_restored_on_the_next_tab(qapp, manager):
    manager.set(WIDTHS_KEY, {"name": 333})
    widget = _fresh(manager, qapp)
    try:
        section = _column_index(widget, "name")
        assert widget.table.horizontalHeader().sectionSize(section) == 333
    finally:
        widget.stop()
        widget.deleteLater()


def test_applying_saved_widths_does_not_resave_them(qapp, manager):
    """A restore resizes every column, which re-fires sectionResized. If
    that re-saved, restoring 333 would immediately write whatever the
    default was back over it. The guard must hold."""
    manager.set(WIDTHS_KEY, {"name": 333, "pid": 44})
    widget = _fresh(manager, qapp)
    try:
        saved = manager.get(WIDTHS_KEY) or {}
        assert saved.get("name") == 333, f"restore clobbered the width: {saved}"
        assert saved.get("pid") == 44
    finally:
        widget.stop()
        widget.deleteLater()


def test_a_width_for_a_hidden_column_is_ignored(qapp, manager):
    """A saved layout names columns that may no longer be shown; applying
    it must not resurrect them or crash."""
    manager.set(WIDTHS_KEY, {"cmdline": 500})
    widget = _fresh(manager, qapp)  # cmdline not shown by default
    try:
        keys = [column.key for column in widget.model.columns()]
        assert "cmdline" not in keys  # the hidden column stayed hidden
        assert len(keys) == len(DEFAULT_KEYS)
    finally:
        widget.stop()
        widget.deleteLater()


# ---- order persists -----------------------------------------------------

def test_a_moved_column_order_is_saved(qapp, manager):
    widget = _fresh(manager, qapp)
    try:
        header = widget.table.horizontalHeader()
        # Move the third column to the front and verify it is recorded.
        columns = widget.model.columns()
        third = columns[2].key
        from_section = _column_index(widget, third)
        header.moveSection(header.visualIndex(from_section), 0)
        saved = manager.get(ORDER_KEY)
        assert saved and saved[0] == third
    finally:
        widget.stop()
        widget.deleteLater()


def test_a_saved_order_is_restored_on_the_next_tab(qapp, manager):
    reversed_keys = list(reversed([c.key for c in COLUMNS
                                   if c.key in DEFAULT_KEYS]))
    manager.set(ORDER_KEY, reversed_keys)
    widget = _fresh(manager, qapp)
    try:
        header = widget.table.horizontalHeader()
        columns = widget.model.columns()
        visual = sorted(range(len(columns)),
                        key=lambda s: header.visualIndex(s))
        on_screen = [columns[s].key for s in visual]
        assert on_screen[:len(reversed_keys)] == reversed_keys
    finally:
        widget.stop()
        widget.deleteLater()
