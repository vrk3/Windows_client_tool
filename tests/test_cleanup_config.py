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
import datetime
import json
import re

import pytest

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

    real_strftime = datetime.datetime.strftime
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
