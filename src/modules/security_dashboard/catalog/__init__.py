"""Assemble the catalog from its category modules."""
from typing import Dict

from .model import Category, ControlState, Risk, SecurityControl

#: check_* functions in security_reader.py that are deliberately NOT controls,
#: each with the reason. The binding test (test_security_catalog_binding.py)
#: fails on any reader that is neither bound nor listed here, so a check
#: cannot quietly fail to reach the pane.
NOT_A_CONTROL: Dict[str, str] = {}

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
