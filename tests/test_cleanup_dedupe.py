"""Two scanners pointing at one directory must not count it twice.

Measured on this machine before the fix: `scan_temp_files` reports 39.4 GB
and `scan_user_crash_dumps` reports 39.4 GB, because `%TEMP%` and
`%LOCALAPPDATA%\\Temp` are the SAME directory on Windows. `_ScanTab` merged
them with `merged.total_size += r.total_size`, so the tab offered 78.8 GB
of "junk" for 39.4 GB of files — and Clean then tried to delete the same
tree twice.

That was survivable while only 133 of 537 scanners were wired into the UI.
It stops being survivable the moment the other 404 are surfaced, which is
what this dedupe exists to make safe.
"""
import os

from modules.cleanup.cleanup_scanner._common import (
    ScanItem, dedupe_items, total_of,
)


def _item(path, size=100, is_dir=True):
    return ScanItem(path=path, size=size, is_dir=is_dir)


def test_the_same_path_twice_counts_once():
    items = [_item(r"C:\Temp"), _item(r"C:\Temp")]
    assert len(dedupe_items(items)) == 1
    assert total_of(items) == 100


def test_the_same_path_spelled_differently_counts_once():
    """%TEMP% and %LOCALAPPDATA%\\Temp resolve to one directory; the two
    scanners that found it spelled it differently."""
    items = [_item(r"C:\Users\x\AppData\Local\Temp"),
             _item(r"C:\Users\x\AppData\Local\Temp\\"),
             _item(r"C:\Users\x\AppData\Local\.\Temp")]
    assert len(dedupe_items(items)) == 1


def test_case_differences_do_not_defeat_it():
    items = [_item(r"C:\Windows\Temp"), _item(r"c:\windows\temp")]
    assert len(dedupe_items(items)) == 1


def test_a_file_inside_a_counted_directory_is_dropped():
    """%TEMP%\\*.dmp is already inside %TEMP%; counting the dumps again
    inflates the total by their size."""
    items = [_item(r"C:\Temp", size=1000),
             _item(r"C:\Temp\crash.dmp", size=250, is_dir=False)]
    kept = dedupe_items(items)
    assert len(kept) == 1
    assert kept[0].path == r"C:\Temp"
    assert total_of(items) == 1000


def test_a_sibling_directory_is_not_dropped():
    """Only NESTED paths are covered — a name that merely starts with the
    same characters is a different directory."""
    items = [_item(r"C:\Temp"), _item(r"C:\Temporary")]
    assert len(dedupe_items(items)) == 2


def test_the_first_occurrence_wins():
    """Callers control precedence by ordering, so a curated scanner listed
    first keeps its own label and safety."""
    first = _item(r"C:\Temp", size=10)
    second = _item(r"C:\Temp", size=999)
    kept = dedupe_items([first, second])
    assert kept == [first]


def test_unrelated_items_are_untouched():
    items = [_item(r"C:\A"), _item(r"C:\B"), _item(r"C:\C")]
    assert len(dedupe_items(items)) == 3
    assert total_of(items) == 300


def test_an_empty_list_is_fine():
    assert dedupe_items([]) == []
    assert total_of([]) == 0


def test_files_only_still_deduplicates():
    """No directories in the list means no nesting pass; exact duplicates
    must still collapse."""
    items = [_item(r"C:\a.log", is_dir=False), _item(r"C:\a.log", is_dir=False)]
    assert len(dedupe_items(items)) == 1


def test_the_real_overlap_this_was_written_for():
    """The measured case, with the paths as the two scanners produce them."""
    local_temp = os.path.join(r"C:\Users\x\AppData\Local", "Temp")
    items = [
        _item(local_temp, size=39_392),                     # scan_temp_files
        _item(local_temp, size=39_392),                     # scan_user_crash_dumps
        _item(os.path.join(local_temp, "x.dmp"), size=12, is_dir=False),
    ]
    assert total_of(items) == 39_392, "the tab would have offered 78,796"
