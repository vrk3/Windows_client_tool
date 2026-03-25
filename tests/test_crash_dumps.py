import os
import tempfile
from modules.crash_dumps.crash_dump_reader import read_crash_dumps


def test_read_crash_dumps_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        entries = read_crash_dumps(dump_dir=tmpdir)
        assert entries == []


def test_read_crash_dumps_with_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a fake .dmp file
        dmp_path = os.path.join(tmpdir, "test.dmp")
        with open(dmp_path, "wb") as f:
            f.write(b"MDMP" + b"\x00" * 28)  # Fake minidump header
        entries = read_crash_dumps(dump_dir=tmpdir)
        assert len(entries) == 1
        assert "test.dmp" in entries[0].message


def test_crash_dump_module_creates_widget():
    from modules.crash_dumps.crash_dump_module import CrashDumpModule
    mod = CrashDumpModule()
    widget = mod.create_widget()
    assert widget is not None


def test_read_nonexistent_dir():
    entries = read_crash_dumps(dump_dir="/nonexistent/path")
    assert entries == []
