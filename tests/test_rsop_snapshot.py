"""Saving a Group Policy report, and diffing two of them.

Every test here is a behaviour someone depends on:

* a snapshot must come back exactly as it went in, or the diff invents changes,
* the list must not have to parse megabytes of JSON to fill a combo box,
* a snapshot from another build of the app must still open,
* and a scope that went from "we were refused" to "we could read it" must not
  be reported as hundreds of new settings on the machine.

`REAL_USER_ONLY` is the actual `gpresult /x` output of this standalone Windows
11 machine run unelevated -- computer half refused, exit code 0. `SETTINGS_XML`
carries the client-side-extension shapes a machine with configured policy
emits. Both go through the real parser, so what is snapshotted here is what
`rsop_parser` really produces rather than a hand-built approximation.
"""
import json
import os
import subprocess

import pytest

from modules.gpresult.rsop_parser import (
    ExtensionStatus, GpoInfo, PolicySetting, RsopResult, RsopScope,
    parse_rsop_xml,
)
from modules.gpresult.rsop_snapshot import (
    SCHEMA_VERSION, VISIBILITY_GAINED, VISIBILITY_LOST, default_snapshot_dir,
    delete_snapshot, diff_rsop, diff_snapshot_files, list_snapshots,
    load_snapshot, result_from_dict, result_to_dict, save_snapshot,
)

REAL_USER_ONLY = """<?xml version="1.0" encoding="utf-8"?>
<Rsop xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns="http://www.microsoft.com/GroupPolicy/Rsop">
  <ReadTime>2026-08-27T05:51:23.3134475Z</ReadTime>
  <DataType>LoggedData</DataType>
  <UserResults>
    <Version>2228228</Version>
    <Name>VRK\\iorda</Name>
    <Domain>Local</Domain>
    <SOM>Local</SOM>
    <SecurityGroup>
      <SID xmlns="http://www.microsoft.com/GroupPolicy/Types">S-1-1-0</SID>
      <Name xmlns="http://www.microsoft.com/GroupPolicy/Types">Everyone</Name>
    </SecurityGroup>
    <SlowLink>false</SlowLink>
    <ExtensionStatus>
      <Name>Group Policy Infrastructure</Name>
      <Identifier>{00000000-0000-0000-0000-000000000000}</Identifier>
      <BeginTime>2026-08-27T05:45:44</BeginTime>
      <EndTime>2026-08-27T05:45:44</EndTime>
      <LoggingStatus>Complete</LoggingStatus>
      <Error>0</Error>
    </ExtensionStatus>
    <GPO>
      <Name>Local Group Policy</Name>
      <Path>
        <Identifier xmlns="http://www.microsoft.com/GroupPolicy/Types">LocalGPO</Identifier>
      </Path>
      <VersionDirectory>0</VersionDirectory>
      <VersionSysvol>0</VersionSysvol>
      <Enabled>true</Enabled>
      <IsValid>true</IsValid>
      <FilterAllowed>true</FilterAllowed>
      <AccessDenied>false</AccessDenied>
      <Link>
        <SOMPath>Local</SOMPath>
        <AppliedOrder>0</AppliedOrder>
        <LinkOrder>1</LinkOrder>
        <NoOverride>false</NoOverride>
      </Link>
    </GPO>
  </UserResults>
</Rsop>
"""

SETTINGS_XML = """<?xml version="1.0" encoding="utf-8"?>
<Rsop xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xmlns="http://www.microsoft.com/GroupPolicy/Rsop">
  <ReadTime>2026-08-27T05:51:23Z</ReadTime>
  <DataType>LoggedData</DataType>
  <ComputerResults>
    <Name>VRK</Name>
    <Domain>Local</Domain>
    <GPO>
      <Name>Local Group Policy</Name>
      <Path><Identifier>LocalGPO</Identifier></Path>
      <Enabled>true</Enabled><IsValid>true</IsValid>
      <FilterAllowed>true</FilterAllowed><AccessDenied>false</AccessDenied>
      <Link><SOMPath>Local</SOMPath><AppliedOrder>0</AppliedOrder>
            <LinkOrder>1</LinkOrder><NoOverride>false</NoOverride></Link>
    </GPO>
    <GPO>
      <Name>Filtered Out</Name>
      <Path><Identifier>{31B2F340-016D-11D2-945F-00C04FB984F9}</Identifier></Path>
      <Enabled>true</Enabled><IsValid>true</IsValid>
      <FilterAllowed>false</FilterAllowed><AccessDenied>false</AccessDenied>
    </GPO>
    <ExtensionStatus>
      <Name>Registry</Name><LoggingStatus>Complete</LoggingStatus><Error>0</Error>
    </ExtensionStatus>
    <ExtensionStatus>
      <Name>Security</Name><LoggingStatus>Failed</LoggingStatus><Error>2</Error>
    </ExtensionStatus>
    <ExtensionData>
      <Extension xmlns:q1="http://www.microsoft.com/GroupPolicy/Settings/Registry"
                 xsi:type="q1:RegistrySettings">
        <q1:Policy>
          <q1:Name>Turn off Windows Error Reporting</q1:Name>
          <q1:State>Enabled</q1:State>
          <q1:Category>Windows Components/Windows Error Reporting</q1:Category>
          <q1:GPO><q1:Identifier>LocalGPO</q1:Identifier>
                  <q1:Name>Local Group Policy</q1:Name></q1:GPO>
        </q1:Policy>
        <q1:RegistrySetting>
          <q1:KeyPath>Software\\Policies\\Microsoft\\Windows\\SrpV2\\Exe</q1:KeyPath>
          <q1:Value><q1:Name>AllowWindows</q1:Name><q1:Number>0</q1:Number></q1:Value>
          <q1:GPO><q1:Name>Local Group Policy</q1:Name></q1:GPO>
        </q1:RegistrySetting>
        <q1:RegistrySetting>
          <q1:KeyPath>Software\\Policies\\Microsoft\\Windows\\SrpV2\\Msi</q1:KeyPath>
          <q1:Value><q1:Name>AllowWindows</q1:Name><q1:Number>0</q1:Number></q1:Value>
          <q1:GPO><q1:Name>Local Group Policy</q1:Name></q1:GPO>
        </q1:RegistrySetting>
      </Extension>
      <Extension xmlns:q2="http://www.microsoft.com/GroupPolicy/Settings/Security"
                 xsi:type="q2:SecuritySettings">
        <q2:UserRightsAssignment>
          <q2:Name>SeNetworkLogonRight</q2:Name>
          <q2:Member><q2:Name>BUILTIN\\Administrators</q2:Name></q2:Member>
          <q2:GPO><q2:Name>Local Group Policy</q2:Name></q2:GPO>
        </q2:UserRightsAssignment>
      </Extension>
    </ExtensionData>
  </ComputerResults>
  <UserResults>
    <Name>VRK\\iorda</Name>
  </UserResults>
</Rsop>
"""


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _rich_result():
    """A report exercising every field, including ones a real machine rarely
    sets, so the round-trip test cannot pass by only covering the common ones."""
    computer = RsopScope(
        scope="Computer", available=True, unavailable_reason="",
        name="VRK", domain="Local", som="Local", site="Default-First-Site",
        slow_link="false", version="65543",
        gpos=[GpoInfo(name="Local Group Policy", guid="LocalGPO",
                      enabled=True, is_valid=True, filter_allowed=True,
                      access_denied=False, som_path="Local",
                      applied_order="0", link_order="1", no_override=False,
                      version_directory="3", version_sysvol="3"),
              GpoInfo(name="Blocked", guid="{AAAA-BBBB}", enabled=False,
                      is_valid=False, filter_allowed=False, access_denied=True,
                      som_path="OU=Test", applied_order="2", link_order="2",
                      no_override=True, version_directory="9",
                      version_sysvol="8")],
        security_groups=[("S-1-1-0", "Everyone"),
                         ("S-1-5-32-544", "BUILTIN\\Administrators")],
        extensions=[ExtensionStatus(name="Registry", identifier="{35378EAC}",
                                    begin_time="2026-08-27T05:45:44",
                                    end_time="2026-08-27T05:45:45",
                                    logging_status="Complete", error="0"),
                    ExtensionStatus(name="Security", identifier="{827D319E}",
                                    begin_time="", end_time="",
                                    logging_status="Failed", error="1208")],
        settings=[PolicySetting(category="Registry Settings",
                                name="Software\\Policies\\X\\AllowWindows",
                                value="0", gpo="Local Group Policy",
                                details=[("KeyPath", "Software\\Policies\\X"),
                                         ("Value.Name", "AllowWindows")]),
                  PolicySetting(category="Unicode / odd", name="Ünïcödé — em",
                                value="Enabled", gpo="", details=[])])
    user = RsopScope(scope="User", available=False,
                     unavailable_reason="Not collected: needs elevation.")
    return RsopResult(computer=computer, user=user,
                      read_time="2026-08-27T05:51:23.3134475Z",
                      data_type="LoggedData", error="")


def _saved(tmp_path, result, label=""):
    return save_snapshot(result, label=label, directory=str(tmp_path))


# ------------------------------------------------------------------
# Where snapshots live
# ------------------------------------------------------------------

def test_the_default_directory_is_under_the_app_data_dir_and_is_not_created():
    """It must match `app.py:_get_app_data_dir` without importing `app` --
    importing it builds a Qt singleton and this module has to stay headless.
    Nothing is created just by asking where snapshots go."""
    path = default_snapshot_dir()
    assert path.endswith(os.path.join("WindowsTweaker", "gpresult_snapshots"))
    assert os.path.dirname(os.path.dirname(path)) == os.environ.get(
        "APPDATA", os.path.expanduser("~"))


def test_saving_creates_the_directory_when_it_does_not_exist(tmp_path):
    target = tmp_path / "nested" / "snapshots"
    meta = save_snapshot(RsopResult(), directory=str(target))
    assert os.path.exists(meta.path)


# ------------------------------------------------------------------
# Round trip
# ------------------------------------------------------------------

def test_every_field_survives_a_save_and_load(tmp_path):
    """Losslessness is not cosmetic: a field that comes back different is a
    change the diff will report on the next comparison."""
    original = _rich_result()
    meta = _saved(tmp_path, original, "baseline")
    assert load_snapshot(meta.path).result == original


def test_tuple_fields_come_back_as_tuples_not_lists(tmp_path):
    """JSON has no tuple type. `("a", "b") != ["a", "b"]`, so leaving these as
    lists would make every round-trip compare unequal."""
    original = _rich_result()
    loaded = load_snapshot(_saved(tmp_path, original).path).result
    assert loaded.computer.security_groups[0] == ("S-1-1-0", "Everyone")
    assert all(isinstance(g, tuple) for g in loaded.computer.security_groups)
    assert all(isinstance(d, tuple) for d in loaded.computer.settings[0].details)


def test_a_real_unelevated_gpresult_report_round_trips(tmp_path):
    """The half-refused report is the shape this machine actually produces:
    a user scope that was read and a computer scope that was not."""
    original = parse_rsop_xml(REAL_USER_ONLY)
    assert original.user.available and not original.computer.available
    loaded = load_snapshot(_saved(tmp_path, original).path).result
    assert loaded == original
    assert loaded.computer.available is False  # not lost to a falsy default


def test_a_report_carrying_settings_round_trips(tmp_path):
    original = parse_rsop_xml(SETTINGS_XML)
    assert len(original.computer.settings) == 4
    loaded = load_snapshot(_saved(tmp_path, original).path).result
    assert loaded == original


def test_the_label_and_timestamp_are_stored_with_the_snapshot(tmp_path):
    meta = _saved(tmp_path, _rich_result(), "before domain join")
    reloaded = load_snapshot(meta.path).meta
    assert reloaded.label == "before domain join"
    assert reloaded.taken_at == meta.taken_at
    assert reloaded.schema_version == SCHEMA_VERSION


def test_a_label_with_path_characters_cannot_escape_the_directory(tmp_path):
    """The label is the user's free text, so it never reaches the filename."""
    meta = _saved(tmp_path, RsopResult(), "../../evil: name\\here")
    assert os.path.dirname(os.path.abspath(meta.path)) == str(tmp_path)
    assert load_snapshot(meta.path).meta.label == "../../evil: name\\here"


def test_the_dict_conversion_is_reusable_on_its_own():
    """`result_to_dict` / `result_from_dict` are public so a caller can embed
    a report in some other document without going through a file."""
    original = _rich_result()
    assert result_from_dict(json.loads(json.dumps(result_to_dict(original)))) == original


# ------------------------------------------------------------------
# Listing
# ------------------------------------------------------------------

def test_snapshots_are_listed_newest_first(tmp_path):
    from datetime import datetime
    for day in (3, 1, 2):
        save_snapshot(RsopResult(), label="day%d" % day, directory=str(tmp_path),
                      taken_at=datetime(2026, 8, day, 12, 0, 0))
    assert [m.label for m in list_snapshots(str(tmp_path))] == ["day3", "day2", "day1"]


def test_listing_does_not_read_the_snapshot_payload(tmp_path):
    """An elevated report is megabytes of JSON and a pane may list twenty of
    them. The sidecar index is what makes the list cheap -- if the payload
    were being parsed, destroying it would break the listing."""
    meta = _saved(tmp_path, parse_rsop_xml(SETTINGS_XML), "indexed")
    with open(meta.path, "w", encoding="utf-8") as handle:
        handle.write("if you are reading this file, listing is not cheap")

    rows = list_snapshots(str(tmp_path))
    assert len(rows) == 1
    assert rows[0].label == "indexed"
    assert rows[0].setting_count == 4
    assert rows[0].error == ""


def test_the_summary_a_listing_shows_matches_the_report(tmp_path):
    meta = _saved(tmp_path, parse_rsop_xml(SETTINGS_XML))
    row = list_snapshots(str(tmp_path))[0]
    assert (row.computer_available, row.user_available) == (True, True)
    assert row.computer_name == "VRK"
    assert row.gpo_count == 2
    assert row.snapshot_id == meta.snapshot_id


def test_a_snapshot_with_no_index_sidecar_still_lists(tmp_path):
    """A hand-copied file, or one written before the sidecar existed, must not
    vanish from the user's history -- it falls back to the payload."""
    meta = _saved(tmp_path, parse_rsop_xml(SETTINGS_XML), "orphan")
    os.remove(meta.path.replace(".rsop.json", ".meta.json"))
    row = list_snapshots(str(tmp_path))[0]
    assert row.label == "orphan"
    assert row.setting_count == 4
    assert row.error == ""


def test_a_corrupt_snapshot_is_reported_as_a_row_not_a_crash(tmp_path):
    """Skipping it silently is how someone concludes their history was
    deleted; raising takes the whole list down with it."""
    good = _saved(tmp_path, RsopResult(), "good")
    bad = _saved(tmp_path, RsopResult(), "bad")
    with open(bad.path, "w", encoding="utf-8") as handle:
        handle.write("{ not json at all")
    os.remove(bad.path.replace(".rsop.json", ".meta.json"))

    rows = list_snapshots(str(tmp_path))
    assert len(rows) == 2
    broken = [r for r in rows if not r.readable]
    assert len(broken) == 1
    assert "Could not read this snapshot" in broken[0].error
    assert broken[0].taken_at  # from the mtime, so it still sorts
    assert [r for r in rows if r.readable][0].snapshot_id == good.snapshot_id


def test_a_corrupt_index_falls_back_to_the_snapshot_itself(tmp_path):
    """The sidecar is a cache. A damaged cache must not condemn a good file."""
    meta = _saved(tmp_path, parse_rsop_xml(SETTINGS_XML), "intact")
    with open(meta.path.replace(".rsop.json", ".meta.json"), "w",
              encoding="utf-8") as handle:
        handle.write("}{")
    row = list_snapshots(str(tmp_path))[0]
    assert row.error == ""
    assert row.label == "intact"
    assert row.setting_count == 4


def test_listing_a_directory_that_does_not_exist_is_empty_not_an_error(tmp_path):
    assert list_snapshots(str(tmp_path / "never-saved-anything")) == []


def test_loading_an_unreadable_file_reports_the_reason_instead_of_raising(tmp_path):
    """Same contract as `parse_rsop_xml`: the error lands on the object so a
    pane can show it in its banner."""
    missing = str(tmp_path / "rsop-nope.rsop.json")
    snapshot = load_snapshot(missing)
    assert snapshot.ok is False
    assert "Could not read this snapshot" in snapshot.meta.error
    assert "Could not read this snapshot" in snapshot.result.error


def test_deleting_a_snapshot_removes_its_index_too(tmp_path):
    meta = _saved(tmp_path, RsopResult(), "temporary")
    assert delete_snapshot(meta.path) is True
    assert list_snapshots(str(tmp_path)) == []
    assert os.listdir(str(tmp_path)) == []


# ------------------------------------------------------------------
# Compatibility, both directions
# ------------------------------------------------------------------

def test_a_snapshot_from_an_older_version_loads_with_defaults(tmp_path):
    """Backward compatibility. Fields this build knows about but the writer
    never stored take the dataclass default -- the alternative is a user
    losing their whole history on upgrade."""
    path = tmp_path / "rsop-ancient.rsop.json"
    path.write_text(json.dumps({
        # No schema_version, no counts, no taken_at, no data_type, and GPOs
        # and settings missing most of their fields.
        "label": "from an old build",
        "rsop": {"read_time": "2026-01-01T00:00:00Z",
                 "computer": {"available": True, "name": "OLDPC",
                              "gpos": [{"name": "Legacy GPO"}],
                              "settings": [{"name": "Some Setting",
                                            "value": "Enabled"}]}},
    }), encoding="utf-8")

    snapshot = load_snapshot(str(path))
    assert snapshot.ok
    assert snapshot.meta.label == "from an old build"
    assert snapshot.meta.taken_at  # filled in from the mtime
    assert snapshot.result.computer.name == "OLDPC"
    assert snapshot.result.data_type == ""
    gpo = snapshot.result.computer.gpos[0]
    assert (gpo.enabled, gpo.is_valid, gpo.filter_allowed) == (True, True, True)
    assert gpo.access_denied is False and gpo.applied is True
    assert snapshot.result.computer.settings[0].details == []
    # The user half was never written at all; it must still be a real scope.
    assert snapshot.result.user.scope == "User"
    assert snapshot.result.user.available is False


def test_an_older_snapshot_still_lists_with_counts_it_never_stored(tmp_path):
    path = tmp_path / "rsop-ancient.rsop.json"
    path.write_text(json.dumps({
        "label": "old", "rsop": {"computer": {
            "available": True, "name": "OLDPC",
            "gpos": [{"name": "A"}, {"name": "B"}],
            "settings": [{"name": "One"}, {"name": "Two"}, {"name": "Three"}]}},
    }), encoding="utf-8")
    row = list_snapshots(str(tmp_path))[0]
    assert (row.setting_count, row.gpo_count) == (3, 2)
    assert row.computer_available is True
    assert row.computer_name == "OLDPC"


def test_a_snapshot_from_a_newer_version_loads_and_ignores_what_it_adds(tmp_path):
    """Forward compatibility. Refusing a higher schema would strand anyone who
    downgraded the app, so unknown fields are ignored rather than fatal."""
    path = tmp_path / "rsop-future.rsop.json"
    path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION + 99,
        "label": "from the future",
        "taken_at": "2099-01-01T00:00:00",
        "quantum_entanglement": {"nonsense": True},
        "rsop": {
            "read_time": "2099-01-01T00:00:00Z",
            "telemetry_scope": {"available": True},   # a scope we know nothing of
            "computer": {
                "available": True, "name": "FUTUREPC", "hologram": 3,
                "gpos": [{"name": "Future GPO", "guid": "{F}",
                          "quantum_state": "superposed"}],
                "extensions": [{"name": "Ext", "error": "0", "novel": 1}],
                "settings": [{"category": "New", "name": "Thing",
                              "value": "On", "details": [["a", "b"]],
                              "confidence": 0.9}]}},
    }), encoding="utf-8")

    snapshot = load_snapshot(str(path))
    assert snapshot.ok
    assert snapshot.meta.schema_version == SCHEMA_VERSION + 99
    assert snapshot.meta.label == "from the future"
    assert snapshot.result.computer.name == "FUTUREPC"
    assert snapshot.result.computer.gpos[0].guid == "{F}"
    assert snapshot.result.computer.settings[0].details == [("a", "b")]
    assert snapshot.result.computer.extensions[0].failed is False


def test_wrongly_typed_fields_fall_back_instead_of_raising(tmp_path):
    """Nobody should be able to crash the pane by editing a file by hand."""
    path = tmp_path / "rsop-mangled.rsop.json"
    path.write_text(json.dumps({
        "schema_version": "not a number",
        "rsop": {"computer": {"available": "true", "name": 12345,
                              "gpos": "should have been a list",
                              "settings": [{"name": "S",
                                            "details": [["ok", "pair"],
                                                        ["bad", "triple", "x"],
                                                        "not a pair"]}],
                              "extensions": None}},
    }), encoding="utf-8")

    snapshot = load_snapshot(str(path))
    assert snapshot.ok
    assert snapshot.meta.schema_version == SCHEMA_VERSION
    assert snapshot.result.computer.available is True   # "true" coerced
    assert snapshot.result.computer.name == "12345"
    assert snapshot.result.computer.gpos == []
    assert snapshot.result.computer.settings[0].details == [("ok", "pair")]


# ------------------------------------------------------------------
# Diff -- settings
# ------------------------------------------------------------------

def _scope(settings=(), gpos=(), extensions=(), available=True, scope="Computer"):
    return RsopScope(scope=scope, available=available, settings=list(settings),
                     gpos=list(gpos), extensions=list(extensions))


def _result(computer=None, user=None):
    return RsopResult(computer=computer or _scope(available=False),
                      user=user or _scope(available=False, scope="User"))


def test_an_identical_pair_of_snapshots_reports_no_changes(tmp_path):
    original = parse_rsop_xml(SETTINGS_XML)
    a = _saved(tmp_path, original, "a")
    b = _saved(tmp_path, original, "b")
    diff = diff_snapshot_files(a.path, b.path)
    assert diff.has_changes is False
    assert diff.total_changes == 0
    assert diff.describe() == ["Computer: no changes", "User: no changes"]
    assert (diff.old_label, diff.new_label) == ("a", "b")


def test_a_new_setting_is_reported_as_added():
    old = _result(_scope([PolicySetting("Cat", "A", "1")]))
    new = _result(_scope([PolicySetting("Cat", "A", "1"),
                          PolicySetting("Cat", "B", "2")]))
    added = diff_rsop(old, new).computer.settings_added
    assert [(c.category, c.name, c.new_value) for c in added] == [("Cat", "B", "2")]


def test_a_vanished_setting_is_reported_as_removed():
    old = _result(_scope([PolicySetting("Cat", "A", "1"),
                          PolicySetting("Cat", "B", "2")]))
    new = _result(_scope([PolicySetting("Cat", "A", "1")]))
    removed = diff_rsop(old, new).computer.settings_removed
    assert [(c.name, c.old_value) for c in removed] == [("B", "2")]


def test_a_changed_setting_carries_the_old_and_the_new_value():
    old = _result(_scope([PolicySetting("Cat", "A", "Enabled", gpo="GPO-1")]))
    new = _result(_scope([PolicySetting("Cat", "A", "Disabled", gpo="GPO-2")]))
    changed = diff_rsop(old, new).computer.settings_changed
    assert len(changed) == 1
    assert (changed[0].old_value, changed[0].new_value) == ("Enabled", "Disabled")
    assert (changed[0].old_gpo, changed[0].new_gpo) == ("GPO-1", "GPO-2")
    assert changed[0].value_changed and changed[0].gpo_changed


def test_a_setting_whose_details_moved_is_changed_even_when_the_value_did_not():
    """`rsop_parser` summarises long member lists to four entries and a "...",
    so a fifth member changing is invisible in the value alone."""
    old = _result(_scope([PolicySetting("Sec", "SeRight", "A, B, C, D, ...",
                                        details=[("M", "E")])]))
    new = _result(_scope([PolicySetting("Sec", "SeRight", "A, B, C, D, ...",
                                        details=[("M", "F")])]))
    changed = diff_rsop(old, new).computer.settings_changed
    assert len(changed) == 1
    assert changed[0].details_changed is True
    assert changed[0].value_changed is False


def test_settings_are_keyed_on_category_and_name_together():
    """The same name under two categories is two settings, not one."""
    old = _result(_scope([PolicySetting("CatOne", "Same", "1"),
                          PolicySetting("CatTwo", "Same", "2")]))
    new = _result(_scope([PolicySetting("CatOne", "Same", "1"),
                          PolicySetting("CatTwo", "Same", "changed")]))
    diff = diff_rsop(old, new).computer
    assert len(diff.settings_changed) == 1
    assert diff.settings_changed[0].category == "CatTwo"


# ------------------------------------------------------------------
# Diff -- duplicate setting names
# ------------------------------------------------------------------

def _dupes(*values):
    """Several settings sharing one `(category, name)`, as SrpV2 really does."""
    return [PolicySetting("Registry Settings", "AllowWindows", v) for v in values]


def test_duplicate_setting_names_are_all_kept_through_a_save(tmp_path):
    """Five `AllowWindows` values live under different SrpV2 keys here. A
    dictionary keyed on the name alone would silently keep one of them."""
    original = _result(_scope(_dupes("0", "1", "2", "3", "4")))
    loaded = load_snapshot(_saved(tmp_path, original).path).result
    assert [s.value for s in loaded.computer.settings] == ["0", "1", "2", "3", "4"]


def test_only_the_duplicate_that_moved_is_reported_as_changed():
    old = _result(_scope(_dupes("0", "0", "0", "0", "0")))
    new = _result(_scope(_dupes("0", "0", "1", "0", "0")))
    diff = diff_rsop(old, new).computer
    assert len(diff.settings_changed) == 1
    assert (diff.settings_changed[0].old_value,
            diff.settings_changed[0].new_value) == ("0", "1")
    assert diff.settings_added == [] and diff.settings_removed == []


def test_reordering_duplicates_is_not_a_change():
    """Pairing duplicates by position alone would turn a reshuffled group of
    five into five bogus 'changed' rows."""
    old = _result(_scope(_dupes("a", "b", "c")))
    new = _result(_scope(_dupes("c", "a", "b")))
    assert diff_rsop(old, new).computer.total_changes == 0


def test_gaining_and_losing_a_duplicate_is_counted_once_each():
    old = _result(_scope(_dupes("a", "b")))
    new = _result(_scope(_dupes("a", "b", "c")))
    grew = diff_rsop(old, new).computer
    assert len(grew.settings_added) == 1 and grew.settings_added[0].new_value == "c"
    shrank = diff_rsop(new, old).computer
    assert len(shrank.settings_removed) == 1
    assert shrank.settings_removed[0].old_value == "c"


def test_a_duplicate_change_says_which_occurrence_it_was():
    """Otherwise the UI shows several identical-looking rows."""
    old = _result(_scope(_dupes("a", "b", "c")))
    new = _result(_scope(_dupes("a", "CHANGED", "c")))
    change = diff_rsop(old, new).computer.settings_changed[0]
    assert change.duplicates == 3
    assert change.occurrence == 2
    assert change.key == ("Registry Settings", "AllowWindows")


# ------------------------------------------------------------------
# Diff -- GPOs
# ------------------------------------------------------------------

def test_a_new_gpo_is_reported_as_added():
    old = _result(_scope(gpos=[GpoInfo(name="A", guid="{A}")]))
    new = _result(_scope(gpos=[GpoInfo(name="A", guid="{A}"),
                               GpoInfo(name="B", guid="{B}")]))
    diff = diff_rsop(old, new).computer
    assert [g.guid for g in diff.gpos_added] == ["{B}"]
    assert diff.gpos_added[0].old_applied is None
    assert diff.gpos_added[0].new_applied is True
    assert diff.gpos_added[0].flipped is False  # added, not flipped


def test_a_gpo_that_stopped_being_returned_is_reported_as_removed():
    old = _result(_scope(gpos=[GpoInfo(name="A", guid="{A}"),
                               GpoInfo(name="B", guid="{B}")]))
    new = _result(_scope(gpos=[GpoInfo(name="A", guid="{A}")]))
    removed = diff_rsop(old, new).computer.gpos_removed
    assert [g.guid for g in removed] == ["{B}"]
    assert removed[0].new_applied is None


def test_a_gpo_that_stopped_applying_is_reported_even_though_it_is_still_listed():
    """Windows lists the GPOs it *considered*. One that is still listed but no
    longer winning is invisible to a plain added/removed comparison, and it is
    exactly the thing someone is looking for."""
    old = _result(_scope(gpos=[GpoInfo(name="Policy", guid="{P}")]))
    new = _result(_scope(gpos=[GpoInfo(name="Policy", guid="{P}",
                                       filter_allowed=False)]))
    flipped = diff_rsop(old, new).computer.gpos_state_changed
    assert len(flipped) == 1
    assert (flipped[0].old_applied, flipped[0].new_applied) == (True, False)
    assert flipped[0].new_reason == "Denied by security filtering"
    assert flipped[0].flipped is True


def test_a_gpo_that_started_applying_is_reported_too():
    old = _result(_scope(gpos=[GpoInfo(name="Policy", guid="{P}",
                                       access_denied=True)]))
    new = _result(_scope(gpos=[GpoInfo(name="Policy", guid="{P}")]))
    flipped = diff_rsop(old, new).computer.gpos_state_changed[0]
    assert (flipped.old_applied, flipped.new_applied) == (False, True)
    assert flipped.old_reason == "Access denied"


def test_a_renamed_gpo_is_matched_on_its_guid_not_its_name():
    """A policy can be renamed without becoming a different policy."""
    old = _result(_scope(gpos=[GpoInfo(name="Old Name", guid="{SAME}")]))
    new = _result(_scope(gpos=[GpoInfo(name="New Name", guid="{SAME}")]))
    diff = diff_rsop(old, new).computer
    assert diff.gpos_added == [] and diff.gpos_removed == []


def test_gpos_without_a_guid_are_matched_on_their_name():
    """Otherwise every GUID-less GPO would collide on the empty string."""
    old = _result(_scope(gpos=[GpoInfo(name="One"), GpoInfo(name="Two")]))
    new = _result(_scope(gpos=[GpoInfo(name="One"), GpoInfo(name="Three")]))
    diff = diff_rsop(old, new).computer
    assert [g.name for g in diff.gpos_added] == ["Three"]
    assert [g.name for g in diff.gpos_removed] == ["Two"]


# ------------------------------------------------------------------
# Diff -- extensions
# ------------------------------------------------------------------

def test_an_extension_that_started_failing_is_reported():
    old = _result(_scope(extensions=[ExtensionStatus(name="Registry", error="0",
                                                     logging_status="Complete")]))
    new = _result(_scope(extensions=[ExtensionStatus(name="Registry", error="1208",
                                                     logging_status="Failed")]))
    changes = diff_rsop(old, new).computer.extension_changes
    assert len(changes) == 1
    assert changes[0].change == "status_changed"
    assert (changes[0].old_error, changes[0].new_error) == ("0", "1208")
    assert changes[0].started_failing is True


def test_an_extension_that_recovered_is_reported_but_not_as_a_failure():
    old = _result(_scope(extensions=[ExtensionStatus(name="Sec", error="1208")]))
    new = _result(_scope(extensions=[ExtensionStatus(name="Sec", error="0")]))
    change = diff_rsop(old, new).computer.extension_changes[0]
    assert change.old_failed is True and change.new_failed is False
    assert change.started_failing is False


def test_extension_timestamps_alone_are_not_a_change():
    """Begin/end times move on every policy refresh. Reporting them would mark
    every extension as changed on every diff and bury the one that broke."""
    old = _result(_scope(extensions=[ExtensionStatus(
        name="Registry", error="0", logging_status="Complete",
        begin_time="2026-08-27T05:45:44", end_time="2026-08-27T05:45:45")]))
    new = _result(_scope(extensions=[ExtensionStatus(
        name="Registry", error="0", logging_status="Complete",
        begin_time="2026-08-28T06:00:00", end_time="2026-08-28T06:00:01")]))
    assert diff_rsop(old, new).computer.extension_changes == []


def test_an_extension_appearing_or_disappearing_is_reported():
    old = _result(_scope(extensions=[ExtensionStatus(name="Registry", error="0")]))
    new = _result(_scope(extensions=[ExtensionStatus(name="Security", error="0")]))
    changes = diff_rsop(old, new).computer.extension_changes
    assert sorted((c.name, c.change) for c in changes) == [
        ("Registry", "removed"), ("Security", "added")]


# ------------------------------------------------------------------
# Diff -- availability, the case that would otherwise lie
# ------------------------------------------------------------------

def test_a_scope_that_became_readable_is_a_visibility_change_not_a_machine_change():
    """Running unelevated and then elevated makes hundreds of computer settings
    appear at once. Reporting them as *added* would say the machine changed
    when only our access to it did."""
    old = _result(computer=_scope(available=False))
    new = _result(computer=_scope([PolicySetting("Cat", "A"),
                                   PolicySetting("Cat", "B")],
                                  gpos=[GpoInfo(name="Local Group Policy")]))
    scope_diff = diff_rsop(old, new).computer
    assert scope_diff.visibility_change == VISIBILITY_GAINED
    assert scope_diff.comparable is False
    assert scope_diff.has_visibility_change is True
    assert scope_diff.settings_added == []
    assert scope_diff.gpos_added == []
    assert scope_diff.has_changes is False
    assert scope_diff.total_changes == 0


def test_a_visibility_change_still_says_how_much_became_visible():
    """The count is the useful part; it just must not be labelled 'added'."""
    new = _result(computer=_scope([PolicySetting("Cat", str(i)) for i in range(7)],
                                  gpos=[GpoInfo(name="A"), GpoInfo(name="B")]))
    scope_diff = diff_rsop(_result(), new).computer
    assert scope_diff.settings_behind_visibility == 7
    assert scope_diff.gpos_behind_visibility == 2
    assert "not a change on this machine" in scope_diff.visibility_note
    assert scope_diff.describe().startswith(
        "Computer: not collected before, collected now - 7 settings and 2 GPOs")


def test_a_scope_that_stopped_being_readable_is_labelled_the_other_way():
    """Elevated then unelevated: the settings did not go away, we did."""
    old = _result(computer=_scope([PolicySetting("Cat", "A")]))
    new_scope = _scope(available=False)
    new_scope.unavailable_reason = "requires an elevated run"
    scope_diff = diff_rsop(old, _result(computer=new_scope)).computer
    assert scope_diff.visibility_change == VISIBILITY_LOST
    assert scope_diff.settings_removed == []
    assert scope_diff.settings_behind_visibility == 1
    assert "requires an elevated run" in scope_diff.visibility_note


def test_a_scope_never_collected_in_either_snapshot_says_nothing_at_all():
    """Neither a change nor a visibility change -- there is no news here."""
    scope_diff = diff_rsop(_result(), _result()).computer
    assert scope_diff.has_changes is False
    assert scope_diff.has_visibility_change is False
    assert scope_diff.comparable is True
    assert scope_diff.describe() == "Computer: no changes"


def test_the_other_scope_is_still_diffed_normally_across_a_visibility_change():
    """A refused computer half must not stop the user half being compared."""
    old = _result(computer=_scope(available=False),
                  user=_scope([PolicySetting("Cat", "A", "1")], scope="User"))
    new = _result(computer=_scope([PolicySetting("Cat", "X")]),
                  user=_scope([PolicySetting("Cat", "A", "2")], scope="User"))
    diff = diff_rsop(old, new)
    assert diff.computer.has_visibility_change is True
    assert diff.user.comparable is True
    assert len(diff.user.settings_changed) == 1
    assert diff.total_changes == 1  # the user setting only
    assert diff.has_visibility_change is True


def test_the_real_unelevated_then_elevated_pair_reads_honestly(tmp_path):
    """The two reports this machine actually produces, in the order a user
    hits them: save unelevated, restart as admin, save again."""
    unelevated = parse_rsop_xml(REAL_USER_ONLY)
    elevated = parse_rsop_xml(SETTINGS_XML)
    before = _saved(tmp_path, unelevated, "unelevated")
    after = _saved(tmp_path, elevated, "elevated")

    diff = diff_snapshot_files(before.path, after.path)
    assert diff.computer.visibility_change == VISIBILITY_GAINED
    assert diff.computer.settings_behind_visibility == 4
    assert diff.computer.total_changes == 0
    assert diff.user.comparable is True  # both runs read the user half


# ------------------------------------------------------------------
# Summary line
# ------------------------------------------------------------------

def test_the_summary_line_pluralises_the_noun_not_the_phrase():
    old = _result(_scope([PolicySetting("Cat", "A"), PolicySetting("Cat", "B")]))
    new = _result(_scope([PolicySetting("Cat", "C"), PolicySetting("Cat", "D"),
                          PolicySetting("Cat", "E")]))
    line = diff_rsop(old, new).computer.describe()
    assert line == "Computer: 3 settings added, 2 settings removed"


def test_a_single_change_reads_in_the_singular():
    old = _result(_scope(gpos=[GpoInfo(name="A")]))
    new = _result(_scope(gpos=[GpoInfo(name="A"), GpoInfo(name="B")]))
    assert diff_rsop(old, new).computer.describe() == "Computer: 1 GPO added"


# ------------------------------------------------------------------
# Against the live machine
# ------------------------------------------------------------------

def _live_report():
    """`gpresult /x` on this machine, or None when it cannot be run.

    Read-only and safe: it reports policy, it never applies any. Unelevated it
    returns a user-scope-only report, which is itself the case worth pinning.
    """
    import tempfile
    import uuid
    path = os.path.join(tempfile.gettempdir(), "wct_test_%s.xml" % uuid.uuid4().hex)
    try:
        subprocess.run(["gpresult", "/x", path, "/f"], capture_output=True,
                       text=True, timeout=90)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return None
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_the_live_gpresult_report_survives_a_save_and_load(tmp_path):
    """The one test that is not fed a fixture. Whatever this machine reports
    -- half a report, an empty user scope, an extension nobody anticipated --
    must come back byte-identical as an object."""
    raw = _live_report()
    if raw is None:
        pytest.skip("gpresult produced no report on this machine")

    original = parse_rsop_xml(raw)
    assert original.error == ""
    meta = _saved(tmp_path, original, "live")

    loaded = load_snapshot(meta.path)
    assert loaded.ok
    assert loaded.result == original
    # And a snapshot of the same machine twice in a row shows nothing moving.
    assert diff_rsop(original, loaded.result).has_changes is False
    assert list_snapshots(str(tmp_path))[0].label == "live"
