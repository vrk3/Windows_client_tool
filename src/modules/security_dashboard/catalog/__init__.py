"""Assemble the catalog from its category modules."""
from typing import Dict

from .model import Category, ControlState, Risk, SecurityControl

#: check_* functions in security_reader.py that are deliberately NOT controls,
#: each with the reason. The binding test (test_security_catalog_binding.py)
#: fails on any reader that is neither bound nor listed here, so a check
#: cannot quietly fail to reach the pane.
NOT_A_CONTROL: Dict[str, str] = {
    # -- Defender (Task 6) --------------------------------------------------
    "check_defender_signatures":
        "A freshness reading, not a setting. The Defender tab's "
        "'Update definitions' action is the thing that changes it.",
    "check_defender_threats":
        "A count of detections. Read-only by nature.",
    "check_defender_quarantine":
        "Lists quarantined items; acting on them is a separate operation.",
    "check_defender_last_scan":
        "A timestamp. 'Run quick scan' is the action that changes it.",
    "check_defender_scanning_history":
        "History, not configuration.",
    "check_defender_av_mode":
        "Reports whether Defender is primary, passive or disabled. That is "
        "decided by which AV products are installed, not by a setting.",
    "check_exploit_protection_system":
        "A census over every system-wide process mitigation: how many are "
        "enforced, how many explicitly disabled, how many left at Windows' "
        "default. Each mitigation is its own setting; the census is not "
        "settable, and CFG and ASLR -- the two that are -- are controls "
        "in their own right.",

    # -- Exploit & CVE (Task 6) --------------------------------------------
    "check_windows_defender_cve_mitigations":
        "An aggregate over 24 individual CVE readers, each of which is its "
        "own control here or in another category. It exists to give the "
        "Overview one card; there is nothing to write.",
}

# Carried instruction (Task 5 addendum, Ruling 6) for whichever task binds
# check_service_wsearch and check_service_sysmain: DO NOT put them in
# NOT_A_CONTROL -- they are real, wireable controls. But their readers
# currently score a RUNNING service as red/bad (_svc_check(..., running_bad=
# True)), which is a false positive in a *security* dashboard: Windows
# Search and SysMain running is a performance/telemetry question, not attack
# surface. That polarity is retained-as-was on purpose -- it was not the
# reader's mistake to fix here, and the verdict belongs in the catalog, not
# in security_reader.py. When these two become catalog entries, give both
# `desired=None` ("no opinion") so a running service is never counted as a
# problem, while the card still shows the reader's honest status. Consequence
# for the pane's "Only problems" filter: it must key off `desired`, NOT off
# the reader's `color` field -- a reader may legitimately colour something
# amber/red that the catalog has no opinion about.


def load_catalog() -> Dict[str, SecurityControl]:
    """id -> control, across every category module."""
    from . import (accounts, defender, device_boot, exploit_cve, features,
                   firewall_network, services)

    catalog: Dict[str, SecurityControl] = {}
    for module in (defender, firewall_network, accounts, device_boot,
                   services, features, exploit_cve):
        for control in module.CONTROLS:
            if control.id in catalog:
                raise ValueError(f"duplicate control id: {control.id}")
            catalog[control.id] = control
    return catalog
