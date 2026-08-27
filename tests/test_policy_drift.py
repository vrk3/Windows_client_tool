"""Behaviour of `policy_drift` — is a local GPO setting actually in effect?

Every test here drives an injected reader, so none of them depend on this
machine's registry. The two that do touch the real machine say so, and assert
only things that are true of any machine.
"""

import os

import pytest

from modules.gpresult.pol_parser import (
    PolFile,
    PolicyValue,
    REG_BINARY,
    REG_DWORD,
    REG_MULTI_SZ,
    REG_NONE,
    REG_SZ,
    local_policy_files,
)
from modules.gpresult.policy_drift import (
    APPLIED,
    DIFFERENT,
    MISSING,
    STATES,
    UNREADABLE,
    DriftReport,
    RegistryRead,
    compare_policy_value,
    drift_for_pol_file,
    drift_report,
    read_live_value,
)


def _reader(**by_value_name):
    """A reader keyed on value name, returning `RegistryRead`s you hand it."""
    def read(hive, key, value_name):
        return by_value_name.get(value_name or "(key)", RegistryRead(found=False))
    return read


def _dword(name="AllowWindows", data=0, key=r"Software\Policies\Test"):
    return PolicyValue(key=key, value_name=name, type_id=REG_DWORD, data=data)


def test_a_value_holding_what_the_policy_asks_for_is_applied():
    policy = _dword(data=0)
    result = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(
            found=True, data=0, type_id=REG_DWORD, key_exists=True)))

    assert result.state == APPLIED
    assert not result.is_drift
    assert result.is_certain


def test_a_value_holding_something_else_is_different_and_records_both():
    policy = _dword(data=0)
    result = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(
            found=True, data=1, type_id=REG_DWORD, key_exists=True)))

    assert result.state == DIFFERENT
    assert result.live_display == "1"
    assert result.expected_display == "0"
    assert "1" in result.reason and "0" in result.reason
    assert result.is_drift


def test_a_value_absent_from_a_key_that_exists_is_missing():
    result = compare_policy_value(
        _dword(), "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(found=False, key_exists=True)))

    assert result.state == MISSING
    assert result.is_drift


def test_a_missing_key_says_the_key_is_missing_not_the_value():
    result = compare_policy_value(
        _dword(), "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(found=False, key_exists=False)))

    assert result.state == MISSING
    assert "key" in result.reason


def test_a_refused_read_is_not_reported_as_missing():
    """The hard rule: a failed read is never a definite answer."""
    result = compare_policy_value(
        _dword(), "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(
            readable=False, error="access denied reading the value")))

    assert result.state == UNREADABLE
    assert result.state != MISSING
    assert "access denied" in result.reason


def test_a_refused_read_does_not_count_as_drift():
    result = compare_policy_value(
        _dword(), "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(readable=False, error="access denied")))

    assert not result.is_drift
    assert not result.is_certain


def test_a_refused_read_never_invents_a_live_value():
    result = compare_policy_value(
        _dword(), "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(readable=False, error="access denied")))

    assert result.live_data is None
    assert result.live_display == ""


def test_a_key_only_record_checks_the_key_instead_of_crashing():
    """This machine's own Safer record: REG_NONE, empty value name, no data."""
    policy = PolicyValue(
        key=r"Software\Policies\Microsoft\Windows\Safer",
        value_name="", type_id=REG_NONE, data=b"", raw=b"")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        lambda hive, key, name: RegistryRead(found=True, key_exists=True))

    assert result.key_only
    assert result.state == APPLIED
    assert "key" in result.reason


def test_a_key_only_record_whose_key_is_absent_is_missing():
    policy = PolicyValue(key=r"Software\Policies\Gone", value_name="",
                         type_id=REG_NONE, data=b"", raw=b"")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        lambda hive, key, name: RegistryRead(found=False, key_exists=False))

    assert result.state == MISSING


def test_a_key_only_record_asks_the_reader_for_no_value_name():
    seen = []

    def read(hive, key, value_name):
        seen.append((hive, key, value_name))
        return RegistryRead(found=True, key_exists=True)

    compare_policy_value(
        PolicyValue(key=r"Software\X", value_name="", type_id=REG_NONE),
        "HKLM", "Computer", read)

    assert seen == [("HKLM", r"Software\X", "")]


def test_a_delete_directive_whose_value_is_gone_is_applied_not_drift():
    policy = PolicyValue(key=r"Software\Policies\Test", value_name="**del.Foo",
                         type_id=REG_SZ, data=" ", directive="delete_value")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        lambda hive, key, name: RegistryRead(found=False, key_exists=True))

    assert result.expects_absent
    assert result.state == APPLIED
    assert not result.is_drift


def test_a_delete_directive_whose_value_survived_is_drift():
    policy = PolicyValue(key=r"Software\Policies\Test", value_name="**del.Foo",
                         type_id=REG_SZ, data=" ", directive="delete_value")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        lambda hive, key, name: RegistryRead(
            found=True, data="still here", type_id=REG_SZ, key_exists=True))

    assert result.state == DIFFERENT
    assert result.is_drift
    assert "still here" in result.reason


def test_a_refused_read_beats_a_delete_directive_too():
    policy = PolicyValue(key=r"Software\Policies\Test", value_name="**del.Foo",
                         directive="delete_value")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        lambda hive, key, name: RegistryRead(readable=False, error="access denied"))

    assert result.state == UNREADABLE


def test_the_same_data_stored_under_the_wrong_type_is_drift():
    """Windows reads a policy value by type, so a DWORD kept as text is inert."""
    policy = _dword(data=0)
    result = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(
            found=True, data=0, type_id=REG_SZ, key_exists=True)))

    assert result.state == DIFFERENT


def test_a_string_with_a_trailing_null_still_matches_the_policy():
    policy = PolicyValue(key=r"Software\Policies\Test", value_name="Banner",
                         type_id=REG_SZ, data="hello")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(Banner=RegistryRead(
            found=True, data="hello\x00", type_id=REG_SZ, key_exists=True)))

    assert result.state == APPLIED


def test_a_multi_sz_matches_element_by_element():
    policy = PolicyValue(key=r"Software\Policies\Test", value_name="List",
                         type_id=REG_MULTI_SZ, data=["a", "b"])

    same = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(List=RegistryRead(
            found=True, data=["a", "b"], type_id=REG_MULTI_SZ, key_exists=True)))
    other = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(List=RegistryRead(
            found=True, data=["a"], type_id=REG_MULTI_SZ, key_exists=True)))

    assert same.state == APPLIED
    assert other.state == DIFFERENT
    assert other.live_display == "a"


def test_binary_data_is_shown_as_hex_on_both_sides():
    policy = PolicyValue(key=r"Software\Policies\Test", value_name="Blob",
                         type_id=REG_BINARY, data=b"\x01\x02", raw=b"\x01\x02")

    result = compare_policy_value(
        policy, "HKLM", "Computer",
        _reader(Blob=RegistryRead(
            found=True, data=b"\xff", type_id=REG_BINARY, key_exists=True)))

    assert result.state == DIFFERENT
    assert result.expected_display == "0102"
    assert result.live_display == "ff"


def test_every_record_is_compared_including_the_directives():
    pol = PolFile(path="x", scope="Computer", hive="HKLM", exists=True, values=[
        _dword(),
        PolicyValue(key=r"Software\Policies\Test", value_name="**del.Foo",
                    directive="delete_value"),
    ])

    results = drift_for_pol_file(
        pol, lambda hive, key, name: RegistryRead(found=False, key_exists=True))

    # `pol.settings` would drop the directive, and a delete that came undone is
    # exactly the drift this module exists to surface.
    assert len(results) == 2
    assert [r.state for r in results] == [MISSING, APPLIED]


def test_each_scope_is_read_from_its_own_hive():
    seen = []

    def read(hive, key, value_name):
        seen.append(hive)
        return RegistryRead(found=True, data=0, type_id=REG_DWORD, key_exists=True)

    drift_report([
        PolFile(path="m", scope="Computer", hive="HKLM", exists=True,
                values=[_dword()]),
        PolFile(path="u", scope="User", hive="HKCU", exists=True,
                values=[_dword()]),
    ], read)

    assert seen == ["HKLM", "HKCU"]


def test_a_scope_with_no_pol_file_contributes_nothing_and_is_not_an_error():
    report = drift_report([
        PolFile(path="u", scope="User", hive="HKCU", exists=False),
    ], _reader())

    assert report.results == []
    assert report.errors == []


def test_a_file_that_could_not_be_parsed_is_skipped_and_still_reported():
    report = drift_report([
        PolFile(path="m", scope="Computer", hive="HKLM", exists=True,
                error="Could not parse m: bad magic"),
    ], _reader())

    assert report.results == []
    assert report.errors == ["Could not parse m: bad magic"]


def test_the_summary_names_every_state_even_at_zero():
    report = DriftReport()

    assert set(report.counts) == set(STATES)
    assert all(count == 0 for count in report.counts.values())
    for state in STATES:
        assert state in report.summary()


def test_the_report_separates_known_drift_from_unanswered_reads():
    pol = PolFile(path="m", scope="Computer", hive="HKLM", exists=True, values=[
        _dword(name="Good"), _dword(name="Bad"), _dword(name="Denied"),
    ])
    reader = _reader(
        Good=RegistryRead(found=True, data=0, type_id=REG_DWORD, key_exists=True),
        Bad=RegistryRead(found=True, data=1, type_id=REG_DWORD, key_exists=True),
        Denied=RegistryRead(readable=False, error="access denied"),
    )

    report = drift_report([pol], reader)

    assert report.counts == {APPLIED: 1, DIFFERENT: 1, MISSING: 0, UNREADABLE: 1}
    assert len(report.drifted) == 1
    assert [r.value_name for r in report.by_state(UNREADABLE)] == ["Denied"]


def test_a_result_names_the_setting_the_way_the_rest_of_the_app_does():
    result = compare_policy_value(
        _dword(key=r"Software\Policies\Test", name="AllowWindows"),
        "HKLM", "Computer",
        _reader(AllowWindows=RegistryRead(
            found=True, data=0, type_id=REG_DWORD, key_exists=True)))

    assert result.full_path == r"HKLM\Software\Policies\Test\AllowWindows"
    assert result.key == r"Software\Policies\Test"
    assert result.scope == "Computer"


def test_every_result_explains_itself():
    """A state with no sentence behind it is useless in a tooltip."""
    pol = PolFile(path="m", scope="Computer", hive="HKLM", exists=True, values=[
        _dword(name="A"), _dword(name="B"), _dword(name="C"), _dword(name="D"),
    ])
    reader = _reader(
        A=RegistryRead(found=True, data=0, type_id=REG_DWORD, key_exists=True),
        B=RegistryRead(found=True, data=9, type_id=REG_DWORD, key_exists=True),
        C=RegistryRead(found=False, key_exists=True),
        D=RegistryRead(readable=False, error="access denied"),
    )

    for result in drift_report([pol], reader).results:
        assert result.reason
        assert result.state in STATES


@pytest.mark.skipif(os.name != "nt", reason="reads the live Windows registry")
def test_the_live_reader_asks_for_the_sixty_four_bit_view(monkeypatch):
    """Without KEY_WOW64_64KEY a 32-bit host reads Wow6432Node and sees nothing."""
    import winreg

    seen = {}

    def fake_open(root, key, reserved=0, access=0):
        seen["access"] = access
        raise FileNotFoundError(2, "not found")

    monkeypatch.setattr(winreg, "OpenKey", fake_open)
    read_live_value("HKLM", r"Software\Policies\Test", "X")

    assert seen["access"] & winreg.KEY_WOW64_64KEY
    assert seen["access"] & winreg.KEY_READ


@pytest.mark.skipif(os.name != "nt", reason="reads the live Windows registry")
def test_an_unknown_hive_is_unreadable_rather_than_missing():
    read = read_live_value("HKZZ", r"Software", "X")

    assert not read.readable
    assert not read.found


@pytest.mark.skipif(os.name != "nt", reason="reads the live Windows registry")
def test_the_real_local_policy_can_be_compared_without_raising():
    """Asserts only what is true of any machine — the counts are this one's."""
    report = drift_report(local_policy_files())

    assert len(report.results) == sum(report.counts.values())
    for result in report.results:
        assert result.state in STATES
        assert result.reason
        assert result.hive in ("HKLM", "HKCU")
