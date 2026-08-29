"""A baseline stages a diff and says what it skips; a profile does the same."""
import json

import pytest

from modules.security_dashboard.catalog.model import (
    Category, SecurityControl)
from modules.security_dashboard.profile import (
    export_profile, import_profile, read_profile, write_profile)


def _control(cid, value, **over):
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": value},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


@pytest.fixture
def catalog():
    return {c.id: c for c in (_control("a", True), _control("b", False),
                              _control("c", 3))}


@pytest.fixture
def catalog_with_unreadable(catalog):
    catalog["unreadable_one"] = _control(
        "unreadable_one", None,
        reader=lambda: {"available": False, "enabled": None})
    return catalog


def test_an_exported_profile_records_the_build_it_came_from(catalog):
    data = export_profile(catalog)
    assert data["os_build"] and data["app_version"]


def test_importing_stages_only_what_differs(catalog):
    data = export_profile(catalog)
    assert len(import_profile(data, catalog)) == 0, (
        "exporting and reimporting the same machine must stage nothing")


def test_an_unreadable_control_is_omitted_from_the_export(catalog_with_unreadable):
    """Exporting None as a value would import as 'set it to nothing'."""
    data = export_profile(catalog_with_unreadable)
    assert "unreadable_one" not in data["controls"]


# --- the rest are not in the plan ------------------------------------------


def test_what_could_not_be_read_is_still_named(catalog_with_unreadable):
    """Dropping it silently makes an export look complete when it is not."""
    data = export_profile(catalog_with_unreadable)
    assert "unreadable_one" in data["unreadable"]


def test_an_export_can_use_readings_the_caller_already_has(catalog):
    """Otherwise every export reads all 149 controls: 12.7s here."""
    for control in catalog.values():
        object.__setattr__(control, "reader",
                           lambda: pytest.fail("the machine was read again"))
    data = export_profile(catalog, readings={"a": True, "b": False, "c": 3})
    assert data["controls"] == {"a": True, "b": False, "c": 3}


def test_a_read_only_control_is_not_exported(catalog):
    catalog["fixed"] = _control("fixed", True, on_steps=(), off_steps=(),
                                read_only_reason="hardware")
    assert "fixed" not in export_profile(catalog)["controls"]


def test_a_profile_naming_a_control_this_build_lacks_is_ignored(catalog):
    data = {"version": 1, "controls": {"a": False, "gone_in_this_build": True}}
    staged = import_profile(data, catalog)
    assert [c.control_id for c in staged.changes] == ["a"]


def test_a_profile_round_trips_through_a_file(tmp_path, catalog):
    path = tmp_path / "p.json"
    write_profile(export_profile(catalog), str(path))
    assert read_profile(str(path))["controls"] == {"a": True, "b": False,
                                                   "c": 3}


def test_half_a_json_file_is_not_a_profile(tmp_path):
    path = tmp_path / "p.json"
    path.write_text('{"controls": {')
    assert read_profile(str(path)) is None


def test_valid_json_that_is_not_a_profile_is_refused(tmp_path):
    path = tmp_path / "p.json"
    path.write_text('["not", "a", "profile"]')
    assert read_profile(str(path)) is None


def test_a_profile_saved_by_a_windows_tool_still_loads(tmp_path, catalog):
    """Notepad and PowerShell's Out-File both write a UTF-8 BOM, and json.load
    refuses it: "Unexpected UTF-8 BOM". Found by running the FROZEN exe
    against a batch file PowerShell had written -- and "Import profile..."
    points at exactly the kind of file someone edits by hand.
    """
    path = tmp_path / "p.json"
    path.write_bytes(b"\xef\xbb\xbf" + b'{"version": 1, "controls": {"a": false}}')
    data = read_profile(str(path))
    assert data is not None and data["controls"] == {"a": False}
