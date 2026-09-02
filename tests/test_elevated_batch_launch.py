"""Launching the elevated Security helper: the error code, and the mess.

Two defects in `run_elevated_batch`, both invisible from the outside.

* It logged `ctypes.get_last_error()` after calling through
  `ctypes.windll.shell32`. `windll` is not built with
  `use_last_error=True`, so that reads ctypes' own private copy, which
  nothing ever set — the number in the log is zero or a leftover from some
  unrelated call. The commonest real cause by far, the user declining the
  UAC prompt (ERROR_CANCELLED, 1223), was therefore indistinguishable from
  a genuine failure. `dashboard/procengine/actions.py` already gets this
  right with `ctypes.WinDLL("shell32", use_last_error=True)`.

* It created a `tempfile.mkdtemp()` and never removed it. Every apply left
  `batch.json` — the staged changes, INCLUDING the previous value of each
  one — and `result.json` behind in %TEMP%, permanently.
"""
import os

import pytest

from modules.security_dashboard import security_module


class _FakeChange:
    def __init__(self, control_id="llmnr"):
        self.control_id = control_id
        self.to_value = True
        self.from_value = False


class _FakeChangeSet:
    changes = [_FakeChange()]


@pytest.fixture
def captured(monkeypatch):
    """Intercept the launch, remembering the folder it staged into."""
    seen = {}

    def fake_write(changes, path):
        seen["batch_path"] = path
        seen["folder"] = os.path.dirname(path)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("[]")

    monkeypatch.setattr(security_module, "write_batch_file", fake_write)
    monkeypatch.setattr(security_module, "build_elevated_command",
                        lambda b, r: ("python.exe", "args"))
    monkeypatch.setattr(security_module, "read_result_file", lambda p: "REPORT")
    return seen


def _refuse_with(monkeypatch, error_code):
    """ShellExecuteExW fails, and SetLastError reports `error_code`."""
    class _Shell32:
        @staticmethod
        def ShellExecuteExW(_info):
            ctypes_mod = security_module.ctypes
            ctypes_mod.set_last_error(error_code)
            return 0

    monkeypatch.setattr(security_module, "_shell32", _Shell32)


def test_a_declined_uac_prompt_is_reported_as_cancelled(monkeypatch, captured, caplog):
    """Saying No is not an error, and the log must not imply it was."""
    _refuse_with(monkeypatch, security_module.ERROR_CANCELLED)

    with caplog.at_level("INFO"):
        result = security_module.run_elevated_batch(_FakeChangeSet())

    assert result is None
    assert "cancel" in caplog.text.lower()


def test_a_real_failure_reports_its_actual_code(monkeypatch, captured, caplog):
    """5 is ERROR_ACCESS_DENIED — a different thing from a declined prompt,
    and the log has to be able to tell them apart."""
    _refuse_with(monkeypatch, 5)

    with caplog.at_level("INFO"):
        security_module.run_elevated_batch(_FakeChangeSet())

    assert "5" in caplog.text
    assert "cancel" not in caplog.text.lower()


def test_the_staging_folder_is_removed_when_the_prompt_is_declined(
        monkeypatch, captured):
    _refuse_with(monkeypatch, security_module.ERROR_CANCELLED)

    security_module.run_elevated_batch(_FakeChangeSet())

    assert not os.path.exists(captured["folder"]), (
        "batch.json holds the staged changes and their previous values; "
        "leaving it in %TEMP% forever is not acceptable")


def test_the_staging_folder_is_removed_after_a_successful_run(
        monkeypatch, captured):
    class _Shell32:
        @staticmethod
        def ShellExecuteExW(info):
            return 1

    class _Kernel32:
        @staticmethod
        def WaitForSingleObject(handle, timeout):
            return 0

        @staticmethod
        def CloseHandle(handle):
            return 1

    monkeypatch.setattr(security_module, "_shell32", _Shell32)
    monkeypatch.setattr(security_module, "_kernel32", _Kernel32)

    result = security_module.run_elevated_batch(_FakeChangeSet())

    assert result == "REPORT", "the report must still be read before cleanup"
    assert not os.path.exists(captured["folder"])
