import copy
import json
import logging
import os
import shutil
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

CURRENT_VERSION = 1


class ConfigManager:
    AUTOSAVE_DELAY_MS = 2000

    def __init__(self, config_dir: str, defaults: dict, event_bus=None):
        self._config_dir = config_dir
        self._defaults = defaults
        self._data: dict = {}
        self._event_bus = event_bus
        self._config_path = os.path.join(config_dir, "config.json")
        self._backup_path = os.path.join(config_dir, "config.json.bak")
        self._migrations: List[Tuple[int, Callable[[dict], dict]]] = []
        self._autosave_timer = None

    def _ensure_autosave_timer(self):
        if self._autosave_timer is None:
            try:
                from PyQt6.QtCore import QTimer
                self._autosave_timer = QTimer()
                self._autosave_timer.setSingleShot(True)
                self._autosave_timer.setInterval(self.AUTOSAVE_DELAY_MS)
                self._autosave_timer.timeout.connect(self.save)
            except ImportError:
                pass

    def register_migration(self, from_version: int, fn: Callable[[dict], dict]) -> None:
        self._migrations.append((from_version, fn))
        self._migrations.sort(key=lambda x: x[0])

    def load(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        loaded = self._try_load(self._config_path)
        if loaded is None:
            logger.warning("Config file corrupt or missing, trying backup")
            loaded = self._try_load(self._backup_path)
        if loaded is None:
            logger.warning("No valid config found, using defaults")
            loaded = copy.deepcopy(self._defaults)
        self._data = self._run_migrations(loaded)

    def _run_migrations(self, data: dict) -> dict:
        version = data.get("version", 1)
        for from_ver, migrate_fn in self._migrations:
            if version == from_ver:
                logger.info("Migrating config from v%d to v%d", from_ver, from_ver + 1)
                data = migrate_fn(data)
                data["version"] = from_ver + 1
                version = from_ver + 1
        return data

    def _try_load(self, path: str) -> Optional[dict]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def get(self, key: str, default=None) -> Any:
        keys = key.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        node = self._data
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        old_value = node.get(keys[-1])
        node[keys[-1]] = value
        if self._event_bus and old_value != value:
            from core.events import CONFIG_CHANGED, ConfigChangedData
            self._event_bus.publish(CONFIG_CHANGED, ConfigChangedData(key=key, old_value=old_value, new_value=value))
        self._ensure_autosave_timer()
        if self._autosave_timer is not None:
            self._autosave_timer.start()

    def get_module_config(self, module_name: str) -> dict:
        return self.get(f"modules.{module_name}", {})

    def save(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        if os.path.exists(self._config_path):
            shutil.copy2(self._config_path, self._backup_path)
        tmp_path = self._config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, self._config_path)

    def reset_to_defaults(self) -> None:
        self._data = copy.deepcopy(self._defaults)
