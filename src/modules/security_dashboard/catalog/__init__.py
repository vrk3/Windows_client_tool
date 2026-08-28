"""Assemble the catalog from its category modules."""
from typing import Dict

from .model import Category, ControlState, Risk, SecurityControl

#: check_* functions in security_reader.py that are deliberately NOT controls,
#: each with the reason. The binding test (test_security_catalog_binding.py)
#: fails on any reader that is neither bound nor listed here, so a check
#: cannot quietly fail to reach the pane.
NOT_A_CONTROL: Dict[str, str] = {}


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
