import os
import tempfile
import time

import pytest

from core.log_rotation import rotate_old_files


@pytest.fixture
def log_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


def _touch_with_age(path: str, days_old: int) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("x")
    old_time = time.time() - (days_old * 86400)
    os.utime(path, (old_time, old_time))


def test_rotate_zero_retention_keeps_everything(log_dir):
    old_file = os.path.join(log_dir, "old.log")
    _touch_with_age(old_file, 9999)
    deleted = rotate_old_files(log_dir, "*.log", retention_days=0)
    assert deleted == 0
    assert os.path.exists(old_file)


def test_rotate_deletes_old_files_only(log_dir):
    old_file = os.path.join(log_dir, "old.log")
    new_file = os.path.join(log_dir, "new.log")
    _touch_with_age(old_file, 60)
    _touch_with_age(new_file, 1)

    deleted = rotate_old_files(log_dir, "*.log", retention_days=30)

    assert deleted == 1
    assert not os.path.exists(old_file)
    assert os.path.exists(new_file)


def test_rotate_respects_glob_pattern(log_dir):
    old_log = os.path.join(log_dir, "old.log")
    old_html = os.path.join(log_dir, "old.html")
    _touch_with_age(old_log, 60)
    _touch_with_age(old_html, 60)

    deleted = rotate_old_files(log_dir, "*.log", retention_days=30)

    assert deleted == 1
    assert not os.path.exists(old_log)
    assert os.path.exists(old_html)  # different pattern, untouched


def test_rotate_missing_directory_is_a_noop():
    assert rotate_old_files(os.path.join(tempfile.gettempdir(), "does-not-exist-xyz"), "*.log", 30) == 0


def test_rotate_empty_directory_string_is_a_noop():
    assert rotate_old_files("", "*.log", 30) == 0
