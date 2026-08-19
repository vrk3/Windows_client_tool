"""Options dialog: settings that actually change behaviour."""
import pytest

from modules.treesize.ui.formatting import Mode, Unit
from modules.treesize.ui.options_dialog import (
    DEFAULTS, OptionsDialog, load_settings, save_settings,
)
from modules.treesize.ui.shell import TreeSizeShell


class FakeConfig:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class BrokenConfig:
    def get(self, key, default=None):
        raise RuntimeError("backend unavailable")

    def set(self, key, value):
        raise RuntimeError("backend unavailable")


def test_defaults_load_without_a_config():
    assert load_settings(None) == DEFAULTS


def test_a_broken_config_falls_back_instead_of_failing():
    """A config backend that cannot read must not stop the module loading."""
    assert load_settings(BrokenConfig()) == DEFAULTS
    save_settings(BrokenConfig(), dict(DEFAULTS))     # must not raise


def test_settings_round_trip_through_the_host_config():
    config = FakeConfig()
    values = dict(DEFAULTS)
    values["decimals"] = 3
    values["unit"] = Unit.MB.value
    save_settings(config, values)
    assert load_settings(config)["decimals"] == 3
    assert load_settings(config)["unit"] == Unit.MB.value


def test_settings_are_namespaced_so_they_do_not_collide(qapp):
    config = FakeConfig()
    save_settings(config, dict(DEFAULTS))
    assert all(k.startswith("treesize.") for k in config._data)


def test_dialog_reports_what_was_set(qapp):
    dialog = OptionsDialog({"decimals": 2, "unit": Unit.GB.value,
                            "treemap_depth": 9})
    values = dialog.values()
    assert values["decimals"] == 2
    assert values["unit"] == Unit.GB.value
    assert values["treemap_depth"] == 9


def test_restore_defaults_puts_every_control_back(qapp):
    dialog = OptionsDialog({"decimals": 3, "unit": Unit.KB.value,
                            "treemap_depth": 11, "exclude_hidden": True})
    dialog.restore_defaults()
    assert dialog.values() == DEFAULTS


def test_an_unknown_stored_value_does_not_break_the_shell(qapp):
    """A value written by an older build must not stop the module opening."""
    shell = TreeSizeShell()
    shell.apply_settings({"unit": "PARSECS", "decimals": 1,
                          "mode": "Nonsense", "exclude_hidden": False,
                          "top_files_limit": 50, "treemap_depth": 4})
    assert shell.top_files._limit == 50


def test_applying_settings_reaches_the_widgets(qapp):
    shell = TreeSizeShell()
    shell.apply_settings({**DEFAULTS, "unit": Unit.MB.value, "decimals": 2,
                          "mode": Mode.FILES.value, "top_files_limit": 25,
                          "treemap_depth": 3, "exclude_hidden": True})
    assert shell.directory_tree.tree_model.unit is Unit.MB
    assert shell.directory_tree.tree_model.mode is Mode.FILES
    assert shell.top_files._limit == 25
    assert shell.chart.treemap.max_depth == 3
    assert shell._filters.exclude_hidden is True


def test_treemap_depth_setting_actually_limits_the_layout(qapp):
    from modules.treesize.store.node_store import NodeStore, DIR
    from modules.treesize.store.rollup import rollup
    from modules.treesize.ui.treemap import build_treemap

    store = NodeStore()
    node = store.add(-1, "C:", attrs=DIR)
    for i in range(10):
        node = store.add(node, f"d{i}", size=100, attrs=DIR)
    store.build_child_lists()
    rollup(store)
    shallow = build_treemap(store, 0, 400, 300, max_depth=2)
    deep = build_treemap(store, 0, 400, 300, max_depth=8)
    assert max(r.depth for r in shallow) <= 2
    assert max(r.depth for r in deep) > 2
