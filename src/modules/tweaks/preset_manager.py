# src/modules/tweaks/preset_manager.py
import json
import logging
import os
import re
import zipfile
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_filename(name: str) -> str:
    """Convert preset name to a safe filename."""
    return re.sub(r'[^\w\-_. ]', '_', name).strip()[:80] + ".json"


class PresetManager:
    """Manages tweak presets: built-in (read-only) + user (read-write).

    Preset format:
        {"name": str, "version": 1, "builtin": bool, "description": str,
         "tweaks": {category: [tweak_id, ...]},
         "apps": {"remove": [...], "install": [...], "protected": [...]}}
    """

    def __init__(self, user_dir: Optional[str] = None,
                 builtins_dir: Optional[str] = None):
        if user_dir is None:
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
            user_dir = os.path.join(base, "WindowsTweaker", "presets")
        if builtins_dir is None:
            builtins_dir = os.path.join(
                os.path.dirname(__file__), "definitions", "builtins"
            )
        self._user_dir = user_dir
        self._builtins_dir = builtins_dir
        os.makedirs(self._user_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_presets(self) -> List[Dict]:
        """Return all presets (builtins first, then user), newest-last."""
        presets = []
        # Built-ins
        if os.path.isdir(self._builtins_dir):
            for fname in sorted(os.listdir(self._builtins_dir)):
                if fname.endswith(".json"):
                    path = os.path.join(self._builtins_dir, fname)
                    try:
                        with open(path, encoding="utf-8") as f:
                            data = json.load(f)
                        data["builtin"] = True
                        data["_path"] = path
                        presets.append(data)
                    except Exception as e:
                        logger.warning("Failed to load builtin %s: %s", fname, e)
        # User presets
        for fname in sorted(os.listdir(self._user_dir)):
            if fname.endswith(".json"):
                path = os.path.join(self._user_dir, fname)
                try:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    data.setdefault("builtin", False)
                    data["_path"] = path
                    presets.append(data)
                except Exception as e:
                    logger.warning("Failed to load preset %s: %s", fname, e)
        return presets

    def load_preset(self, name: str) -> Dict:
        """Load a preset by name. Raises KeyError if not found."""
        for preset in self.list_presets():
            if preset.get("name") == name:
                return preset
        raise KeyError(f"Preset '{name}' not found")

    # ------------------------------------------------------------------
    # Write (user presets only)
    # ------------------------------------------------------------------

    def save_preset(self, name: str, data: Dict) -> None:
        """Save or overwrite a user preset."""
        data = dict(data)
        data["name"] = name
        data.setdefault("version", 1)
        data.pop("builtin", None)
        data.pop("_path", None)
        path = os.path.join(self._user_dir, _safe_filename(name))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def delete_preset(self, name: str) -> None:
        """Delete a user preset. Raises ValueError for built-ins."""
        for preset in self.list_presets():
            if preset.get("name") == name:
                if preset.get("builtin"):
                    raise ValueError(f"Cannot delete built-in preset '{name}'")
                os.remove(preset["_path"])
                return
        raise KeyError(f"Preset '{name}' not found")

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_preset(self, name: str, dest_path: str) -> None:
        """Export preset to .json or .zip based on dest_path extension."""
        preset = self.load_preset(name)
        export_data = {k: v for k, v in preset.items()
                       if not k.startswith("_")}
        if dest_path.endswith(".zip"):
            with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("preset.json",
                            json.dumps(export_data, indent=2, ensure_ascii=False))
        else:
            with open(dest_path, "w", encoding="utf-8") as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)

    def import_preset(self, src_path: str) -> str:
        """Import a .json or .zip preset file. Returns the imported preset name."""
        if src_path.endswith(".zip"):
            with zipfile.ZipFile(src_path, "r") as zf:
                names = [n for n in zf.namelist() if n.endswith(".json")]
                if not names:
                    raise ValueError("No .json file found in ZIP")
                data = json.loads(zf.read(names[0]).decode("utf-8"))
        else:
            with open(src_path, encoding="utf-8") as f:
                data = json.load(f)

        name = data.get("name")
        if not name:
            raise ValueError("Preset has no 'name' field")
        self.save_preset(name, data)
        return name
