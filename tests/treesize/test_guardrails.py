"""Spec 7.2: path guardrails.

The spec calls these the highest-value defence in the module. The threat is not
a user typing "delete C:\\" — it is a path-assembly bug in the MFT reader
producing a path nobody intended, and a delete following it without question.
"""
import os

import pytest

from modules.treesize.actions.guardrails import (
    Refusal, check, is_allowed, is_drive_root, is_within, protected_paths,
)


def test_drive_roots_are_recognised_in_every_spelling():
    for spelling in ("C:\\", "c:\\", "C:/", "D:\\"):
        assert is_drive_root(spelling), spelling


def test_a_folder_on_a_drive_is_not_a_root():
    assert not is_drive_root("C:\\Windows")
    assert not is_drive_root("C:\\Windows\\")


def test_drive_roots_are_refused_even_with_the_override():
    """There is no legitimate 'delete C:\\', so the override does not unlock it."""
    with pytest.raises(Refusal, match="drive root"):
        check("C:\\", override=True)


def test_protected_directories_are_refused():
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    with pytest.raises(Refusal, match="protected"):
        check(windows)


def test_the_override_unlocks_paths_inside_a_protected_system_tree():
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    inside = os.path.join(windows, "Temp", "junk")
    with pytest.raises(Refusal):
        check(inside)
    check(inside, override=True)          # must not raise


def test_the_override_does_not_unlock_a_protected_directory_itself():
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    with pytest.raises(Refusal):
        check(windows, override=True)


def test_a_parent_of_a_protected_directory_is_refused():
    """The case a path bug actually produces: a target that CONTAINS a
    protected directory. Deleting it would take that directory with it, so
    refusing only the protected path itself would not help.

    C:\\Users contains the profile root, and is not itself a drive root, so it
    exercises the containment rule rather than the drive-root rule.
    """
    profile = os.environ.get("USERPROFILE")
    if not profile:
        pytest.skip("no USERPROFILE on this machine")
    parent = os.path.dirname(profile)
    with pytest.raises(Refusal, match="contains a protected"):
        check(parent, override=True)


def test_ordinary_paths_are_allowed(tmp_path):
    assert is_allowed(str(tmp_path))
    assert is_allowed(str(tmp_path / "some" / "deep" / "folder"))


def test_files_inside_the_user_profile_need_no_override(tmp_path):
    """The profile is protected at its ROOT only. Clearing junk out of your own
    Downloads folder is the commonest use of this tool; demanding an override
    for it would train people to tick the box without reading it."""
    profile = os.environ.get("USERPROFILE")
    if not profile:
        pytest.skip("no USERPROFILE on this machine")
    assert is_allowed(os.path.join(profile, "Downloads", "big.iso"))
    assert is_allowed(os.path.join(profile, "Downloads"))


def test_files_inside_windows_still_need_the_override():
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    target = os.path.join(windows, "Temp", "junk")
    assert not is_allowed(target)
    assert is_allowed(target, override=True)


def test_empty_and_blank_paths_are_refused():
    for value in ("", "   ", None and ""):
        with pytest.raises(Refusal):
            check(value)


def test_normalisation_defeats_spelling_tricks():
    """Comparison is on the resolved path, not the string handed in."""
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    for variant in (windows + "\\", windows + "\\.", windows.lower(),
                    windows.replace("\\", "/")):
        with pytest.raises(Refusal):
            check(variant)


def test_traversal_back_into_a_protected_directory_is_refused():
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    sneaky = os.path.join(windows, "Temp", "..", "..", os.path.basename(windows))
    with pytest.raises(Refusal):
        check(sneaky)


def test_is_within_does_not_match_a_sibling_with_a_shared_prefix():
    """C:\\Windows10 is not inside C:\\Windows, though startswith says it is."""
    assert is_within("C:\\Windows\\System32", "C:\\Windows")
    assert is_within("C:\\Windows", "C:\\Windows")
    assert not is_within("C:\\Windows10", "C:\\Windows")
    assert not is_within("C:\\Win", "C:\\Windows")


def test_the_user_profile_root_is_protected():
    profile = os.environ.get("USERPROFILE")
    if not profile:
        pytest.skip("no USERPROFILE on this machine")
    with pytest.raises(Refusal):
        check(profile)
    assert _normalised_in(profile, protected_paths())


def _normalised_in(path, protected):
    from modules.treesize.actions.guardrails import _normalise
    return _normalise(path) in protected


def test_is_allowed_mirrors_check_without_raising():
    assert not is_allowed("C:\\")
    windows = os.environ.get("SystemRoot", "C:\\Windows")
    assert not is_allowed(windows)
