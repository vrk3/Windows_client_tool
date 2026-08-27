"""The RSOP parser and runner, against real gpresult output shapes.

Every test here corresponds to something the previous Group Policy pane got
wrong on this machine, so they are written to fail if it comes back:

* user results reported as computer results,
* a refused scope reported as an empty one,
* the GUID column blank because the parser looked at `Identifier/Identifier`
  when the document says `Path/Identifier`,
* settings parsed into a key nothing ever read.

The `REAL_*` constant is the actual `gpresult /x` output of a standalone
Windows 11 Pro machine, byte for byte apart from indentation. The
`SETTINGS_XML` constant carries the client-side-extension shapes that a
machine with configured policy emits.
"""
import subprocess

import pytest

from modules.gpresult.rsop_parser import parse_rsop_xml
from modules.gpresult import rsop_runner
from modules.gpresult.rsop_runner import (
    collect_rsop, export_html_report, mmc_console_path, run_gpresult_xml,
)

# Real output of `gpresult /x` run unelevated: it exits 0, writes a valid
# report, and the report has no <ComputerResults> in it at all.
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
        <SOMOrder>1</SOMOrder>
        <AppliedOrder>0</AppliedOrder>
        <LinkOrder>1</LinkOrder>
        <Enabled>true</Enabled>
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
    <GPO>
      <Name>Unreadable</Name>
      <Path><Identifier>{AAAAAAAA-0000-0000-0000-00000000FFFF}</Identifier></Path>
      <Enabled>true</Enabled><IsValid>true</IsValid>
      <FilterAllowed>true</FilterAllowed><AccessDenied>true</AccessDenied>
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
      <Extension xmlns:q9="http://www.microsoft.com/GroupPolicy/Settings/Future"
                 xsi:type="q9:UnheardOfSettings">
        <q9:WidgetConfiguration>
          <q9:Widget>Frobnicator</q9:Widget>
          <q9:Level>11</q9:Level>
        </q9:WidgetConfiguration>
      </Extension>
    </ExtensionData>
  </ComputerResults>
  <UserResults>
    <Name>VRK\\iorda</Name>
  </UserResults>
</Rsop>
"""


# ------------------------------------------------------------------
# Scope separation
# ------------------------------------------------------------------

def test_user_results_are_not_reported_as_computer_results():
    """The old parser called root.iter() once and filed everything under
    computer_gpos, so this machine's single user GPO was shown as a computer
    GPO."""
    result = parse_rsop_xml(REAL_USER_ONLY)
    assert result.user.name == "VRK\\iorda"
    assert [g.name for g in result.user.gpos] == ["Local Group Policy"]
    assert result.computer.gpos == []


def test_a_refused_scope_is_not_an_empty_scope():
    """Unelevated the computer half is refused, not absent-because-unset.
    `available` has to carry that difference; an empty list cannot."""
    result = parse_rsop_xml(REAL_USER_ONLY)
    assert result.computer.available is False
    assert result.user.available is True


def test_both_scopes_parse_when_both_are_present():
    result = parse_rsop_xml(SETTINGS_XML)
    assert result.computer.available and result.user.available
    assert result.computer.name == "VRK"
    assert result.user.name == "VRK\\iorda"


def test_header_fields_are_read():
    result = parse_rsop_xml(REAL_USER_ONLY)
    assert result.read_time.startswith("2026-08-27T05:51:23")
    assert result.data_type == "LoggedData"


# ------------------------------------------------------------------
# GPOs
# ------------------------------------------------------------------

def test_guid_comes_from_path_identifier():
    """The document nests it as Path/Identifier. The old parser looked for
    Identifier/Identifier and then GUID, found neither, and left the column
    blank for every row on every machine."""
    gpo = parse_rsop_xml(REAL_USER_ONLY).user.gpos[0]
    assert gpo.guid == "LocalGPO"


def test_link_metadata_is_read():
    gpo = parse_rsop_xml(REAL_USER_ONLY).user.gpos[0]
    assert gpo.som_path == "Local"
    assert gpo.applied_order == "0"
    assert gpo.link_order == "1"
    assert gpo.no_override is False


def test_gpos_windows_considered_but_did_not_apply_are_split_out():
    """Windows lists every GPO it evaluated. Showing a filtered-out or
    unreadable one under "Applied" is a lie about the machine's state."""
    computer = parse_rsop_xml(SETTINGS_XML).computer
    assert [g.name for g in computer.applied_gpos] == ["Local Group Policy"]
    denied = {g.name: g.denied_reason for g in computer.denied_gpos}
    assert denied == {
        "Filtered Out": "Denied by security filtering",
        "Unreadable": "Access denied",
    }


# ------------------------------------------------------------------
# Extension status
# ------------------------------------------------------------------

def test_a_nonzero_extension_error_is_a_failure():
    computer = parse_rsop_xml(SETTINGS_XML).computer
    by_name = {e.name: e for e in computer.extensions}
    assert by_name["Registry"].failed is False
    assert by_name["Security"].failed is True
    assert by_name["Security"].error == "2"


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def test_administrative_template_policies_carry_name_state_and_category():
    settings = parse_rsop_xml(SETTINGS_XML).computer.settings
    policy = next(s for s in settings
                  if s.name == "Turn off Windows Error Reporting")
    assert policy.value == "Enabled"
    assert policy.category == "Windows Components/Windows Error Reporting"
    assert policy.gpo == "Local Group Policy"


def test_registry_settings_are_named_by_key_and_value():
    """Five SrpV2 keys on this machine all carry a value called
    "AllowWindows". Named by the value alone they are five identical rows."""
    settings = parse_rsop_xml(SETTINGS_XML).computer.settings
    names = [s.name for s in settings if "SrpV2" in s.name]
    assert names == [
        "Software\\Policies\\Microsoft\\Windows\\SrpV2\\Exe\\AllowWindows",
        "Software\\Policies\\Microsoft\\Windows\\SrpV2\\Msi\\AllowWindows",
    ]
    assert all(s.value == "0" for s in settings if "SrpV2" in s.name)


def test_a_setting_with_no_state_element_still_shows_its_content():
    """A user rights assignment has no <State>; its members are the value."""
    settings = parse_rsop_xml(SETTINGS_XML).computer.settings
    right = next(s for s in settings if s.name == "SeNetworkLogonRight")
    assert "BUILTIN\\Administrators" in right.value


def test_an_unknown_extension_still_surfaces_its_data():
    """There are dozens of client-side extensions and each defines its own
    schema. One we cannot name must still show its content rather than
    vanishing, which is what the old parser did to all of them."""
    settings = parse_rsop_xml(SETTINGS_XML).computer.settings
    widget = next(s for s in settings if s.category == "Unheard Of Settings")
    assert "Frobnicator" in widget.value
    assert ("Widget", "Frobnicator") in widget.details
    assert ("Level", "11") in widget.details


def test_every_setting_keeps_its_full_subtree():
    for setting in parse_rsop_xml(SETTINGS_XML).computer.settings:
        assert setting.details, setting.name


def test_the_winning_gpo_is_not_mistaken_for_the_setting_name():
    """<GPO><Name> sits inside the setting. Taking the first <Name> in
    document order would name half the tree "Local Group Policy"."""
    for setting in parse_rsop_xml(SETTINGS_XML).computer.settings:
        assert setting.name != "Local Group Policy"


# ------------------------------------------------------------------
# Malformed input
# ------------------------------------------------------------------

def test_broken_xml_is_reported_not_raised():
    result = parse_rsop_xml("<Rsop><UserResults></Rsop>")
    assert result.error
    assert result.computer.available is False


def test_missing_file_is_reported_not_raised(tmp_path):
    result = parse_rsop_xml(str(tmp_path / "nope.xml"))
    assert result.error


def test_utf16_output_is_read(tmp_path):
    """gpresult writes UTF-16. A parser that assumes UTF-8 sees line noise."""
    path = tmp_path / "utf16.xml"
    path.write_bytes(REAL_USER_ONLY.replace(
        'encoding="utf-8"', 'encoding="utf-16"').encode("utf-16"))
    result = parse_rsop_xml(str(path))
    assert result.error == ""
    assert result.user.name == "VRK\\iorda"


# ------------------------------------------------------------------
# Runner
# ------------------------------------------------------------------

def test_unelevated_missing_computer_scope_says_elevation(monkeypatch):
    monkeypatch.setattr(rsop_runner, "run_gpresult_xml",
                        lambda **kw: (True, REAL_USER_ONLY.encode(), ""))
    result = collect_rsop(elevated=False)
    assert result.computer.available is False
    assert "elevated" in result.computer.unavailable_reason.lower()


def test_elevated_missing_computer_scope_says_the_report_is_incomplete(monkeypatch):
    """Same empty half, different cause -- blaming elevation while running
    elevated would send the user chasing a UAC prompt that changes nothing."""
    monkeypatch.setattr(rsop_runner, "run_gpresult_xml",
                        lambda **kw: (True, REAL_USER_ONLY.encode(), ""))
    result = collect_rsop(elevated=True)
    reason = result.computer.unavailable_reason
    assert "incomplete" in reason
    # The point of the branch: do not send someone who is already elevated to
    # go and elevate.
    assert "Restart" not in reason


def test_a_collected_scope_carries_no_reason(monkeypatch):
    monkeypatch.setattr(rsop_runner, "run_gpresult_xml",
                        lambda **kw: (True, SETTINGS_XML.encode(), ""))
    result = collect_rsop(elevated=True)
    assert result.computer.unavailable_reason == ""
    assert result.user.unavailable_reason == ""


def test_gpresult_failure_is_carried_into_both_scopes(monkeypatch):
    monkeypatch.setattr(rsop_runner, "run_gpresult_xml",
                        lambda **kw: (False, b"", "ERROR: Access Denied."))
    result = collect_rsop(elevated=False)
    assert result.error == "ERROR: Access Denied."
    assert "Access Denied" in result.computer.unavailable_reason
    assert "Access Denied" in result.user.unavailable_reason


def test_the_complaint_is_read_from_stdout_not_stderr(monkeypatch, tmp_path):
    """netsh, dism and gpresult all write their real reason to stdout. A
    runner that reads only stderr reports an empty error."""
    class Result:
        stdout = "ERROR: Access Denied."
        stderr = ""
        returncode = 1

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    ok, data, message = run_gpresult_xml(scope="computer")
    assert ok is False
    assert message == "ERROR: Access Denied."


def test_a_zero_exit_with_no_file_is_still_a_failure(monkeypatch):
    """Exit code is not the success signal: the report existing is."""
    class Result:
        stdout = ""
        stderr = ""
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    ok, data, message = run_gpresult_xml()
    assert ok is False
    assert message


def test_a_missing_gpresult_exe_is_reported(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    ok, _, message = run_gpresult_xml()
    assert ok is False
    assert "not found" in message


def test_a_timeout_is_reported(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("gpresult", 90)

    monkeypatch.setattr(subprocess, "run", boom)
    ok, _, message = run_gpresult_xml()
    assert ok is False
    assert "90s" in message


def test_the_temp_report_is_always_deleted(monkeypatch, tmp_path):
    """A pile of wct_gpresult_*.xml in %TEMP% is the tell for a runner that
    returns early on failure."""
    import os
    written = {}

    def fake_run(cmd, **kwargs):
        path = cmd[cmd.index("/x") + 1]
        written["path"] = path
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(REAL_USER_ONLY)

        class Result:
            stdout = stderr = ""
            returncode = 0
        return Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, data, _ = run_gpresult_xml()
    assert ok and data
    assert not os.path.exists(written["path"])


def test_export_html_reports_a_refusal(monkeypatch, tmp_path):
    class Result:
        stdout = "ERROR: Access Denied."
        stderr = ""
        returncode = 1

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    ok, message = export_html_report(str(tmp_path / "r.html"))
    assert ok is False
    assert "Access Denied" in message


# ------------------------------------------------------------------
# MMC consoles
# ------------------------------------------------------------------

def test_a_console_that_is_not_installed_returns_none():
    assert mmc_console_path("definitely-not-a-console.msc") is None


@pytest.mark.skipif(mmc_console_path("gpedit.msc") is None,
                    reason="gpedit.msc ships with Pro and above")
def test_gpedit_is_found_when_installed():
    path = mmc_console_path("gpedit.msc")
    assert path.lower().endswith("gpedit.msc")
