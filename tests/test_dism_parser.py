import os
import tempfile
from modules.dism_log.dism_parser import DISMParser


def test_parse_dism_line():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("2026-03-25 10:00:00, Info                  DISM   Package Manager: Initializing.\n")
        f.write("2026-03-25 10:00:01, Warning               DISM   Image not found.\n")
        path = f.name
    try:
        parser = DISMParser(path)
        entries = parser.parse()
        assert len(entries) == 2
        assert entries[0].source == "DISM"
        assert entries[1].level == "Warning"
    finally:
        os.unlink(path)


def test_dism_module_creates_widget():
    from modules.dism_log.dism_module import DISMLogModule
    mod = DISMLogModule()
    widget = mod.create_widget()
    assert widget is not None
