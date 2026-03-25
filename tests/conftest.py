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
