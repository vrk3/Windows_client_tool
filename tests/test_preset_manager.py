# tests/test_preset_manager.py
import json, os, pytest, zipfile


@pytest.fixture
def manager(tmp_path):
    from modules.tweaks.preset_manager import PresetManager
    builtins_dir = os.path.join(
        os.path.dirname(__file__), "..", "src",
        "modules", "tweaks", "definitions", "builtins"
    )
    return PresetManager(user_dir=str(tmp_path / "presets"),
                         builtins_dir=os.path.abspath(builtins_dir))


def test_list_presets_includes_builtins(manager):
    presets = manager.list_presets()
    names = [p["name"] for p in presets]
    assert "Minimal" in names
    assert "Privacy Focused" in names


def test_builtin_presets_are_readonly(manager):
    presets = manager.list_presets()
    builtins = [p for p in presets if p.get("builtin")]
    assert all(p["builtin"] for p in builtins)


def test_save_and_load_user_preset(manager):
    data = {
        "name": "My Preset", "version": 1,
        "tweaks": {"privacy": ["disable_location"]},
        "apps": {"remove": [], "install": [], "protected": []}
    }
    manager.save_preset("My Preset", data)
    loaded = manager.load_preset("My Preset")
    assert loaded["tweaks"]["privacy"] == ["disable_location"]


def test_delete_user_preset(manager):
    data = {"name": "Temp", "version": 1, "tweaks": {}, "apps": {"remove":[],"install":[],"protected":[]}}
    manager.save_preset("Temp", data)
    manager.delete_preset("Temp")
    presets = manager.list_presets()
    assert all(p["name"] != "Temp" for p in presets)


def test_delete_builtin_raises(manager):
    with pytest.raises(ValueError, match="built-in"):
        manager.delete_preset("Minimal")


def test_export_json(manager, tmp_path):
    data = {"name": "Export Test", "version": 1, "tweaks": {}, "apps": {"remove":[],"install":[],"protected":[]}}
    manager.save_preset("Export Test", data)
    out = tmp_path / "export.json"
    manager.export_preset("Export Test", str(out))
    loaded = json.loads(out.read_text())
    assert loaded["name"] == "Export Test"


def test_export_zip(manager, tmp_path):
    data = {"name": "Zip Test", "version": 1, "tweaks": {}, "apps": {"remove":[],"install":[],"protected":[]}}
    manager.save_preset("Zip Test", data)
    out = tmp_path / "export.zip"
    manager.export_preset("Zip Test", str(out))
    assert zipfile.is_zipfile(str(out))


def test_import_json_preset(manager, tmp_path):
    data = {"name": "Imported", "version": 1, "tweaks": {"privacy": ["x"]}, "apps": {"remove":[],"install":[],"protected":[]}}
    f = tmp_path / "imp.json"
    f.write_text(json.dumps(data))
    manager.import_preset(str(f))
    loaded = manager.load_preset("Imported")
    assert loaded["tweaks"]["privacy"] == ["x"]


def test_import_zip_preset(manager, tmp_path):
    data = {"name": "ZipImport", "version": 1, "tweaks": {}, "apps": {"remove":[],"install":[],"protected":[]}}
    zp = tmp_path / "imp.zip"
    with zipfile.ZipFile(str(zp), "w") as zf:
        zf.writestr("preset.json", json.dumps(data))
    manager.import_preset(str(zp))
    loaded = manager.load_preset("ZipImport")
    assert loaded["name"] == "ZipImport"
