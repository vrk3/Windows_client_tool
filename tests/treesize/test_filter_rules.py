"""Spec 3.6: "Rules match on path glob, extension, size range, and age."

FilterSet matched names and sizes only. Two rules were missing outright:

- **Path globs.** `*.tmp` matched, but `*\\node_modules\\*` could not, because
  the predicate never saw a path. That is the rule people actually reach for.
- **Age.** Absent entirely, though it is half of what a cleanup tool is for.

Extension is covered by name globs (`*.tmp`) and needs no separate rule.
"""
import pytest

from modules.treesize.scan.filters import FilterSet, days_to_filetime, filetime_now
from modules.treesize.store.node_store import DIR

DAY = 24 * 60 * 60 * 10_000_000          # one day in FILETIME ticks


def test_filetime_now_is_a_plausible_windows_timestamp():
    """FILETIME epoch is 1601; 'now' must be past 2020 and short of 2100."""
    now = filetime_now()
    assert 13_200_000_000_000_0000 < now < 19_000_000_000_000_0000


def test_days_to_filetime_converts_whole_days():
    assert days_to_filetime(1) == DAY
    assert days_to_filetime(0) == 0


def test_path_glob_excludes_by_full_path():
    f = FilterSet(exclude_path_globs=("*\\node_modules\\*",))
    assert f.excludes("thing.js", 10, 0,
                      path="C:\\src\\node_modules\\thing.js") is True
    assert f.excludes("thing.js", 10, 0, path="C:\\src\\app\\thing.js") is False


def test_path_glob_is_case_insensitive():
    f = FilterSet(exclude_path_globs=("*\\TEMP\\*",))
    assert f.excludes("a.txt", 10, 0, path="C:\\Users\\me\\temp\\a.txt") is True


def test_path_glob_is_inert_when_no_path_is_supplied():
    """The MFT prune pass may not have a path for every node; a rule that
    cannot be evaluated must not fire, rather than guessing."""
    f = FilterSet(exclude_path_globs=("*\\node_modules\\*",))
    assert f.excludes("thing.js", 10, 0) is False


def test_name_glob_still_works_alongside_path_globs():
    f = FilterSet(exclude_globs=("*.tmp",),
                  exclude_path_globs=("*\\cache\\*",))
    assert f.excludes("a.tmp", 10, 0, path="C:\\keep\\a.tmp") is True
    assert f.excludes("b.txt", 10, 0, path="C:\\cache\\b.txt") is True
    assert f.excludes("c.txt", 10, 0, path="C:\\keep\\c.txt") is False


def test_min_age_excludes_files_younger_than_the_threshold():
    now = filetime_now()
    f = FilterSet(min_age_days=30, now=now)
    assert f.excludes("fresh.bin", 10, 0, mtime=now - 5 * DAY) is True
    assert f.excludes("stale.bin", 10, 0, mtime=now - 90 * DAY) is False


def test_max_age_excludes_files_older_than_the_threshold():
    now = filetime_now()
    f = FilterSet(max_age_days=30, now=now)
    assert f.excludes("ancient.bin", 10, 0, mtime=now - 90 * DAY) is True
    assert f.excludes("recent.bin", 10, 0, mtime=now - 5 * DAY) is False


def test_age_rules_never_exclude_directories():
    """Same reasoning as the size rules: a folder's age says nothing about
    whether its contents match, and dropping it drops the whole subtree."""
    now = filetime_now()
    f = FilterSet(max_age_days=1, now=now)
    assert f.excludes("olddir", 0, DIR, mtime=now - 900 * DAY) is False


def test_age_rules_are_inert_without_an_mtime():
    now = filetime_now()
    f = FilterSet(max_age_days=1, now=now)
    assert f.excludes("nostamp.bin", 10, 0, mtime=0) is False


def test_age_and_size_compose():
    now = filetime_now()
    f = FilterSet(min_size=1000, max_age_days=30, now=now)
    assert f.excludes("big-old.bin", 5000, 0, mtime=now - 90 * DAY) is True
    assert f.excludes("small-new.bin", 10, 0, mtime=now - DAY) is True
    assert f.excludes("big-new.bin", 5000, 0, mtime=now - DAY) is False


def test_every_rule_still_counts_one_exclusion_per_entry():
    now = filetime_now()
    f = FilterSet(exclude_globs=("*.tmp",), min_size=1000,
                  max_age_days=30, now=now)
    assert f.excludes("tiny-old.tmp", 1, 0, mtime=now - 90 * DAY) is True
    assert f.excluded_count == 1
