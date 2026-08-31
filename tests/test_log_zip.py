r"""Opening a zip of collected logs.

This is the shape logs arrive in from someone else's machine, and unpacking
it by hand before you can read it is a step with no purpose.

The security part is not theoretical: `zipfile` will happily write a member
named `..\..\evil.log` or `C:\Windows\System32\evil.log` outside the
directory you gave it. A log viewer that unpacks a bundle from a stranger's
machine has to refuse those.
"""
import os
import zipfile

import pytest

from modules.log_viewer.archives import extract_zip, is_zip


def _bundle(path, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return str(path)


LINE = "2026-08-27 10:00:00, Info                  CBS    a line\n"


def test_a_zip_is_recognised_by_its_extension():
    assert is_zip(r"C:\bundles\logs.zip")
    assert is_zip(r"C:\bundles\LOGS.ZIP")
    assert not is_zip(r"C:\logs\CBS.log")


def test_a_bundle_of_logs_yields_them_all(tmp_path):
    bundle = _bundle(tmp_path / "logs.zip",
                     {"cbs.log": LINE, "dism.log": LINE})

    found, problem = extract_zip(bundle, into=str(tmp_path / "out"))

    assert not problem
    assert sorted(os.path.basename(p) for p in found) == \
        ["cbs.log", "dism.log"]


def test_nested_logs_are_found_too(tmp_path):
    bundle = _bundle(tmp_path / "logs.zip", {"CBS/cbs.log": LINE})
    found, problem = extract_zip(bundle, into=str(tmp_path / "out"))
    assert not problem and len(found) == 1


def test_entries_that_are_not_logs_are_skipped(tmp_path):
    bundle = _bundle(tmp_path / "logs.zip",
                     {"cbs.log": LINE, "readme.txt": "hello",
                      "photo.png": "binary"})
    found, _ = extract_zip(bundle, into=str(tmp_path / "out"))
    assert [os.path.basename(p) for p in found] == ["cbs.log"]


def test_a_bundle_with_no_logs_says_so(tmp_path):
    bundle = _bundle(tmp_path / "empty.zip", {"readme.txt": "hello"})
    found, problem = extract_zip(bundle, into=str(tmp_path / "out"))
    assert found == []
    assert problem


def test_something_that_is_not_a_zip_says_why(tmp_path):
    fake = tmp_path / "fake.zip"
    fake.write_text("not a zip", encoding="utf-8")
    found, problem = extract_zip(str(fake), into=str(tmp_path / "out"))
    assert found == [] and problem


def test_a_missing_bundle_says_why(tmp_path):
    found, problem = extract_zip(str(tmp_path / "nope.zip"))
    assert found == [] and problem


# ---- the part that matters -----------------------------------------------

def test_a_member_escaping_the_target_directory_is_refused(tmp_path):
    r"""Zip Slip: `..\..\evil.log` would be written outside the directory
    given to extract."""
    out = tmp_path / "out"
    bundle = tmp_path / "evil.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("../escaped.log", LINE)
        archive.writestr("good.log", LINE)

    found, _problem = extract_zip(str(bundle), into=str(out))

    assert [os.path.basename(p) for p in found] == ["good.log"]
    assert not (tmp_path / "escaped.log").exists(), \
        "a member was written outside the target directory"


def test_an_absolute_member_is_refused(tmp_path):
    out = tmp_path / "out"
    bundle = tmp_path / "abs.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("/rooted.log", LINE)
        archive.writestr("good.log", LINE)

    found, _problem = extract_zip(str(bundle), into=str(out))

    assert all(str(out) in os.path.abspath(p) for p in found)


def test_every_extracted_file_lands_inside_the_target(tmp_path):
    out = tmp_path / "out"
    bundle = _bundle(tmp_path / "logs.zip",
                     {"a.log": LINE, "deep/b.log": LINE})
    found, _ = extract_zip(str(bundle), into=str(out))
    for path in found:
        assert os.path.abspath(path).startswith(os.path.abspath(str(out)))


# ---- the pane -----------------------------------------------------------

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402


def test_opening_a_bundle_merges_its_logs(qapp, tmp_path):
    bundle = _bundle(tmp_path / "support.zip",
                     {"cbs.log": LINE,
                      "dism.log": "2026-08-27 10:00:05, Info"
                                  "                  DISM   later\n"})
    widget = LogViewerWidget()
    try:
        widget.open(str(bundle))
        assert widget.model.total == 2
        assert "2 logs merged" in widget.status.text()
    finally:
        widget.stop()


def test_a_bundle_with_no_logs_says_so_and_keeps_the_pane(qapp, tmp_path):
    bundle = _bundle(tmp_path / "empty.zip", {"readme.txt": "hello"})
    widget = LogViewerWidget()
    try:
        widget.open(str(bundle))
        assert "no logs" in widget.status.text().lower()
        assert widget.model.total == 0
    finally:
        widget.stop()


def test_the_browse_filter_offers_bundles(qapp):
    widget = LogViewerWidget()
    try:
        assert ".zip" in widget.FILE_FILTER
    finally:
        widget.stop()
