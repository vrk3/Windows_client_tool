"""One UAC prompt for the batch, and a command line that survives a space.

core.admin_utils.restart_as_admin builds its command line with
" ".join(sys.argv) and no quoting. The batch file lives under
C:\\Users\\<name>\\AppData\\Local\\... -- a path with a space in it is not
hypothetical here, it is the normal case.

A ShellExecuteW-launched process cannot have its stdout captured by the
parent, so the helper writes its own result file. This project has already
paid for that lesson once with elevated PowerShell.
"""
import json

import pytest

from modules.security_dashboard.applier import BatchResult
from modules.security_dashboard.catalog.model import (
    Category, ControlState, SecurityControl)
from modules.security_dashboard.elevated_helper import (
    build_elevated_command, changes_of, read_result_file, write_batch_file)
from modules.security_dashboard.staging import ChangeSet


def test_the_command_line_quotes_a_path_containing_spaces():
    _, args = build_elevated_command(
        r"C:\Users\a b\AppData\batch.json", r"C:\Users\a b\result.json")
    assert '"C:\\Users\\a b\\AppData\\batch.json"' in args
    assert '"C:\\Users\\a b\\result.json"' in args


def test_a_batch_round_trips_through_the_file(tmp_path, monkeypatch):
    batch = tmp_path / "b.json"
    write_batch_file([("llmnr", False), ("wdigest", False)], str(batch))
    assert json.loads(batch.read_text())["changes"] == [
        ["llmnr", False], ["wdigest", False]]


def test_a_missing_result_file_is_reported_not_assumed(tmp_path):
    result = read_result_file(str(tmp_path / "nope.json"))
    assert result is None, "no result must mean unknown, never success"


def test_a_truncated_result_file_is_unknown_not_success(tmp_path):
    path = tmp_path / "r.json"
    path.write_text('{"results": [')
    assert read_result_file(str(path)) is None


# --- the four below are not in the plan ------------------------------------


def _control(cid, current):
    return SecurityControl(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": current},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))


def test_a_changeset_carries_the_value_the_user_reviewed_across_the_prompt():
    """Not just (id, target).

    The elevated child stages the batch again on the other side of the UAC
    prompt. Given only (id, target) it has to READ the machine for every
    from_value -- 12.7s unelevated and 31.4s elevated on this machine, all of
    it after the user has already granted the prompt -- and the revert it then
    computes from that fresh reading need not be the one the review dialog
    showed. So the value the parent read travels with the change.
    """
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)
    cs.add(_control("wdigest", None), False)   # was unreadable unelevated
    assert changes_of(cs) == [
        ("llmnr", False, True), ("wdigest", False, None)]


def test_a_batch_file_from_a_changeset_keeps_all_three_fields(tmp_path):
    batch = tmp_path / "b.json"
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)
    write_batch_file(cs, str(batch))
    assert json.loads(batch.read_text())["changes"] == [["llmnr", False, True]]


def test_a_result_file_comes_back_as_a_batch_result(tmp_path):
    """Task 14 renders one shape whether the batch ran here or elevated."""
    path = tmp_path / "r.json"
    path.write_text(json.dumps({
        "version": 1, "rp_id": "rp-9", "windows_restore_point": None,
        "results": [
            {"control_id": "llmnr", "state": "applied_verified",
             "requested": False, "observed": False, "reason": ""},
            {"control_id": "wdigest", "state": "refused", "requested": False,
             "observed": True, "reason": "Access is denied."}]}))
    result = read_result_file(str(path))
    assert isinstance(result, BatchResult)
    assert result.rp_id == "rp-9"
    assert result.verified == 1
    assert result.results[1].state is ControlState.REFUSED
    assert len(result.problems) == 1


def test_a_state_the_reader_does_not_recognise_is_unknown_not_success(tmp_path):
    """A result file written by a NEWER build of the app.

    Guessing at a state name it does not know is how a refusal gets rendered
    as a success. The whole file is unusable instead.
    """
    path = tmp_path / "r.json"
    path.write_text(json.dumps({
        "version": 1, "rp_id": "rp-9",
        "results": [{"control_id": "llmnr", "state": "applied_probably",
                     "requested": False, "observed": False, "reason": ""}]}))
    assert read_result_file(str(path)) is None


def test_a_helper_that_crashed_says_so_rather_than_reporting_nothing(tmp_path):
    """The child cannot print to the parent -- the file is the only channel."""
    path = tmp_path / "r.json"
    path.write_text(json.dumps({
        "version": 1, "rp_id": "", "results": [],
        "error": "BackupService could not open its database"}))
    result = read_result_file(str(path))
    assert isinstance(result, BatchResult)
    assert "could not open its database" in result.error
    assert result.results == []


def test_a_result_file_with_a_byte_order_mark_still_reads(tmp_path):
    """The helper's own writes have no BOM, but a file that has been through
    a Windows tool does, and json.load refuses it outright."""
    path = tmp_path / "r.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({
        "version": 1, "rp_id": "rp-9",
        "results": [{"control_id": "llmnr", "state": "applied_verified",
                     "requested": False, "observed": False,
                     "reason": ""}]}).encode("utf-8"))
    result = read_result_file(str(path))
    assert result is not None and result.verified == 1
