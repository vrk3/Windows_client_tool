"""Quick scan locations for the Home tab's target dropdown.

Everything resolves from the ENVIRONMENT rather than from a hardcoded `C:`.
Windows is not always on C: -- least of all on the servers these entries are
aimed at -- and a hardcoded path does not fail, it quietly scans the wrong
place or nothing at all.
"""
import os

import pytest

from modules.treesize.ui import locations


FAKE = {
    "SystemDrive": "D:",
    "SystemRoot": r"D:\Windows",
    "USERPROFILE": r"D:\Users\ana",
    "LOCALAPPDATA": r"D:\Users\ana\AppData\Local",
    "ProgramData": r"D:\ProgramData",
    "TEMP": r"D:\Users\ana\AppData\Local\Temp",
}


#: No redirection, so the profile-relative fallback is what gets used.
def NO_REDIRECT(_name):
    return ""


def _all(environ=FAKE, exists=lambda _p: True, resolve=NO_REDIRECT):
    """Every location as {label: path}, flattened across groups."""
    out = {}
    for group in locations.known_locations(environ=environ, exists=exists,
                                           resolve=resolve):
        for item in group.items:
            out[item.label] = item.path
    return out


# ---- resolution ---------------------------------------------------------

def test_nothing_is_hardcoded_to_c():
    """The whole point. On a D: install every path must follow."""
    for label, path in _all().items():
        assert not path.upper().startswith("C:"), f"{label} -> {path}"


def test_the_users_folder_is_not_drive_relative():
    r"""os.path.join("D:", "Users") is "D:Users" -- a DRIVE-RELATIVE path
    meaning "Users, relative to the current directory on D:". It is not an
    error, it just silently means somewhere else."""
    path = _all()["Users"]
    assert path.lower() == r"d:\users", path
    assert os.path.isabs(path)


def test_the_five_that_were_asked_for_are_present():
    found = _all()
    assert found["Desktop"] == r"D:\Users\ana\Desktop"
    assert found["Current user"] == r"D:\Users\ana"
    assert found["Users"] == r"D:\Users"
    assert found["Windows Temp"] == r"D:\Windows\Temp"


def test_downloads_and_documents_are_present():
    found = _all()
    assert found["Downloads"] == r"D:\Users\ana\Downloads"
    assert found["Documents"] == r"D:\Users\ana\Documents"


def test_user_temp_is_distinct_from_windows_temp():
    """Two different places, and the user one is usually the bigger win."""
    found = _all()
    assert found["User Temp"] != found["Windows Temp"]


def test_the_big_windows_caches_are_offered():
    found = _all()
    assert found["Windows Update cache"] == r"D:\Windows\SoftwareDistribution\Download"
    assert found["Installer cache"] == r"D:\Windows\Installer"
    assert found["Package Cache"] == r"D:\ProgramData\Package Cache"


def test_the_server_log_locations_are_offered():
    found = _all()
    assert found["IIS logs"] == r"D:\inetpub\logs"
    assert found["Windows Logs"] == r"D:\Windows\Logs"
    assert found["System log files"] == r"D:\Windows\System32\LogFiles"


# ---- grouping -----------------------------------------------------------

def test_groups_come_back_in_menu_order():
    groups = [g.name for g in locations.known_locations(environ=FAKE, exists=lambda _p: True,
                                                        resolve=NO_REDIRECT)]
    assert groups == [locations.PLACES, locations.TEMP, locations.LOGS]


def test_every_group_has_a_name_and_items():
    for group in locations.known_locations(environ=FAKE, exists=lambda _p: True,
                                  resolve=NO_REDIRECT):
        assert group.name and group.items


# ---- existence filtering ------------------------------------------------

def test_a_location_that_does_not_exist_is_hidden():
    """The server entries are the reason. Offering \\inetpub\\logs on a laptop
    is a menu item whose only outcome is an error."""
    def exists(path):
        return "inetpub" not in path.lower()

    labels = _all(exists=exists)
    assert "IIS logs" not in labels
    assert "Desktop" in labels


def test_a_group_that_empties_out_disappears_entirely():
    """An empty submenu is worse than no submenu."""
    def only_places(path):
        # Not merely "under D:\Users": the user Temp and CrashDumps entries
        # live under the profile too, and letting them through would leave
        # the other groups populated and prove nothing.
        lowered = path.lower()
        return lowered.startswith(r"d:\users") and "appdata" not in lowered

    groups = [g.name for g in locations.known_locations(environ=FAKE, exists=only_places,
                                                        resolve=NO_REDIRECT)]
    assert locations.LOGS not in groups


def test_everything_vanishing_is_not_a_crash():
    assert locations.known_locations(environ=FAKE, exists=lambda _p: False,
                                     resolve=NO_REDIRECT) == []


# ---- robustness ---------------------------------------------------------

def test_a_missing_environment_variable_drops_only_what_needs_it():
    """A stripped service environment must not take the whole menu with it."""
    stripped = dict(FAKE)
    del stripped["LOCALAPPDATA"]
    del stripped["TEMP"]
    labels = _all(environ=stripped)
    assert "Desktop" in labels and "Windows Temp" in labels
    assert "User Temp" not in labels


def test_an_empty_environment_yields_nothing_rather_than_junk():
    """Better an empty menu than one full of paths rooted at "\"."""
    assert locations.known_locations(environ={}, exists=lambda _p: True,
                                     resolve=NO_REDIRECT) == []


def test_duplicates_are_collapsed():
    """If TEMP happens to point at the Windows temp folder, it must not appear
    twice under two names."""
    same = dict(FAKE, TEMP=r"D:\Windows\Temp")
    paths = [item.path.lower()
             for group in locations.known_locations(environ=same, exists=lambda _p: True,
                                                    resolve=NO_REDIRECT)
             for item in group.items]
    assert len(paths) == len(set(paths)), paths


def test_the_real_environment_produces_something_usable():
    """Not a fake: on this actual machine the list must not be empty, and
    every path it offers must really be there."""
    groups = locations.known_locations()
    assert groups, "no quick locations at all on a real Windows box"
    for group in groups:
        for item in group.items:
            assert os.path.isdir(item.path), f"{item.label} -> {item.path}"


# ---- redirected known folders -------------------------------------------
#
# OneDrive's Known Folder Move redirects Desktop/Documents/Downloads by
# default on a modern install. Guessing %USERPROFILE%\Desktop is not a
# near-miss. On the machine this was written on, Desktop lives in OneDrive and
# the profile copy does NOT exist -- so the guess offered nothing -- while a
# stale empty %USERPROFILE%\Documents DOES exist, so the guess offered the
# WRONG folder and looked entirely plausible doing it.

REDIRECTED = {
    "Desktop": r"D:\Users\ana\OneDrive\Desktop",
    "Documents": r"D:\Users\ana\OneDrive\Documents",
    "Downloads": r"D:\Users\ana\Downloads",
}


def test_the_shells_answer_beats_the_profile_guess():
    found = _all(resolve=lambda name: REDIRECTED.get(name, ""))
    assert found["Desktop"] == r"D:\Users\ana\OneDrive\Desktop"
    assert found["Documents"] == r"D:\Users\ana\OneDrive\Documents"


def test_a_redirected_desktop_is_found_even_though_the_profile_one_is_gone():
    """The exact shape of the real failure: only the redirected path exists."""
    def exists(path):
        return "onedrive" in path.lower() or "desktop" not in path.lower()

    found = _all(exists=exists, resolve=lambda n: REDIRECTED.get(n, ""))
    assert found.get("Desktop") == r"D:\Users\ana\OneDrive\Desktop"


def test_the_profile_path_is_used_when_the_shell_says_nothing():
    """No pywin32, or no redirection: the fallback still has to work."""
    found = _all(resolve=lambda _n: "")
    assert found["Desktop"] == r"D:\Users\ana\Desktop"


def test_a_broken_shell_lookup_does_not_take_the_menu_down():
    def explode(_name):
        raise OSError("the shell is having a day")

    with pytest.raises(OSError):
        explode("Desktop")
    # shell_folder swallows it; known_locations must then use the fallback.
    found = _all(resolve=lambda n: locations.shell_folder("no such folder"))
    assert found["Desktop"] == r"D:\Users\ana\Desktop"


def test_the_real_desktop_is_offered_on_this_machine():
    """Regression for the bug this section exists for: Desktop was silently
    absent from the real list because of OneDrive redirection."""
    labels = {item.label for group in locations.known_locations()
              for item in group.items}
    assert "Desktop" in labels
