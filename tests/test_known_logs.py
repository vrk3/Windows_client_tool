"""The viewer's one-click log list.

Resolved from the environment, never a hardcoded C: -- Windows is not always
on C:, and a hardcoded path does not fail loudly, it opens nothing.
"""
import os

import pytest

from modules.log_viewer import known_logs

FAKE = {"SystemRoot": r"D:\Windows", "ProgramData": r"D:\ProgramData"}


def _labels(environ=FAKE, exists=lambda _p: True):
    return {k.label: k.path for k in
            known_logs.known_logs(environ=environ, exists=exists)}


def test_nothing_is_hardcoded_to_c():
    for label, path in _labels().items():
        assert not path.upper().startswith("C:"), f"{label} -> {path}"


def test_the_everyday_windows_logs_are_offered():
    found = _labels()
    assert found["DISM"] == r"D:\Windows\Logs\DISM\dism.log"
    assert found["CBS (component store)"] == r"D:\Windows\Logs\CBS\CBS.log"
    assert found["Setup (setupact)"] == r"D:\Windows\Panther\setupact.log"


def test_the_configmgr_logs_are_offered_when_present():
    """The whole reason a CMTrace-style viewer exists."""
    found = _labels()
    assert found["ConfigMgr — CcmExec"] == r"D:\Windows\CCM\Logs\CcmExec.log"


def test_a_log_that_does_not_exist_is_hidden():
    """ConfigMgr is absent on a plain machine; a menu entry whose only
    outcome is an error is worse than no entry."""
    # Case-insensitively: the client-setup log lives under "ccmsetup",
    # which a case-sensitive check waves straight through.
    found = _labels(exists=lambda p: "ccm" not in p.lower())
    assert not any("ConfigMgr" in label for label in found)
    assert "DISM" in found


def test_an_empty_environment_yields_nothing_rather_than_junk():
    assert known_logs.known_logs(environ={}, exists=lambda _p: True) == []


def test_duplicates_are_collapsed():
    paths = [k.path for k in known_logs.known_logs(environ=FAKE,
                                                   exists=lambda _p: True)]
    assert len(paths) == len(set(paths))


def test_the_real_machine_offers_something_that_exists():
    for log in known_logs.known_logs():
        assert os.path.isfile(log.path), f"{log.label} -> {log.path}"


# ---- the rolled CBS archives -------------------------------------------

def test_the_newest_cbs_archive_is_chosen(tmp_path, monkeypatch):
    r"""On a machine that has been running a while the live CBS.log is the
    smallest part of the story; the CbsPersist_* siblings hold the rest."""
    folder = tmp_path / "Logs" / "CBS"
    folder.mkdir(parents=True)
    older = folder / "CbsPersist_20260101000000.log"
    newer = folder / "CbsPersist_20260202000000.log"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    os.utime(older, (1, 1))
    os.utime(newer, (10_000_000, 10_000_000))

    got = known_logs.newest_cbs_archive(environ={"SystemRoot": str(tmp_path)})
    assert got == str(newer)


def test_no_archives_yields_empty(tmp_path):
    (tmp_path / "Logs" / "CBS").mkdir(parents=True)
    assert known_logs.newest_cbs_archive(
        environ={"SystemRoot": str(tmp_path)}) == ""


def test_a_missing_folder_is_not_an_error():
    assert known_logs.newest_cbs_archive(environ={"SystemRoot": r"D:\nope"}) == ""


def test_cab_files_are_not_offered_as_logs(tmp_path):
    """A .cab is not readable text; extracting it is the Diagnose tab's job."""
    folder = tmp_path / "Logs" / "CBS"
    folder.mkdir(parents=True)
    (folder / "CbsPersist_20260101000000.cab").write_text("x", encoding="utf-8")
    assert known_logs.newest_cbs_archive(
        environ={"SystemRoot": str(tmp_path)}) == ""
