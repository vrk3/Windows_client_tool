"""Behaviour of the offline ADMX/ADML lookup.

Two halves. The fixture half builds a tiny PolicyDefinitions tree in `tmp_path`
and pins the parsing rules -- elements, cross-file parentCategory chaining,
malformed files, missing ADML, language fallback. The real-machine half runs
against `C:\\Windows\\PolicyDefinitions` and is skipped where it is absent,
because a hand-built fixture cannot tell you whether the `<elements>` handling
survives Microsoft's own 224 files.
"""

import os
import time

import pytest

from modules.gpresult.admx_catalog import (
    DEFAULT_POLICY_DEFINITIONS_DIR,
    AdmxCatalog,
    clear_cache,
    get_catalog,
    lookup_policy,
)

REAL_DIR = DEFAULT_POLICY_DEFINITIONS_DIR
has_real_admx = pytest.mark.skipif(
    not os.path.isdir(REAL_DIR),
    reason="PolicyDefinitions is stripped on this image",
)


# --------------------------------------------------------------------------
# fixture tree
# --------------------------------------------------------------------------

BASE_ADMX = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"
                   revision="1.0" schemaVersion="1.0">
  <policyNamespaces>
    <target prefix="base" namespace="Test.Policies.Base" />
  </policyNamespaces>
  <supportedOn>
    <definitions>
      <definition name="SUPPORTED_TestOS" displayName="$(string.SUPPORTED_TestOS)" />
    </definitions>
  </supportedOn>
  <categories>
    <category name="WindowsComponents" displayName="$(string.WindowsComponents)" />
    <category name="Inner" displayName="$(string.Inner)">
      <parentCategory ref="WindowsComponents" />
    </category>
  </categories>
  <policies />
</policyDefinitions>
"""

BASE_ADML = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitionResources xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"
                           revision="1.0" schemaVersion="1.0">
  <displayName>Base</displayName>
  <description>Base</description>
  <resources>
    <stringTable>
      <string id="WindowsComponents">Windows Components</string>
      <string id="Inner">Inner Things</string>
      <string id="SUPPORTED_TestOS">At least Test Windows</string>
    </stringTable>
  </resources>
</policyDefinitionResources>
"""

LEAF_ADMX = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"
                   revision="1.0" schemaVersion="1.0">
  <policyNamespaces>
    <target prefix="leaf" namespace="Test.Policies.Leaf" />
    <using prefix="base" namespace="Test.Policies.Base" />
  </policyNamespaces>
  <categories>
    <category name="Leafy" displayName="$(string.Leafy)">
      <parentCategory ref="base:Inner" />
    </category>
  </categories>
  <policies>
    <policy name="SimpleMachine" class="Machine" displayName="$(string.SimpleMachine)"
            explainText="$(string.SimpleMachine_Help)"
            key="Software\\Policies\\Test\\Leaf" valueName="TurnItOff">
      <parentCategory ref="Leafy" />
      <supportedOn ref="base:SUPPORTED_TestOS" />
    </policy>
    <policy name="SimpleUser" class="User" displayName="$(string.SimpleUser)"
            key="Software\\Policies\\Test\\Leaf" valueName="UserOnly">
      <parentCategory ref="Leafy" />
    </policy>
    <policy name="ElementsOnly" class="Machine" displayName="$(string.ElementsOnly)"
            key="Software\\Policies\\Test\\Elements">
      <parentCategory ref="Leafy" />
      <elements>
        <decimal id="Interval" valueName="IntervalMinutes" />
        <boolean id="Flag" valueName="FlagOn" />
        <text id="Elsewhere" key="Software\\Policies\\Test\\Other" valueName="OverThere" />
        <list id="TheList" key="Software\\Policies\\Test\\ListKey" />
      </elements>
    </policy>
  </policies>
</policyDefinitions>
"""

LEAF_ADML = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitionResources xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"
                           revision="1.0" schemaVersion="1.0">
  <displayName>Leaf</displayName>
  <description>Leaf</description>
  <resources>
    <stringTable>
      <string id="Leafy">Leafy Bits</string>
      <string id="SimpleMachine">Turn the machine thing off</string>
      <string id="SimpleMachine_Help">Explains the machine thing.</string>
      <string id="SimpleUser">Turn the user thing off</string>
      <string id="ElementsOnly">Configure several knobs</string>
    </stringTable>
  </resources>
</policyDefinitionResources>
"""

ORPHAN_ADMX = """<?xml version="1.0" encoding="utf-8"?>
<policyDefinitions xmlns="http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"
                   revision="1.0" schemaVersion="1.0">
  <policyNamespaces>
    <target prefix="orphan" namespace="Test.Policies.Orphan" />
  </policyNamespaces>
  <categories />
  <policies>
    <policy name="NoAdmlHere" class="Machine" displayName="$(string.NoAdmlHere)"
            key="Software\\Policies\\Test\\Orphan" valueName="Lonely" />
  </policies>
</policyDefinitions>
"""

BROKEN_ADMX = "<policyDefinitions><policies><policy name='oops'"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


@pytest.fixture
def definitions(tmp_path):
    """A miniature PolicyDefinitions: two well-formed files that reference each
    other, one with no ADML, and one that is not XML at all."""
    root = str(tmp_path / "PolicyDefinitions")
    _write(os.path.join(root, "Base.admx"), BASE_ADMX)
    _write(os.path.join(root, "Leaf.admx"), LEAF_ADMX)
    _write(os.path.join(root, "Orphan.admx"), ORPHAN_ADMX)
    _write(os.path.join(root, "Broken.admx"), BROKEN_ADMX)
    _write(os.path.join(root, "en-US", "Base.adml"), BASE_ADML)
    _write(os.path.join(root, "en-US", "Leaf.adml"), LEAF_ADML)
    return root


@pytest.fixture
def catalog(definitions):
    return AdmxCatalog(definitions)


@pytest.fixture(autouse=True)
def _clean_shared_cache():
    clear_cache()
    yield
    clear_cache()


# --------------------------------------------------------------------------
# laziness and caching
# --------------------------------------------------------------------------


def test_constructing_a_catalog_parses_nothing(definitions):
    catalog = AdmxCatalog(definitions)
    assert catalog.loaded is False


def test_first_lookup_builds_the_index_and_later_ones_reuse_it(catalog):
    assert catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff") is not None
    assert catalog.loaded is True
    stats = catalog.stats
    catalog.lookup(r"Software\Policies\Test\Leaf", "UserOnly")
    assert catalog.stats is stats  # same build, not a second one


def test_get_catalog_returns_the_same_instance_per_directory(definitions):
    assert get_catalog(definitions) is get_catalog(definitions)


def test_clear_cache_forces_a_fresh_catalog(definitions):
    first = get_catalog(definitions)
    clear_cache()
    assert get_catalog(definitions) is not first


# --------------------------------------------------------------------------
# resolving a policy
# --------------------------------------------------------------------------


def test_lookup_resolves_the_friendly_name_and_explain_text(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff")
    assert info.display_name == "Turn the machine thing off"
    assert info.explain_text == "Explains the machine thing."


def test_category_path_chains_across_files_and_is_rooted_by_class(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff")
    assert info.category_path == (
        "Computer Configuration/Administrative Templates/"
        "Windows Components/Inner Things/Leafy Bits"
    )


def test_a_user_policy_is_rooted_under_user_configuration(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "UserOnly")
    assert info.scope == "User"
    assert info.category_path.startswith("User Configuration/Administrative Templates/")


def test_supported_on_text_is_resolved_from_the_defining_file(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff")
    assert info.supported_on == "At least Test Windows"


def test_a_policy_without_supported_on_reports_empty_not_none(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "UserOnly")
    assert info.supported_on == ""


def test_lookup_ignores_case_and_hive_prefix_on_the_key(catalog):
    info = catalog.lookup(r"HKLM\SOFTWARE\policies\TEST\leaf", "turnitoff")
    assert info is not None and info.name == "SimpleMachine"


def test_registry_pol_deletion_markers_resolve_to_the_same_policy(catalog):
    # Registry.pol writes `**del.ValueName` to remove a setting; it is still
    # the same policy and the user still wants to read its name.
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "**del.TurnItOff")
    assert info is not None and info.name == "SimpleMachine"


def test_scope_hint_selects_between_policies_sharing_a_key(catalog):
    machine = catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff", "Machine")
    assert machine.name == "SimpleMachine"
    assert catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff", "User") is None


def test_path_for_scope_shows_both_trees_for_a_both_class_policy(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Orphan", "Lonely")
    assert info.path_for_scope("User").startswith("User Configuration/")
    assert info.path_for_scope("Machine").startswith("Computer Configuration/")


# --------------------------------------------------------------------------
# <elements>
# --------------------------------------------------------------------------


def test_element_value_names_are_indexed_not_just_the_policy_attribute(catalog):
    # ElementsOnly has no valueName of its own -- 1,229 real policies are like
    # this, so missing them would gut the catalogue.
    for value in ("IntervalMinutes", "FlagOn"):
        info = catalog.lookup(r"Software\Policies\Test\Elements", value)
        assert info is not None and info.name == "ElementsOnly"


def test_an_element_may_override_the_policy_key(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Other", "OverThere")
    assert info is not None and info.name == "ElementsOnly"


def test_a_list_element_is_matched_by_key_because_it_has_no_value_name(catalog):
    # A <list> writes "1", "2", ... under its key, so any value there belongs
    # to it.
    info = catalog.lookup(r"Software\Policies\Test\ListKey", "1")
    assert info is not None and info.name == "ElementsOnly"


def test_an_exact_value_match_outranks_a_list_key_match(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff")
    assert info.name == "SimpleMachine"


def test_value_names_lists_every_value_the_policy_writes(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Elements", "FlagOn")
    assert info.value_names == ("IntervalMinutes", "FlagOn", "OverThere")


def test_lookup_key_returns_every_policy_touching_a_key(catalog):
    names = {p.name for p in catalog.lookup_key(r"Software\Policies\Test\Leaf")}
    assert names == {"SimpleMachine", "SimpleUser"}


# --------------------------------------------------------------------------
# misses
# --------------------------------------------------------------------------


def test_an_unknown_value_under_a_known_key_returns_none(catalog):
    assert catalog.lookup(r"Software\Policies\Test\Leaf", "NeverHeardOfIt") is None


def test_an_unknown_key_returns_none(catalog):
    assert catalog.lookup(r"Software\Policies\Nope", "Whatever") is None


# --------------------------------------------------------------------------
# degrading instead of raising
# --------------------------------------------------------------------------


def test_a_missing_definitions_directory_yields_an_empty_working_catalog(tmp_path):
    catalog = AdmxCatalog(str(tmp_path / "not-here"))
    assert catalog.lookup(r"Software\Anything", "Value") is None
    assert catalog.stats.policy_count == 0
    assert catalog.stats.admx_files_found == 0


def test_a_malformed_admx_is_skipped_and_the_rest_still_load(catalog):
    stats = catalog.stats
    assert stats.admx_files_failed == 1  # Broken.admx
    assert stats.admx_files_parsed == 3
    assert catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff") is not None


def test_a_policy_whose_adml_is_missing_falls_back_to_its_admx_name(catalog):
    info = catalog.lookup(r"Software\Policies\Test\Orphan", "Lonely")
    assert info is not None
    assert info.display_name == "NoAdmlHere"  # never the raw $(string.…) ref
    assert info.explain_text == ""
    assert catalog.stats.adml_files_missing == 1


def test_a_category_ref_into_an_absent_file_keeps_the_raw_name_in_the_path(
    tmp_path,
):
    root = str(tmp_path / "PolicyDefinitions")
    _write(os.path.join(root, "Leaf.admx"), LEAF_ADMX)  # Base.admx absent
    _write(os.path.join(root, "en-US", "Leaf.adml"), LEAF_ADML)
    info = AdmxCatalog(root).lookup(r"Software\Policies\Test\Leaf", "TurnItOff")
    assert info.category_segments == ("Inner", "Leafy Bits")


# --------------------------------------------------------------------------
# language
# --------------------------------------------------------------------------


def test_en_us_is_preferred_when_present(catalog):
    assert catalog.stats.language == "en-US"


def test_another_language_is_used_when_en_us_is_absent(tmp_path):
    root = str(tmp_path / "PolicyDefinitions")
    _write(os.path.join(root, "Leaf.admx"), LEAF_ADMX)
    _write(os.path.join(root, "de-DE", "Leaf.adml"), LEAF_ADML)
    catalog = AdmxCatalog(root)
    assert catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff") is not None
    assert catalog.stats.language == "de-DE"  # reported, not silently guessed


def test_no_language_folder_at_all_still_lists_policies_by_admx_name(tmp_path):
    root = str(tmp_path / "PolicyDefinitions")
    _write(os.path.join(root, "Leaf.admx"), LEAF_ADMX)
    catalog = AdmxCatalog(root)
    info = catalog.lookup(r"Software\Policies\Test\Leaf", "TurnItOff")
    assert info.display_name == "SimpleMachine"
    assert catalog.stats.language == ""


# --------------------------------------------------------------------------
# the real files
# --------------------------------------------------------------------------


@has_real_admx
def test_applocker_srpv2_has_no_admx_and_must_return_none():
    """The honest limitation, pinned.

    AppLocker is configured through its own MMC snap-in, not Administrative
    Templates, so nothing in PolicyDefinitions describes `SrpV2` -- and that is
    exactly what is set on this machine. A lookup MUST come back `None` so the
    caller shows the raw key instead of an invented friendly name.
    """
    catalog = get_catalog(REAL_DIR)
    assert catalog.lookup(r"Software\Policies\Microsoft\Windows\SrpV2\Exe", "AllowWindows") is None
    assert catalog.lookup(r"Software\Policies\Microsoft\Windows\SrpV2\Msi", "EnforcementMode") is None
    assert not [p for p in catalog.all_policies() if "srpv2" in p.registry_key.lower()]


@has_real_admx
def test_the_real_catalog_indexes_thousands_of_policies_without_failures():
    stats = get_catalog(REAL_DIR).stats
    assert stats.policy_count > 3000
    assert stats.pair_count > 4000
    # Two files that ship with Windows 11 are UTF-16 and one of those declares
    # encoding='unicode'; if the decoder regresses, this fails.
    assert stats.admx_files_failed == 0
    assert stats.strings_unresolved == 0


@has_real_admx
def test_a_real_machine_policy_resolves_to_its_gpedit_name_and_path():
    info = lookup_policy(
        r"Software\Policies\Microsoft\Windows\CloudContent",
        "DisableWindowsConsumerFeatures",
        definitions_dir=REAL_DIR,
    )
    assert info.display_name == "Turn off Microsoft consumer experiences"
    assert info.category_path == (
        "Computer Configuration/Administrative Templates/"
        "Windows Components/Cloud Content"
    )
    assert info.scope == "Machine"
    assert info.supported_on.startswith("At least Windows 10")


@has_real_admx
def test_a_real_user_policy_chains_its_category_through_another_admx():
    # WindowsExplorer.admx's category parents into windows:WindowsExplorer,
    # which is only defined in Windows.admx.
    info = lookup_policy(
        r"Software\Microsoft\Windows\CurrentVersion\Policies\Comdlg32",
        "NoBackButton",
        definitions_dir=REAL_DIR,
    )
    assert info.display_name == "Hide the common dialog back button"
    assert info.category_path == (
        "User Configuration/Administrative Templates/Windows Components/"
        "File Explorer/Common Open File Dialog"
    )


@has_real_admx
def test_a_real_value_declared_only_by_an_element_still_resolves():
    # ScheduledInstallDay is an <elements><decimal> inside AutoUpdateCfg; the
    # policy element itself never names it.
    info = lookup_policy(
        r"Software\Policies\Microsoft\Windows\WindowsUpdate\AU",
        "ScheduledInstallDay",
        definitions_dir=REAL_DIR,
    )
    assert info.name == "AutoUpdateCfg"
    assert info.display_name == "Configure Automatic Updates"
    assert "Windows Update" in info.category_path


@has_real_admx
def test_the_real_cold_build_is_fast_enough_to_run_on_first_lookup():
    # Budget, not a benchmark: it measures ~0.17 s here, and a UI thread can
    # afford this once. A tenfold regression means something is being reparsed.
    catalog = AdmxCatalog(REAL_DIR)
    started = time.perf_counter()
    catalog.ensure_loaded()
    assert time.perf_counter() - started < 5.0
