"""Spec 3.6: "Exclusions are either temporary -- this scan only -- or
permanent, persisted through `ConfigManager`."

Every exclusion was temporary. There was no permanent kind at all: the Exclude
menu appended to an in-memory tuple that died with the widget, so a rule the
user set up to keep node_modules out of every future scan lasted until they
switched modules and back.
"""
import pytest

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


@pytest.fixture
def shell(qapp):
    s = TreeSizeShell()
    s.config = FakeConfig()
    return s


# ---- the setting itself -------------------------------------------------

def test_the_permanent_list_is_a_setting():
    assert DEFAULTS["exclude_patterns"] == []


def test_it_round_trips_through_the_config_manager():
    config = FakeConfig()
    save_settings(config, {"exclude_patterns": ["node_modules", "*.tmp"]})
    assert load_settings(config)["exclude_patterns"] == ["node_modules", "*.tmp"]


def test_the_dialog_round_trips_the_list(qapp):
    settings = dict(DEFAULTS, exclude_patterns=["node_modules", "*.iso"])
    dialog = OptionsDialog(settings)
    assert dialog.values()["exclude_patterns"] == ["node_modules", "*.iso"]


def test_the_dialog_ignores_empty_entries(qapp):
    """A trailing comma is a typo, not a rule matching everything."""
    dialog = OptionsDialog(dict(DEFAULTS))
    dialog.exclude_patterns.setText("a, ,b,")
    assert dialog.values()["exclude_patterns"] == ["a", "b"]


# ---- the two kinds ------------------------------------------------------

def test_permanent_rules_reach_the_filters(shell):
    shell.apply_settings(dict(DEFAULTS, exclude_patterns=["node_modules"]))
    assert "node_modules" in shell._filters.exclude_globs


def test_a_temporary_rule_is_not_persisted(shell):
    shell.add_exclusion("*.tmp", permanent=False)
    assert "*.tmp" in shell._filters.exclude_globs
    assert shell.config.get("treesize.exclude_patterns") is None


def test_a_permanent_rule_is_persisted(shell):
    shell.add_exclusion("node_modules", permanent=True)
    assert shell.config.get("treesize.exclude_patterns") == ["node_modules"]


def test_both_kinds_apply_at_once(shell):
    shell.add_exclusion("node_modules", permanent=True)
    shell.add_exclusion("*.tmp", permanent=False)
    assert set(shell._filters.exclude_globs) == {"node_modules", "*.tmp"}


def test_a_permanent_rule_is_not_added_twice(shell):
    shell.add_exclusion("node_modules", permanent=True)
    shell.add_exclusion("node_modules", permanent=True)
    assert shell.config.get("treesize.exclude_patterns") == ["node_modules"]


def test_a_blank_rule_is_refused(shell):
    """An empty glob matches nothing in fnmatch, but a rule that silently
    does nothing is worse than no rule at all in a tool that deletes things."""
    assert shell.add_exclusion("   ", permanent=True) is False
    assert shell._filters.exclude_globs == ()


# ---- clearing -----------------------------------------------------------

def test_clearing_temporary_leaves_the_permanent_rules(shell):
    """The whole point of the distinction: "undo what I did for this scan"
    must not throw away the standing rules."""
    shell.add_exclusion("node_modules", permanent=True)
    shell.add_exclusion("*.tmp", permanent=False)
    shell.clear_exclusions(permanent=False)
    assert shell._filters.exclude_globs == ("node_modules",)
    assert shell.config.get("treesize.exclude_patterns") == ["node_modules"]


def test_clearing_permanent_persists_the_removal(shell):
    shell.add_exclusion("node_modules", permanent=True)
    shell.clear_exclusions(permanent=True)
    assert shell._filters.exclude_globs == ()
    assert shell.config.get("treesize.exclude_patterns") == []


def test_permanent_rules_survive_a_fresh_pane(qapp):
    """A new pane on the same config is what "persisted" has to mean --
    switching modules and back used to lose everything."""
    config = FakeConfig()
    first = TreeSizeShell()
    first.config = config
    first.add_exclusion("node_modules", permanent=True)

    second = TreeSizeShell()
    second.config = config
    second.apply_settings(load_settings(config))
    assert "node_modules" in second._filters.exclude_globs
