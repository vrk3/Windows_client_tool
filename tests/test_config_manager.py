import json
import os
import tempfile
import pytest
from core.config_manager import ConfigManager

@pytest.fixture
def config_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir

@pytest.fixture
def default_config():
    return {
        "version": 1,
        "app": {"theme": "dark", "window_size": [1400, 900], "log_level": "INFO"},
        "modules": {"enabled": []},
        "search": {"presets": {}},
    }

@pytest.fixture
def manager(config_dir, default_config):
    return ConfigManager(config_dir=config_dir, defaults=default_config)

def test_get_with_dot_notation(manager):
    manager.load()
    assert manager.get("app.theme") == "dark"
    assert manager.get("app.window_size") == [1400, 900]

def test_get_default_value(manager):
    manager.load()
    assert manager.get("nonexistent.key", "fallback") == "fallback"

def test_set_and_get(manager):
    manager.load()
    manager.set("app.theme", "light")
    assert manager.get("app.theme") == "light"

def test_get_module_config(manager):
    manager.load()
    manager.set("modules.process_explorer.refresh_rate", 2000)
    cfg = manager.get_module_config("process_explorer")
    assert cfg["refresh_rate"] == 2000

def test_save_creates_file(manager, config_dir):
    manager.load()
    manager.set("app.theme", "light")
    manager.save()
    config_path = os.path.join(config_dir, "config.json")
    assert os.path.exists(config_path)
    with open(config_path) as f:
        saved = json.load(f)
    assert saved["app"]["theme"] == "light"

def test_save_creates_backup(manager, config_dir):
    manager.load()
    manager.save()
    manager.set("app.theme", "light")
    manager.save()
    backup_path = os.path.join(config_dir, "config.json.bak")
    assert os.path.exists(backup_path)

def test_load_from_existing_file(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    custom = {**default_config, "app": {**default_config["app"], "theme": "light"}}
    with open(config_path, "w") as f:
        json.dump(custom, f)
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.load()
    assert mgr.get("app.theme") == "light"

def test_load_corrupt_file_falls_back_to_defaults(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    with open(config_path, "w") as f:
        f.write("{corrupt json!!!")
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.load()
    assert mgr.get("app.theme") == "dark"

def test_load_corrupt_file_uses_backup(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    backup_path = os.path.join(config_dir, "config.json.bak")
    backup = {**default_config, "app": {**default_config["app"], "theme": "custom"}}
    with open(backup_path, "w") as f:
        json.dump(backup, f)
    with open(config_path, "w") as f:
        f.write("corrupt!")
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.load()
    assert mgr.get("app.theme") == "custom"

def test_reset_to_defaults(manager, default_config):
    manager.load()
    manager.set("app.theme", "light")
    manager.reset_to_defaults()
    assert manager.get("app.theme") == "dark"

def test_version_field_preserved(manager):
    manager.load()
    assert manager.get("version") == 1

def test_migration_v1_to_v2(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    v1_config = {**default_config, "version": 1}
    with open(config_path, "w") as f:
        json.dump(v1_config, f)
    def migrate_v1_to_v2(data):
        data["app"]["new_field"] = "added_by_migration"
        return data
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.register_migration(1, migrate_v1_to_v2)
    mgr.load()
    assert mgr.get("version") == 2
    assert mgr.get("app.new_field") == "added_by_migration"
