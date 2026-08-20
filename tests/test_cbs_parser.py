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
        # Three lines in, three entries out. The unmatched line used to be
        # DROPPED; on a real CBS.log that silently lost 6,333 of 85,850 lines,
        # which are the indented detail under a message and usually the part
        # that says why. It is kept as a continuation of the record above.
        assert len(entries) == 3
        assert entries[0].level == "Info"
        assert entries[0].source == "CBS"
        assert "TrustedInstaller" in entries[0].message
        assert entries[1].level == "Error"

        assert entries[2].raw.get("continuation") is True
        assert entries[2].message == "malformed line"
        # It inherits WHEN and WHERE from the record it continues...
        assert entries[2].timestamp == entries[1].timestamp
        assert entries[2].source == entries[1].source
        # ...but not its severity: a detail line is not an error of its own,
        # and inheriting one would inflate any count of them.
        assert entries[2].level != "Error"
    finally:
        os.unlink(path)


def test_cbs_module_creates_widget():
    from modules.cbs_log.cbs_module import CBSLogModule
    mod = CBSLogModule()
    widget = mod.create_widget()
    assert widget is not None
