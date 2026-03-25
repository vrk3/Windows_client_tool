import os
import tempfile
from modules.windows_update.wu_parser import WUParser


def test_parse_wu_line():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("2026-03-25 10:00:00\tAgent\tWindowsUpdate\tSuccess\tKB12345 installed\n")
        f.write("2026-03-25 10:00:01\tAgent\tWindowsUpdate\tFailure\tKB67890 failed\n")
        f.write("\n")
        path = f.name
    try:
        parser = WUParser(path)
        entries = parser.parse()
        assert len(entries) >= 2
        # Check that entries have reasonable fields
        assert entries[0].source != ""
    finally:
        os.unlink(path)


def test_wu_module_creates_widget():
    from modules.windows_update.wu_module import WindowsUpdateModule
    mod = WindowsUpdateModule()
    widget = mod.create_widget()
    assert widget is not None
