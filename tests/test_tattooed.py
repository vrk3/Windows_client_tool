"""The tattooed-policy scan: what is in the managed branches that no
`Registry.pol` accounts for.

Every test here is a statement about behaviour that would produce a wrong or
dangerous answer if it broke:

* the hive mapping (Machine .pol = HKLM, User .pol = HKCU) -- get it backwards
  and every managed value is reported as tattooed, which is a screenful of
  false positives on a clean machine;
* case-insensitivity -- the registry is case-insensitive and .pol writers are
  inconsistent, so a case-sensitive compare produces the same false positives
  more subtly;
* access-denied handling -- three real keys on the development machine refuse
  an unelevated read, and a scan that quietly dropped them would report
  "nothing tattooed here" about a place it never looked;
* the recursion bounds -- a cap that truncates without saying so turns an
  incomplete scan into a confident wrong answer.

The registry is injected in almost every test, so none of this depends on the
state of the machine running pytest.
"""
from typing import Dict, Iterable, List, Sequence, Tuple

import pytest

from modules.gpresult.pol_parser import PolFile, PolicyValue
from modules.gpresult.tattooed import (
    DEFAULT_MAX_DEPTH, KeyContents, MANAGED_BRANCHES, RegistryValue,
    find_tattooed, pol_index, read_registry_key, scan_branch,
)

REG_SZ = 1
REG_DWORD = 4
REG_MULTI_SZ = 7


class FakeRegistry:
    """An injectable stand-in for the live registry.

    Built from full paths (`HKLM\\Software\\Policies\\Foo`) so the tests read
    like regedit. Ancestors are created implicitly, subkeys are derived, and
    the original casing of every path is preserved -- which is what lets the
    case-insensitivity tests hand back keys spelled differently from the .pol.
    """

    def __init__(self,
                 keys: Dict[str, Sequence[Tuple[str, int, object]]],
                 denied: Iterable[str] = ()):
        self._values: Dict[Tuple[str, str], List[Tuple[str, int, object]]] = {}
        #: parent ident -> child names, in the casing they were declared with.
        self._children: Dict[Tuple[str, str], List[str]] = {}
        self._denied = set()
        self.reads: List[str] = []

        for path, values in keys.items():
            self._add(path, list(values))
        for path in denied:
            # A denied key must still be enumerable from its parent -- that is
            # the whole scenario being modelled.
            self._add(path, [])
            self._denied.add(self._ident(path))

    def _ident(self, path: str) -> Tuple[str, str]:
        hive, _, rest = path.partition("\\")
        return hive.upper(), rest.lower()

    def _add(self, path: str, values: List[Tuple[str, int, object]]) -> None:
        hive, _, rest = path.partition("\\")
        parts = rest.split("\\")
        # Walk up from the leaf and stop at the first ancestor already known:
        # creating ancestors top-down instead makes building a deep chain
        # quadratic, and one test deliberately builds a 2000-level one.
        depth = len(parts)
        while depth >= 1:
            ident = (hive.upper(), "\\".join(parts[:depth]).lower())
            if ident in self._values:
                break
            self._values[ident] = []
            self._children.setdefault(ident, [])
            if depth > 1:
                parent = (hive.upper(), "\\".join(parts[:depth - 1]).lower())
                self._children.setdefault(parent, []).append(parts[depth - 1])
            depth -= 1
        self._values[(hive.upper(), rest.lower())] = values

    def __call__(self, hive: str, key: str) -> KeyContents:
        self.reads.append("%s\\%s" % (hive, key))
        ident = (hive.upper(), key.lower())
        if ident in self._denied:
            return KeyContents(denied=True, error="[WinError 5] Access is denied")
        if ident not in self._values:
            return KeyContents(missing=True)
        return KeyContents(subkeys=sorted(self._children.get(ident, [])),
                           values=list(self._values[ident]))


def machine_pol(*records: Tuple[str, str, int, object]) -> PolFile:
    """A Computer-scope `Registry.pol` holding the given records."""
    return PolFile(scope="Computer", hive="HKLM", exists=True, values=[
        PolicyValue(key=key, value_name=name, type_id=type_id, data=data)
        for key, name, type_id, data in records])


def user_pol(*records: Tuple[str, str, int, object]) -> PolFile:
    """A User-scope `Registry.pol` holding the given records."""
    return PolFile(scope="User", hive="HKCU", exists=True, values=[
        PolicyValue(key=key, value_name=name, type_id=type_id, data=data)
        for key, name, type_id, data in records])


ONE_HKLM_BRANCH = (("HKLM", r"Software\Policies"),)
ONE_HKCU_BRANCH = (("HKCU", r"Software\Policies"),)


# ---------------------------------------------------------------------------
# The core subtraction
# ---------------------------------------------------------------------------

def test_a_value_no_policy_file_accounts_for_is_reported_as_tattooed():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor\App": [("Telemetry", REG_DWORD, 0)],
    })
    result = find_tattooed(pol_files=[], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert [v.full_path for v in result.tattooed] == [
        r"HKLM\Software\Policies\Vendor\App\Telemetry"]
    assert result.accounted == []


def test_a_value_the_machine_policy_file_sets_is_not_tattooed():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor\App": [("Telemetry", REG_DWORD, 0)],
    })
    pol = machine_pol((r"Software\Policies\Vendor\App", "Telemetry",
                       REG_DWORD, 0))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.tattooed == []
    assert [v.full_path for v in result.accounted] == [
        r"HKLM\Software\Policies\Vendor\App\Telemetry"]


def test_the_machine_policy_file_does_not_account_for_an_hkcu_value():
    # Machine .pol is HKLM only. If its records were matched against HKCU as
    # well, a user-hive value with the same name would be silently excused.
    registry = FakeRegistry({
        r"HKCU\Software\Policies\Vendor\App": [("Telemetry", REG_DWORD, 0)],
    })
    pol = machine_pol((r"Software\Policies\Vendor\App", "Telemetry",
                       REG_DWORD, 0))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKCU_BRANCH)

    assert [v.full_path for v in result.tattooed] == [
        r"HKCU\Software\Policies\Vendor\App\Telemetry"]


def test_the_user_policy_file_accounts_for_an_hkcu_value():
    registry = FakeRegistry({
        r"HKCU\Software\Policies\Vendor\App": [("Telemetry", REG_DWORD, 0)],
    })
    pol = user_pol((r"Software\Policies\Vendor\App", "Telemetry",
                    REG_DWORD, 0))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKCU_BRANCH)

    assert result.tattooed == []
    assert len(result.accounted) == 1


def test_a_key_or_value_spelled_in_a_different_case_still_matches_the_policy():
    # The registry here spells the key and the value name differently from the
    # .pol. They are the same setting; a case-sensitive compare would report
    # it as tattooed.
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Microsoft\Windows\SrpV2\Exe":
            [("AllowWindows", REG_DWORD, 0)],
    })
    pol = machine_pol((r"software\policies\microsoft\windows\srpv2\exe",
                       "allowwindows", REG_DWORD, 0))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.tattooed == []
    assert len(result.accounted) == 1


def test_values_from_every_managed_branch_are_scanned():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\A": [("one", REG_DWORD, 1)],
        r"HKLM\Software\Microsoft\Windows\CurrentVersion\Policies\B":
            [("two", REG_DWORD, 1)],
        r"HKCU\Software\Policies\C": [("three", REG_DWORD, 1)],
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Policies\D":
            [("four", REG_DWORD, 1)],
    })

    result = find_tattooed(pol_files=[], reader=registry)

    assert len(result.branches) == 4
    assert sorted(v.value_name for v in result.tattooed) == [
        "four", "one", "three", "two"]


def test_the_four_managed_branches_are_the_ones_group_policy_owns():
    assert MANAGED_BRANCHES == (
        ("HKLM", r"Software\Policies"),
        ("HKLM", r"Software\Microsoft\Windows\CurrentVersion\Policies"),
        ("HKCU", r"Software\Policies"),
        ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Policies"),
    )


# ---------------------------------------------------------------------------
# Access denied is an outcome, not a shrug
# ---------------------------------------------------------------------------

def test_a_denied_subkey_does_not_stop_the_rest_of_the_walk():
    registry = FakeRegistry(
        keys={
            r"HKLM\Software\Policies\Readable": [("kept", REG_DWORD, 1)],
            r"HKLM\Software\Policies\AlsoReadable": [("also", REG_DWORD, 1)],
        },
        denied=[r"HKLM\Software\Policies\Secret"])

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry)

    assert sorted(v.value_name for v in scan.values) == ["also", "kept"]


def test_a_denied_subkey_is_named_in_the_result_rather_than_dropped():
    registry = FakeRegistry(
        keys={r"HKLM\Software\Policies\Readable": [("kept", REG_DWORD, 1)]},
        denied=[r"HKLM\Software\Policies\Secret"])

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry)

    assert scan.unreadable_keys == [r"HKLM\Software\Policies\Secret"]


def test_a_scan_that_was_refused_anywhere_never_calls_itself_complete():
    # "We could not look here" must never present as "there is nothing here".
    registry = FakeRegistry(
        keys={r"HKLM\Software\Policies\Readable": []},
        denied=[r"HKLM\Software\Policies\Secret"])

    result = find_tattooed(pol_files=[], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.complete is False
    assert result.unreadable_key_count == 1
    assert "unreadable" in result.summary()


def test_a_denied_branch_root_reads_as_unreadable_not_as_an_empty_branch():
    registry = FakeRegistry(keys={r"HKLM\Software\Policies\Sub": []},
                            denied=[r"HKLM\Software\Policies"])

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry)

    assert scan.exists is True
    assert scan.values == []
    assert scan.unreadable_keys == [r"HKLM\Software\Policies"]
    assert scan.complete is False


def test_a_partially_readable_key_is_recorded_as_unreadable_too():
    # A key whose enumeration failed halfway gave us some of its values. It
    # must not pass as fully examined.
    def reader(hive, key):
        if key.lower() == r"software\policies":
            return KeyContents(subkeys=["Half"])
        return KeyContents(values=[("got", REG_DWORD, 1)],
                           error="[WinError 5] Access is denied")

    scan = scan_branch("HKLM", r"Software\Policies", reader=reader)

    assert [v.value_name for v in scan.values] == ["got"]
    assert scan.unreadable_keys == [r"HKLM\Software\Policies\Half"]


def test_a_branch_that_does_not_exist_is_neither_an_error_nor_a_finding():
    registry = FakeRegistry({r"HKLM\Software\Policies\Present": []})

    scan = scan_branch("HKCU", r"Software\Policies", reader=registry)

    assert scan.exists is False
    assert scan.values == []
    assert scan.unreadable_keys == []
    assert scan.error == ""
    assert scan.complete is True


# ---------------------------------------------------------------------------
# The bounds
# ---------------------------------------------------------------------------

def _deep_chain(levels: int) -> FakeRegistry:
    path = r"HKLM\Software\Policies"
    keys = {}
    for level in range(levels):
        path = "%s\\L%d" % (path, level)
        keys[path] = [("v%d" % level, REG_DWORD, level)]
    return FakeRegistry(keys)


def test_the_walk_stops_at_max_depth_and_names_the_keys_it_did_not_open():
    registry = _deep_chain(6)

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry,
                       max_depth=3)

    # Depth 0 is the branch root, so values from L0, L1 and L2 come back.
    assert [v.value_name for v in scan.values] == ["v0", "v1", "v2"]
    assert scan.depth_capped_keys == [r"HKLM\Software\Policies\L0\L1\L2"]
    assert scan.complete is False


def test_a_branch_shallower_than_the_cap_reports_no_depth_capping():
    registry = _deep_chain(3)

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry,
                       max_depth=DEFAULT_MAX_DEPTH)

    assert scan.depth_capped_keys == []
    assert scan.complete is True


def test_the_walk_stops_at_the_value_cap_and_flags_the_result_incomplete():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Many":
            [("v%d" % i, REG_DWORD, i) for i in range(10)],
    })

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry,
                       max_values=4)

    assert len(scan.values) == 4
    assert scan.value_cap_hit is True
    assert scan.complete is False


def test_a_capped_scan_says_so_in_its_summary():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Many":
            [("v%d" % i, REG_DWORD, i) for i in range(10)],
    })

    result = find_tattooed(pol_files=[], reader=registry,
                           branches=ONE_HKLM_BRANCH, max_values=4)

    assert result.capped is True
    assert result.complete is False
    assert "incomplete" in result.summary()


def test_a_chain_deeper_than_python_would_recurse_is_walked_without_error():
    # The walk is an explicit stack, so the bound is the one we chose rather
    # than CPython's -- a deep branch produces a reported cap, never a
    # RecursionError surfacing out of a worker thread.
    registry = _deep_chain(2000)

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry,
                       max_depth=1500)

    assert len(scan.values) == 1500
    assert len(scan.depth_capped_keys) == 1


# ---------------------------------------------------------------------------
# What the .pol directives account for
# ---------------------------------------------------------------------------

def test_a_delete_directive_accounts_for_the_value_name_it_names():
    # "**del.Telemetry" means Group Policy actively manages `Telemetry` into
    # the absent state. The name is owned; it is not unaccounted for.
    pol = PolFile(scope="Computer", hive="HKLM", exists=True, values=[
        PolicyValue(key=r"Software\Policies\Vendor", value_name="**del.Telemetry",
                    type_id=REG_SZ, data=" ", directive="delete_value"),
    ])
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor": [("Telemetry", REG_DWORD, 1)],
    })

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.tattooed == []
    assert len(result.accounted) == 1


def test_a_delete_all_values_directive_does_not_excuse_the_values_it_finds():
    # "**delvals." says nothing about which names exist, so anything actually
    # present under that key is genuinely unaccounted for.
    pol = PolFile(scope="Computer", hive="HKLM", exists=True, values=[
        PolicyValue(key=r"Software\Policies\Vendor", value_name="**delvals.",
                    type_id=REG_SZ, data=" ", directive="delete_all_values"),
    ])
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor": [("Telemetry", REG_DWORD, 1)],
    })

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert [v.full_path for v in result.tattooed] == [
        r"HKLM\Software\Policies\Vendor\Telemetry"]


def test_the_policy_index_is_keyed_case_insensitively():
    pol = machine_pol((r"Software\POLICIES\Vendor", "MixedCase", REG_DWORD, 1))

    index = pol_index([pol])

    assert index == {("HKLM", r"software\policies\vendor", "mixedcase"): 1}


# ---------------------------------------------------------------------------
# Drift: policy owns the name, something else changed the data
# ---------------------------------------------------------------------------

def test_a_policy_value_overwritten_with_other_data_is_reported_as_drift():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor": [("Telemetry", REG_DWORD, 1)],
    })
    pol = machine_pol((r"Software\Policies\Vendor", "Telemetry", REG_DWORD, 0))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.tattooed == []
    assert [v.full_path for v in result.drifted] == [
        r"HKLM\Software\Policies\Vendor\Telemetry"]
    assert "overwritten" in result.summary()


def test_a_policy_value_still_holding_its_policy_data_is_not_drift():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor": [("List", REG_MULTI_SZ, ["a", "b"])],
    })
    pol = machine_pol((r"Software\Policies\Vendor", "List", REG_MULTI_SZ,
                       ["a", "b"]))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.drifted == []


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def test_a_policy_file_that_would_not_parse_surfaces_as_a_warning():
    # An unreadable .pol under-counts the accounted-for side, which inflates
    # the tattooed list. The user has to be told.
    broken = PolFile(scope="Computer", hive="HKLM", exists=True,
                     error="Could not parse Registry.pol: not a PReg file")
    registry = FakeRegistry({r"HKLM\Software\Policies\Vendor": []})

    result = find_tattooed(pol_files=[broken], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.warnings == [broken.error]


def test_a_found_value_carries_the_path_a_person_would_paste_into_regedit():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor\App": [("Telemetry", REG_DWORD, 0)],
    })

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry)
    value = scan.values[0]

    assert value.key_path == r"HKLM\Software\Policies\Vendor\App"
    assert value.full_path == r"HKLM\Software\Policies\Vendor\App\Telemetry"
    assert value.branch == r"HKLM\Software\Policies"
    assert value.type_name == "REG_DWORD"
    assert value.display() == "0"


def test_binary_and_multi_string_data_display_readably():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor": [
            ("Blob", 3, b"\x01\xff"),
            ("List", REG_MULTI_SZ, ["a", "b"]),
        ],
    })

    scan = scan_branch("HKLM", r"Software\Policies", reader=registry)
    shown = {v.value_name: v.display() for v in scan.values}

    assert shown == {"Blob": "01ff", "List": "a, b"}


def test_a_clean_scan_of_a_fully_managed_machine_reports_itself_complete():
    registry = FakeRegistry({
        r"HKLM\Software\Policies\Vendor": [("Telemetry", REG_DWORD, 0)],
    })
    pol = machine_pol((r"Software\Policies\Vendor", "Telemetry", REG_DWORD, 0))

    result = find_tattooed(pol_files=[pol], reader=registry,
                           branches=ONE_HKLM_BRANCH)

    assert result.complete is True
    assert result.tattooed == []
    assert result.total_values == 1
    assert result.elapsed_seconds >= 0.0


def test_an_injected_reader_is_the_only_registry_the_scan_touches():
    # If this ever fails, the scan is reading the machine it runs on and the
    # rest of this file is testing that machine rather than the code.
    registry = FakeRegistry({r"HKLM\Software\Policies\Vendor": []})

    find_tattooed(pol_files=[], reader=registry, branches=ONE_HKLM_BRANCH)

    assert registry.reads[0] == r"HKLM\Software\Policies"
    assert all(read.startswith("HKLM") for read in registry.reads)


# ---------------------------------------------------------------------------
# The real winreg-backed reader
# ---------------------------------------------------------------------------

def test_the_real_reader_reports_a_missing_key_as_missing_not_as_an_error():
    contents = read_registry_key(
        "HKLM", r"Software\Policies\NoSuchVendor_%s" % id(object()))

    assert contents.missing is True
    assert contents.denied is False
    assert contents.error == ""


def test_the_real_reader_rejects_a_hive_it_does_not_know():
    contents = read_registry_key("HKXX", r"Software\Policies")

    assert contents.error
    assert contents.values == []


def test_the_real_reader_opens_a_branch_that_exists_on_every_windows_box():
    # HKLM\Software\Policies is present on every Windows install; if this
    # comes back missing, the 64-bit view is not being asked for.
    contents = read_registry_key("HKLM", r"Software\Policies")

    assert contents.missing is False
    assert contents.denied is False
    assert contents.subkeys, "expected at least one vendor under Policies"


@pytest.mark.parametrize("hive,key", MANAGED_BRANCHES)
def test_every_managed_branch_can_be_scanned_on_this_machine(hive, key):
    scan = scan_branch(hive, key)

    assert scan.branch_path == "%s\\%s" % (hive, key)
    assert scan.value_cap_hit is False
    assert scan.depth_capped_keys == []
    for value in scan.values:
        assert isinstance(value, RegistryValue)
        assert value.full_path.startswith(hive)
