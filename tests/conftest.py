import os
import sys

# Add src/ to path so tests can import `core.*` directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def _catalog_readers_restored():
    """Put back any security-catalog reader a test swapped out.

    `catalog/<category>.py` holds its CONTROLS at module level, so every
    load_catalog() hands back the SAME SecurityControl objects. A test that
    does `object.__setattr__(control, "reader", ...)` -- which several must,
    to prove a tab reads only its own controls -- changes them for the rest
    of the session. That is how test_security_reader_defender.py started
    failing in a whole-suite run while passing on its own.

    Guarded on the module already being imported, so the ~2,400 tests that
    never touch the catalog pay nothing.
    """
    module = sys.modules.get("modules.security_dashboard.catalog")
    if module is None:
        yield
        return
    catalog = module.load_catalog()
    originals = {cid: control.reader for cid, control in catalog.items()}
    yield
    for control_id, reader in originals.items():
        control = catalog.get(control_id)
        if control is not None and control.reader is not reader:
            object.__setattr__(control, "reader", reader)
