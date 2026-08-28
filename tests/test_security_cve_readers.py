"""The CVE readers, against a real Get-SpeculationControlSettings result.

Until 2026-08-28 none of these had ever run on real data in this project: the
snapshot command piped the cmdlet straight into ConvertTo-Json, and the cmdlet
writes a page of human-readable findings to the HOST before returning its
object -- so stdout was prose followed by JSON, the parse failed, and all
fourteen readers answered "could not determine" on a machine where the module
was installed and the data was right there.

With the data flowing, three of them were wrong, and all three erred GREEN:

  check_inception       "MITIGATION" in "SRSO_MITIGATION_DISABLED" is True, so
                        a status that says the mitigation is DISABLED was
                        classified as mitigated.
  check_swapgs          `BhbEnabled or BhbDisabledSystemPolicy is False` --
                        "no policy disabled it" was read as "it is on".
                        BhbEnabled is False on this machine.
  check_mmio_stale_data reported Mitigated from FBClearWindowsSupportPresent
                        alone, while FBClearWindowsSupportEnabled is False.
                        Support present is not the mitigation running.

REAL_SPECULATION below is verbatim what this AMD machine returned. Where a
reader's verdict is checked, it is checked against the module's OWN prose for
the same CVE, which is the only independent source available.
"""
import pytest

from modules.security_dashboard import security_reader
from modules.security_dashboard import snapshots


#: Get-SpeculationControlSettings -Quiet on this machine, 2026-08-28.
REAL_SPECULATION = {
    "BTIDisabledByNoHardwareSupport": False, "BTIDisabledBySystemPolicy": False,
    "BTIHardwarePresent": True, "BTIKernelImportOptimizationEnabled": True,
    "BTIKernelRetpolineEnabled": True, "BTIWindowsSupportEnabled": True,
    "BTIWindowsSupportPresent": True,
    "BhbDisabledNoHardwareSupport": False, "BhbDisabledSystemPolicy": False,
    "BhbEnabled": False,
    "BranchConfusionReported": True,
    "BranchConfusionStatus":
        "SYSTEM_SPECULATION_CONTROL_BRANCH_CONFUSION_HARDWARE_IMMUNE",
    "DivideByZeroReported": True,
    "DivideByZeroStatus": "SYSTEM_SPECULATION_CONTROL_DIVIDE_BY_ZERO_MITIGATED",
    "FBClearWindowsSupportEnabled": False, "FBClearWindowsSupportPresent": True,
    "FBSDPHardwareVulnerable": False,
    "GdsReported": True,
    "GdsStatus": "SYSTEM_SPECULATION_CONTROL_GDS_HARDWARE_IMMUNE",
    "HvL1tfProcessorNotAffected": True, "HvL1tfStatusAvailable": True,
    "KVAShadowPcidEnabled": False, "KVAShadowRequired": False,
    "KVAShadowWindowsSupportEnabled": False,
    "KVAShadowWindowsSupportPresent": True,
    "L1DFlushSupported": False, "L1TFHardwareVulnerable": False,
    "L1TFInvalidPteBit": 0, "L1TFWindowsSupportEnabled": False,
    "L1TFWindowsSupportPresent": True,
    "MDSHardwareVulnerable": False, "MDSWindowsSupportEnabled": False,
    "MDSWindowsSupportPresent": True,
    "PSDPHardwareVulnerable": False,
    "RdclHardwareProtected": False, "RdclHardwareProtectedReported": True,
    "RfdsReported": True,
    "RfdsStatus": "SYSTEM_SPECULATION_CONTROL_RFDS_HARDWARE_IMMUNE",
    "SBDRSSDPHardwareVulnerable": False,
    "SSBDHardwarePresent": True, "SSBDHardwareVulnerable": True,
    "SSBDWindowsSupportEnabledSystemWide": False,
    "SSBDWindowsSupportPresent": True,
    "SrsoReported": True,
    "SrsoStatus": "SYSTEM_SPECULATION_CONTROL_SRSO_MITIGATION_DISABLED",
}


@pytest.fixture
def speculation(monkeypatch):
    state = {"data": dict(REAL_SPECULATION), "reason": None}
    monkeypatch.setattr(snapshots, "speculation_control", lambda: state["data"])
    monkeypatch.setattr(
        snapshots, "unavailable",
        lambda name: state["reason"] if name == "speculation_control" else None)
    return state


# -- the three that rendered green on this machine and should not have --------

def test_a_disabled_srso_mitigation_is_not_mitigated(speculation):
    """SrsoStatus literally ends in MITIGATION_DISABLED. Inception affects
    AMD Zen 3/4, and this is an AMD machine, so a false green here is the
    worst kind."""
    result = security_reader.check_inception()

    assert result["available"] is True
    assert result["color"] != "green"
    assert "disabled" in result["status"].lower()


def test_bhb_not_disabled_by_policy_does_not_mean_bhb_is_on(speculation):
    result = security_reader.check_swapgs()

    assert result["available"] is True
    assert result["color"] != "green", (
        "green came from BhbDisabledSystemPolicy being False, which only says "
        "no policy turned it off")


def test_bhb_actually_enabled_is_green(speculation):
    speculation["data"] = dict(REAL_SPECULATION, BhbEnabled=True)

    result = security_reader.check_swapgs()

    assert result["color"] == "green"


def test_fill_buffer_clear_present_but_not_enabled_is_not_mitigated(speculation):
    """FBClearWindowsSupportPresent True, ...Enabled False. The mitigation is
    shipped, not running."""
    speculation["data"] = dict(REAL_SPECULATION,
                               SBDRSSDPHardwareVulnerable=True,
                               FBSDPHardwareVulnerable=True)

    result = security_reader.check_mmio_stale_data()

    assert result["available"] is True
    assert result["color"] != "green"


def test_hardware_that_is_not_vulnerable_to_mmio_is_green_for_that_reason(
        speculation):
    """On this machine the module's own prose says the hardware is not
    vulnerable to SBDR, FBSDP or PSDP. Green is right; 'support is present'
    was the wrong reason for it."""
    result = security_reader.check_mmio_stale_data()

    assert result["color"] == "green"
    assert "hardware" in str(result["details"]).lower()


# -- the ones that were already right, pinned so a refactor cannot break them -

def test_the_readers_that_agree_with_the_modules_own_prose(speculation):
    """Each expectation is the module's English finding for that CVE:
    BTI enabled True; L1TF/MDS/SBDR hardware not vulnerable; SSBD hardware
    vulnerable with the mitigation not enabled system-wide."""
    assert security_reader.check_spectre_v2()["color"] == "green"
    assert security_reader.check_l1tf()["color"] == "green"
    assert security_reader.check_mds()["color"] == "green"
    assert security_reader.check_srbds()["color"] == "green"
    assert security_reader.check_tsx_async_abort()["color"] == "green"
    assert security_reader.check_retbleed()["color"] == "green"
    assert security_reader.check_downfall_gds()["color"] == "green"
    assert security_reader.check_rfds()["color"] == "green"
    assert security_reader.check_zenbleed()["color"] == "green"
    assert security_reader.check_ssbd()["color"] == "amber"


def test_every_speculation_reader_reports_a_refusal_as_a_refusal(speculation):
    speculation["reason"] = "module not present"

    for name in ("check_spectre_v2", "check_meltdown", "check_l1tf",
                 "check_mds", "check_ssbd", "check_swapgs", "check_srbds",
                 "check_tsx_async_abort", "check_retbleed",
                 "check_mmio_stale_data", "check_downfall_gds",
                 "check_zenbleed", "check_inception", "check_rfds"):
        result = getattr(security_reader, name)()
        assert result["available"] is False, name
        assert result["color"] == "amber", name


# -- the status-string classifier, which is where the substring bug lived -----

@pytest.mark.parametrize("status,expected", [
    ("SYSTEM_SPECULATION_CONTROL_SRSO_MITIGATION_DISABLED", "disabled"),
    ("SYSTEM_SPECULATION_CONTROL_GDS_HARDWARE_IMMUNE", "immune"),
    ("SYSTEM_SPECULATION_CONTROL_DIVIDE_BY_ZERO_MITIGATED", "mitigated"),
    ("SYSTEM_SPECULATION_CONTROL_SRSO_MITIGATION_ENABLED", "mitigated"),
    ("SYSTEM_SPECULATION_CONTROL_RFDS_NOT_AFFECTED", "immune"),
    ("SOMETHING_NOBODY_HAS_SEEN", "unknown"),
    ("", "unknown"),
])
def test_disabled_is_decided_before_mitigated(status, expected):
    assert security_reader._speculation_status(status) == expected
