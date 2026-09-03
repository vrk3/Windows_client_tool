"""The trash manager's restore path, which had no test at all.

Found by the ruff sweep: `restore()` computed `dest_dir` to cover the
`original_path=None` default and then built `dest_path` from
`original_path` unconditionally, so the default argument put
`Path(None).parent` into the try block. The exception was caught and
reported as an ordinary "could not restore", which is indistinguishable
from a genuine failure.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from modules.cleanup.trash import TrashManager


class _Config:
    """The slice of CleanupConfig that TrashManager actually reads."""

    def __init__(self, trash_dir):
        self._trash_dir = str(trash_dir)

    def get_config(self):
        return {"user_cleanup": {"temp_files": self._trash_dir},
                "overwrite_existing": False}

    def get_trash_retention_days(self):
        return 30


def _manager(tmp_path):
    trash = tmp_path / "trash"
    trash.mkdir()
    mgr = TrashManager(_Config(trash))
    mgr._trash_dir = trash
    return mgr, trash


def test_restore_puts_the_file_back_beside_its_original(tmp_path):
    mgr, trash = _manager(tmp_path)
    original = tmp_path / "home" / "notes.txt"
    original.parent.mkdir()
    in_trash = trash / "notes.txt"
    in_trash.write_text("contents")

    assert mgr.restore(str(in_trash), str(original)) is True
    assert original.read_text() == "contents"
    assert not in_trash.exists()


def test_restore_without_an_original_path_does_not_raise(tmp_path, caplog):
    """The default argument. It cannot restore anywhere useful -- the item
    is already in that directory -- so False is the right answer. What it
    must NOT do is reach that answer by way of a TypeError, because the
    handler logs one exactly like a genuine I/O failure and the log then
    says the machine refused something it never attempted."""
    mgr, trash = _manager(tmp_path)
    in_trash = trash / "notes.txt"
    in_trash.write_text("contents")

    with caplog.at_level(logging.WARNING, logger="modules.cleanup.trash"):
        assert mgr.restore(str(in_trash)) is False

    assert in_trash.exists(), "a refused restore must not lose the file"
    raised = [r for r in caplog.records if r.exc_info]
    assert raised == [], f"answered by exception, not by decision: {raised}"


def test_restore_refuses_to_overwrite_an_existing_file(tmp_path):
    mgr, trash = _manager(tmp_path)
    original = tmp_path / "home" / "notes.txt"
    original.parent.mkdir()
    original.write_text("the newer one")
    in_trash = trash / "notes.txt"
    in_trash.write_text("the trashed one")

    assert mgr.restore(str(in_trash), str(original)) is False
    assert original.read_text() == "the newer one"
