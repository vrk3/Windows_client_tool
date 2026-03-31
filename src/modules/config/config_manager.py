"""Configuration manager for cleanup module.

Handles:
- User-customized cleanup rules
- Preset management
- Settings persistence
- Default rule merging
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from PyQt6.QtWidgets import QCheckBox, QPushButton, QVBoxLayout
from PyQt6.QtCore import QSettings, QDate


class ConfigManager:
    """Manages cleanup configuration and rules.

    Features:
    - Load/save user rules
    - Merge with defaults
    - Preset management
    - Export/import configs
    """

    _DEFAULT_CONFIG: Dict[str, Any] = {
        "user_cleanup": {
            "temp_files": True,
            "app_auto": True,
            "prefetch": True,
            "gpu_shuffle": True,
            "dev_tools": True,
        },
        "browser_caches": True,
        "windows_update": {
            "windows_update": True,
            "delivery_opt": True,
            "old_windows": True,
            "installer_cache": True,
        },
        "system_logs": {
            "windows_logs": True,
            "event_logs": True,
            "memory_dumps": True,
            "crash_dumps": True,
        },
        "performance": {
            "prefetch": True,
            "app_specific": True,
            "thumbnails": True,
        },
    }

    _CONFIG_PATH: Path = Path(
        os.environ.get("APPDATA", ""), "WindowsTweaker", "cleanup_config.json"
    )

    def __init__(self):
        self._config: Dict[str, Any] = {
            **self._DEFAULT_CONFIG,
            "presets": [],
            "settings": {
                "auto_refresh": True,
                "refresh_interval": 30,
                "show_suggestions": True,
                "export_csv": True,
                "export_pdf": True,
                "trash_retention_days": 30,
                "background_scan": True,
                "size_threshold_mb": 0,
                "age_threshold_days": 0,
                "expand_all_enabled": True,
            },
        }
        self._last_config: Dict[str, Any] = None
        self._load_config()

    def _load_config(self) -> None:
        """Load configuration from file."""
        Path(self._CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
        if self._CONFIG_PATH.exists():
            try:
                with open(self._CONFIG_PATH, "r", encoding="utf-8") as f:
                    user_config = json.load(f)
                self._config.update(**self._filter_user_config(user_config))
                self._last_config = self._config.copy()
            except Exception as e:
                print(f"Config loading error: {e}")

    def _filter_user_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Filter valid user config entries."""
        valid_keys = {
            "presets", "settings"
        }
        filtered = {"settings": {}, "presets": []}
        for key in valid_keys:
            if key in data:
                filtered[key] = data[key]
        return filtered

    def get_config(self) -> Dict# Dict[str, Any]]:
        """Get current configuration.

        Returns:
            Dictionary with merged default + user settings.
        """
        return self._config

    def get_enabled_categories(self) -> Dict[str, bool]:
        """Get list of enabled categories."""
        return {k: v for k, v in self._config.items() if isinstance(v, bool)}

    def should_clean_category(self, group: str, category: str) -> bool:
        """Check if specific category should be cleaned."""
        group_config = self._config.get(group, {})
        return group_config.get(category, self._DEFAULT_CONFIG.get(group, {}).get(category, True))

    def update_category(self, group: str, category: str, enabled: bool) -> None:
        """Update category enable/disable status.

        Args:
            group: Group name (user_cleanup, system_logs, etc.)
            category: Category identifier (temp_files, app_auto, etc.)
            enabled: True to enable, False to disable
        """
        if category not in self._config.get(group, {}):
            return

        self._config[group][category] = enabled
        self._save_config()

    def add_preset(self, name: str, categories: Dict[str, bool]) -> bool:
        """Add a cleanup preset.

        Returns:
            True if preset added successfully, False if duplicate.
        """
        for preset in self._config.get("presets", []):
            if preset["name"] == name:
                return False

        preset = {
            "name": name,
            "categories": categories,
            "auto_load": False,
            "description": "",
        }
        self._config["presets"].append(preset)
        self._save_config()
        return True

    def remove_preset(self, name: str) -> bool:
        """Remove preset by name.

        Returns:
            True if preset removed, False if not found.
        """
        original = len(self._config.get("presets", []))
        self._config["presets"] = [
            p for p in self._config.get("presets", []) if p["name"] != name
        ]
        saved = len(self._config.get("presets", [])) != original
        self._save_config()
        return saved

    def apply_preset(self, name: str) -> bool:
        """Apply preset configuration.

        Returns:
            True if preset found and applied.
        """
        for preset in self._config.get("presets", []):
            if preset["name"] == name:
                categories = preset.get("categories", {})
                groups = self._config.keys() - {"presets", "settings"}
                for group, cat_dict in self._config.items():
                    if group in groups:
                        for cat, enabled in categories.items():
                            if cat in cat_dict:
                                cat_dict[cat] = enabled
                self._save_config()
                return True
        return False

    def export_config(self, filepath: Optional[Path] = None) -> Path:
        """Export configuration to file.

        Returns:
            Path to exported file.
        """
        if filepath is None:
            filepath = Path(self._CONFIG_PATH).parent / "cleanup_config_export.json"

        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2)

        return filepath

    def import_config(self, filepath: Path) -> bool:
        """Import configuration from file.

        Returns:
            True if import successful.
        """
        if not filepath.exists():
            return False

        Path(self._CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                imported = json.load(f)
                self._config.update(**self._filter_user_config(imported))
                self._save_config()
                return True
        except Exception:
            return False

    def get_last_used_config(self) -> Dict[str, Any]:
        """Get last used configuration.

        Returns:
            Dictionary with last configuration.
        """
        return self._last_config if self._last_config else {}

    def merge_with_previous(self, base_path: Path) -> bool:
        """Merge with previous configuration.

        If previous config exists, merge valid entries.
        Returns True if merge successful.
        """
        if not base_path.exists():
            return False

        try:
            with open(base_path, "r", encoding="utf-8") as f:
                previous = json.load(f)
            # Merge only valid keys
            for key in ["presets", "settings"]:
                if key in previous and key in self._config:
                    self._config[key].update(previous[key])
            self._save_config()
            return True
        except Exception:
            return False

    def _save_config(self) -> None:
        """Save configuration to file.

        Ensures proper format and validity.
        """
        Path(self._CONFIG_PATH).parent.mkdir(parents=True, exist_ok=True)

        try:
            # Backup current config
            backup_path = self._CONFIG_PATH.with_name(
                f"cleanup_config_backup_{QDate.currentDate().toString('yyyyMMdd_hhmmss')}.json"
            )

            with open(self._CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)

            # Save backup
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2)
        except Exception as e:
            print(f"Config save error: {e}")
            # Restore backup if available
            backup_path = Path(str(self._CONFIG_PATH) + "_backup")
            if backup_path.exists():
                backup_path.rename(self._CONFIG_PATH)

    def get_trash_retention_days(self) -> int:
        """Get trash retention period in days.

        Returns:
            Number of days trash is retained.
        """
        return self._config.get("settings", {}).get("trash_retention_days", 30)

    def get_refresh_interval(self) -> int:
        """Get auto-refresh interval in seconds.

        Returns:
            Refresh interval in seconds.
        """
        return self._config.get("settings", {}).get("refresh_interval", 30)

    def get_auto_refresh_enabled(self) -> bool:
        """Get auto-refresh status.

        Returns:
            True if auto-refresh enabled.
        """
        return self._config.get("settings", {}).get("auto_refresh", True)

    def get_size_threshold_mb(self) -> int:
        """Get minimum size threshold for cleanup.

        Returns:
            Size in MB (0 = no threshold).
        """
        return self._config.get("settings", {}).get("size_threshold_mb", 0)

    def get_age_threshold_days(self) -> int:
        """Get minimum age threshold for cleanup.

        Returns:
            Age in days (0 = no threshold).
        """
        return self._config.get("settings", {}).get("age_threshold_days", 0)

    def get_background_scan_enabled(self) -> bool:
        """Get background scan status.

        Returns:
            True if background scan enabled.
        """
        return self._config.get("settings", {}).get("background_scan", True)

    def get_expand_all_enabled(self) -> bool:
        """Get expand all button status.

        Returns:
            True if expand all enabled.
        """
        return self._config.get("settings", {}).get("expand_all_enabled", True)

    def get_all_categories(self) -> dict:
        """Get all categories grouped by tab."""
        groups = {}
        for key in self._config:
            if isinstance(self._config[key], dict):
                groups[key] = self._config[key]
        return groups

    def set_trash_retention_days(self, days: int) -> None:
        """Set trash retention period.

        Args:
            days: Number of days to retain trash.
        """
        self._config["settings"]["trash_retention_days"] = days
        self._save_config()

    def set_refresh_interval(self, interval: int) -> None:
        """Set auto-refresh interval.

        Args:
            interval: Interval in seconds.
        """
        self._config["settings"]["refresh_interval"] = interval
        self._save_config()

    def reset_to_defaults(self) -> None:
        """Reset configuration to defaults.

        Preserves presets.
        """
        self._config = {
            **self._DEFAULT_CONFIG,
            "presets": self._config.get("presets", []),
            "settings": self._copy_settings_from_last(),
        }
        self._save_config()

    def _copy_settings_from_last(self) -> Dict[str, Any]:
        """Copy settings from last configuration.

        Returns:
            Settings dictionary.
        """
        return self._DEFAULT_CONFIG.get("settings", {})

</div>
