"""The cleanup module's settings, and the two things that were wrong.

There were two classes called `ConfigManager` in the tree —
`core/config_manager.py`, which owns the application config (versioned,
migratable, autosaving, event-bus aware), and this one, which holds cleanup
rules and presets. Same name, different jobs, and an import line that reads
identically either way.

It also imported QCheckBox, QPushButton, QVBoxLayout and QSettings and used
none of them. "The only QSettings user in the tree" turned out to be a dead
import, not a second persistence mechanism.

And its config backup was named with `QDate.toString("yyyyMMdd_hhmmss")`.
QDate carries no time, so the time specifiers rendered LITERALLY: every
backup this has ever written went to
`cleanup_config_backup_<date>_hhmmss.json` and overwrote the one before it.
"""
import copy
import re


from modules.cleanup import cleanup_config as cc


def test_the_class_no_longer_shares_a_name_with_the_app_config():
    assert hasattr(cc, "CleanupConfig")
    from core.config_manager import ConfigManager as AppConfigManager
    assert cc.CleanupConfig is not AppConfigManager


def test_the_old_name_still_resolves():
    """An import that predates the rename must not fail at startup."""
    assert cc.ConfigManager is cc.CleanupConfig


def test_it_no_longer_depends_on_qt():
    """A settings file has no business importing widgets. Keeping it Qt-free
    is also what lets it be tested without a display."""
    import ast
    import pathlib

    source = pathlib.Path(cc.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PyQt6" not in imported, f"imports {sorted(imported)}"


def test_the_backup_filename_carries_a_real_timestamp(tmp_path, monkeypatch):
    """QDate.toString('yyyyMMdd_hhmmss') renders '20260902_hhmmss' — the
    time specifiers come out as the letters themselves, so every backup
    collided on one filename."""
    config_path = tmp_path / "cleanup_config.json"
    monkeypatch.setattr(cc.CleanupConfig, "_CONFIG_PATH", config_path,
                        raising=False)

    manager = cc.CleanupConfig()
    monkeypatch.setattr(manager, "_CONFIG_PATH", config_path, raising=False)
    manager._save_config()

    backups = list(tmp_path.glob("cleanup_config_backup_*.json"))
    assert backups, "no backup written"
    name = backups[0].name
    assert "hhmmss" not in name, f"literal time specifiers in {name}"
    assert re.search(r"_\d{8}_\d{6}\.json$", name), name


def test_two_saves_do_not_collide_on_one_backup(tmp_path, monkeypatch):
    """The consequence of the bug: the previous backup was the only one, and
    it was overwritten by every save."""
    config_path = tmp_path / "cleanup_config.json"
    manager = cc.CleanupConfig()
    monkeypatch.setattr(manager, "_CONFIG_PATH", config_path, raising=False)

    stamps = iter(["20260902_120000", "20260902_120001"])
    monkeypatch.setattr(
        cc.datetime, "datetime",
        type("D", (), {"now": staticmethod(
            lambda: type("N", (), {"strftime": staticmethod(
                lambda _fmt: next(stamps))})())}))

    manager._save_config()
    manager._save_config()

    backups = sorted(p.name for p in tmp_path.glob("cleanup_config_backup_*.json"))
    assert len(backups) == 2, f"saves collided: {backups}"


# ---------------------------------------------------------------------------
# The class-level default was being edited in place.
#
# `__init__` and `reset_to_defaults` both seed `self._config` with
# `{**self._DEFAULT_CONFIG, ...}`, which is a SHALLOW copy: the top-level
# keys are new, the group dicts under them are the very objects hanging off
# the class. `update_category` then writes through one of them with
# `self._config[group][category] = enabled`.
#
# So toggling a category rewrote the default. Two consequences, and the
# second is the one a user meets: `should_clean_category` falls back to
# `_DEFAULT_CONFIG` for anything it cannot find, and `reset_to_defaults`
# rebuilds from it -- so Reset could not restore a category the user had
# changed, because the thing it resets to had already been changed too.
# ---------------------------------------------------------------------------


def _isolated(tmp_path, monkeypatch):
    """A config whose file and whose class default are this test's alone."""
    monkeypatch.setattr(cc.CleanupConfig, "_DEFAULT_CONFIG",
                        copy.deepcopy(cc.CleanupConfig._DEFAULT_CONFIG))
    monkeypatch.setattr(cc.CleanupConfig, "_CONFIG_PATH",
                        tmp_path / "cleanup_config.json")
    return cc.CleanupConfig()


def test_changing_a_category_does_not_edit_the_class_default(tmp_path, monkeypatch):
    manager = _isolated(tmp_path, monkeypatch)
    was = cc.CleanupConfig._DEFAULT_CONFIG["user_cleanup"]["temp_files"]

    manager.update_category("user_cleanup", "temp_files", not was)

    assert cc.CleanupConfig._DEFAULT_CONFIG["user_cleanup"]["temp_files"] == was, \
        "the default is the thing we compare against; it must not move"


def test_reset_to_defaults_restores_a_changed_category(tmp_path, monkeypatch):
    manager = _isolated(tmp_path, monkeypatch)
    was = manager.should_clean_category("user_cleanup", "temp_files")

    manager.update_category("user_cleanup", "temp_files", not was)
    assert manager.should_clean_category("user_cleanup", "temp_files") == (not was)

    manager.reset_to_defaults()
    assert manager.should_clean_category("user_cleanup", "temp_files") == was


def test_two_managers_do_not_share_their_category_settings(tmp_path, monkeypatch):
    first = _isolated(tmp_path, monkeypatch)
    was = first.should_clean_category("user_cleanup", "temp_files")
    first.update_category("user_cleanup", "temp_files", not was)

    second = cc.CleanupConfig()
    assert second.should_clean_category("user_cleanup", "temp_files") == was, \
        "a second manager reads the defaults, not the first one's edits"


def test_reset_to_defaults_restores_the_settings_rather_than_emptying_them(tmp_path, monkeypatch):
    """`_DEFAULT_CONFIG` has no "settings" key -- the settings block was a
    literal inside __init__ -- so reset read `.get("settings", {})` and
    assigned an empty dict. Every getter has its own hardcoded fallback, so
    this degraded quietly instead of raising."""
    manager = _isolated(tmp_path, monkeypatch)

    manager.set_trash_retention_days(7)
    assert manager.get_trash_retention_days() == 7

    manager.reset_to_defaults()

    settings = manager.get_config()["settings"]
    assert settings, "reset must leave the defaults behind, not an empty dict"
    assert settings["trash_retention_days"] == 30
    assert settings["refresh_interval"] == 30


def test_reset_to_defaults_keeps_the_presets(tmp_path, monkeypatch):
    """The docstring promises it, and nothing checked."""
    manager = _isolated(tmp_path, monkeypatch)
    manager.add_preset("mine", {"user_cleanup": True})

    manager.reset_to_defaults()

    names = [p.get("name") for p in manager.get_config()["presets"]]
    assert "mine" in names
