import os
import tempfile
from modules.cbs_log.cbs_parser import CBSParser


def test_parse_cbs_line():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, encoding="utf-8") as f:
        f.write("2026-03-25 13:19:10, Info                  CBS    Starting TrustedInstaller.\n")
        f.write("2026-03-25 13:19:11, Error                 CBS    Package failed.\n")
        f.write("malformed line\n")
        path = f.name
    try:
        parser = CBSParser(path)
        entries = parser.parse()
        assert len(entries) == 2
        assert entries[0].level == "Info"
        assert entries[0].source == "CBS"
        assert "TrustedInstaller" in entries[0].message
        assert entries[1].level == "Error"
    finally:
        os.unlink(path)


def test_cbs_module_creates_widget():
    from modules.cbs_log.cbs_module import CBSLogModule
    mod = CBSLogModule()
    widget = mod.create_widget()
    assert widget is not None
