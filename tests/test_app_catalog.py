# tests/test_app_catalog.py
import json
import os
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def catalog_path():
    base = os.path.join(os.path.dirname(__file__), "..", "src",
                        "modules", "tweaks", "definitions", "app_catalog.json")
    return os.path.abspath(base)


def test_load_catalog_returns_list(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    items = c.entries
    assert len(items) > 0
    assert all("winget_id" in item for item in items)


def test_catalog_categories(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    cats = c.categories()
    assert "Browsers" in cats
    assert "Development" in cats


def test_filter_by_category(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    browsers = c.filter_by_category("Browsers")
    assert all(e["category"] == "Browsers" for e in browsers)
    assert len(browsers) >= 2


def test_detect_installed_parses_winget_output(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    fake_output = (
        "Name                           Id                    Version\n"
        "--------------------------------------------------------------\n"
        "Mozilla Firefox                Mozilla.Firefox       123.0\n"
        "Git                            Git.Git               2.44.0\n"
    )
    installed = c._parse_winget_list(fake_output)
    assert "Mozilla.Firefox" in installed
    assert "Git.Git" in installed


def test_detect_installed_empty_on_bad_output(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    installed = c._parse_winget_list("winget not found")
    assert isinstance(installed, set)


def test_get_appx_packages_parses_output(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    fake = "Microsoft.3DViewer\nMicrosoft.XboxGameBar\nMicrosoft.OneDriveSync\n"
    result = c._parse_appx_list(fake)
    assert "Microsoft.3DViewer" in result
    assert "Microsoft.XboxGameBar" in result


# --- removal has to be verified, not assumed -------------------------------
#
# `Get-AppxPackage 'Microsoft.NoSuchThing' | Remove-AppxPackage` exits 0 and
# prints nothing, so returning `rc == 0` reported a removal that never
# happened -- and the Tweaks Apps tab then said "Everything applied
# successfully". Measured on this machine, not assumed.

class _Recorder:
    """Stands in for subprocess.run: canned answers, in call order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        rc, out, err = self.answers.pop(0)
        return type("P", (), {"returncode": rc, "stdout": out, "stderr": err})()


def test_a_removal_that_left_the_package_there_is_not_a_success(monkeypatch,
                                                               catalog_path):
    """Reported from the running app: TreeSize's context-menu package was
    selected, the app said "everything applied successfully", and the package
    is still installed."""
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([
        (0, "JAMSoftware.TreeSizeContextMenu\nOther.Package", ""),  # before
        (0, "", ""),                                                # removal
        (0, "JAMSoftware.TreeSizeContextMenu\nOther.Package", ""),  # after
    ])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu",
                         on_output=lines.append) is False
    assert any("still installed" in line for line in lines)


def test_a_removal_that_actually_removed_it_is_a_success(monkeypatch,
                                                         catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([
        (0, "JAMSoftware.TreeSizeContextMenu\nOther.Package", ""),  # before
        (0, "", ""),                                                # removal
        (0, "Other.Package", ""),                                   # after
    ])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu") is True


def test_a_check_that_did_not_run_is_never_read_as_removed(monkeypatch,
                                                           catalog_path):
    """THE bug. Empty stdout was read as "the package is gone" without ever
    looking at the return code or stderr -- so a package list that could not
    be read at all reported a successful removal. A refused read is not an
    absent value; that rule is all over this codebase and this call broke it.
    """
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([
        (0, "JAMSoftware.TreeSizeContextMenu", ""),   # before: it is there
        (0, "", ""),                                   # removal: silent
        (1, "", "Access is denied."),                  # after: the CHECK failed
    ])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu",
                         on_output=lines.append) is False
    assert any("could not" in line.lower() for line in lines)


def test_a_package_that_cannot_be_seen_beforehand_is_not_quietly_fine(
        monkeypatch, catalog_path):
    """If the package is not visible in the context doing the removing, the
    pipeline removes nothing and says nothing -- which must not read as done.
    """
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([(0, "Other.Package", "")])   # before: not listed
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu",
                         on_output=lines.append) is False
    assert any("not visible" in line.lower() or "not installed" in line.lower()
               for line in lines)
    assert len(recorder.calls) == 1, "it tried to remove something it cannot see"


# --- Win32 / winget apps ---------------------------------------------------
#
# The Apps tab listed AppX packages only, so TreeSize -- a Win32 app with a
# registry uninstall entry -- could not be uninstalled from it at all, and the
# AppX package that *was* listed is only its shell context menu.
#
# Column geometry below is REAL `winget list` output from this machine
# (Name 0, Id 61, Version 152, Available 182, Source 192). Splitting it on
# whitespace cannot work: 24 of 139 rows carry an ARP id containing spaces,
# and the old "first token containing a dot" heuristic returned 66 junk ids
# out of 126 -- '.NET', 'Drv_3.00.0045', bare version numbers.

_REAL_WINGET_LIST = (
    'Name                                                         Id                                                                                         Version                       Available Source\n'
    '------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------\n'
    '7-Zip 26.02 (x64 edition)                                    7zip.7zip                                                                                  26.02.00.0                              winget\n'
    'AMD Software                                                 ARP\\Machine\\X64\\AMD Catalyst Install Manager                                               2026.04.15                              \n'
    'TreeSize V9.8.2                                              JAMSoftware.TreeSize                                                                       9.8.2                                   winget\n'
    'AV1 Video Extension                                          MSIX\\Microsoft.AV1VideoExtension_2.0.30.0_x64__8wekyb3d8bbwe                               2.0.30.0                                \n'
)


def test_winget_rows_are_read_by_column_not_by_splitting(catalog_path):
    """An id with spaces in it is the normal case for a registry-installed
    app, and no amount of whitespace splitting recovers it."""
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    rows = {r.app_id: r for r in c.parse_winget_rows(_REAL_WINGET_LIST)}
    assert r"ARP\Machine\X64\AMD Catalyst Install Manager" in rows
    amd = rows[r"ARP\Machine\X64\AMD Catalyst Install Manager"]
    assert amd.name == "AMD Software"
    assert amd.version == "2026.04.15"
    assert amd.source == ""


def test_a_version_number_is_never_mistaken_for_an_id(catalog_path):
    """'7-Zip 26.02 (x64 edition)' has a dot in its NAME. The old heuristic
    took the first dotted token and returned '26.02' as the package id."""
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    rows = {r.name: r for r in c.parse_winget_rows(_REAL_WINGET_LIST)}
    assert rows["7-Zip 26.02 (x64 edition)"].app_id == "7zip.7zip"


def test_the_installed_id_set_holds_only_real_winget_ids(catalog_path):
    """`MSIX\\...` and `ARP\\...` are winget's internal handles for things it
    did not install. Marking a catalog entry "Installed" off one of those is
    how the catalog list came to lie."""
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    ids = c._parse_winget_list(_REAL_WINGET_LIST)
    assert ids == {"7zip.7zip", "JAMSoftware.TreeSize"}


def test_desktop_apps_leave_out_what_the_appx_list_already_shows(catalog_path):
    """A `MSIX\\` row IS an AppX package; listing it in both halves of the tab
    offers two different removals of one thing."""
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    apps = c.desktop_apps_from(_REAL_WINGET_LIST)
    assert [a.name for a in apps] == ["7-Zip 26.02 (x64 edition)",
                                      "AMD Software", "TreeSize V9.8.2"]


class _WingetRecorder:
    """subprocess.run + Popen stand-in: canned answers in call order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def run(self, args, **kwargs):
        self.calls.append(args)
        rc, out, err = self.answers.pop(0)
        return type("P", (), {"returncode": rc, "stdout": out,
                              "stderr": err})()

    def popen(self, args, **kwargs):
        self.calls.append(args)
        rc, out, _ = self.answers.pop(0)

        class _P:
            stdout = out.splitlines(keepends=True)
            returncode = rc

            def wait(self):
                return rc

        return _P()


def _install_recorder(monkeypatch, recorder):
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run",
                        recorder.run)
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.Popen",
                        recorder.popen)


def test_a_winget_removal_is_verified_not_assumed(monkeypatch, catalog_path):
    """winget exiting 0 is not evidence the app is gone -- the same rule that
    the AppX side already learned the hard way."""
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _WingetRecorder([
        (0, _REAL_WINGET_LIST, ""),                       # before: listed
        (0, "Successfully uninstalled", ""),              # the uninstall
        (0, _REAL_WINGET_LIST, ""),                       # after: STILL listed
    ])
    _install_recorder(monkeypatch, recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_app_winget("JAMSoftware.TreeSize",
                               on_output=lines.append) is False
    assert any("still installed" in line.lower() for line in lines)


def test_a_winget_removal_that_worked_is_a_success(monkeypatch, catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    after = "".join(
        line + "\n" for line in _REAL_WINGET_LIST.splitlines()
        if "JAMSoftware.TreeSize" not in line)
    recorder = _WingetRecorder([
        (0, _REAL_WINGET_LIST, ""),
        (0, "Successfully uninstalled", ""),
        (0, after, ""),
    ])
    _install_recorder(monkeypatch, recorder)
    c = AppCatalog(catalog_path=catalog_path)
    assert c.remove_app_winget("JAMSoftware.TreeSize") is True


def test_a_winget_list_that_could_not_be_read_is_not_a_removal(monkeypatch,
                                                               catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _WingetRecorder([
        (0, _REAL_WINGET_LIST, ""),
        (0, "Successfully uninstalled", ""),
        (1, "", "Failed when searching source"),          # after: refused
    ])
    _install_recorder(monkeypatch, recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_app_winget("JAMSoftware.TreeSize",
                               on_output=lines.append) is False
    assert any("could not" in line.lower() for line in lines)


def test_the_uninstall_addresses_the_app_by_id_exactly(monkeypatch,
                                                       catalog_path):
    """A bare positional query matches id, name OR moniker, so it can hit
    several apps and refuse -- and an ARP id contains spaces."""
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _WingetRecorder([
        (0, _REAL_WINGET_LIST, ""),
        (0, "Successfully uninstalled", ""),
        (0, "".join(line + "\n" for line in _REAL_WINGET_LIST.splitlines()
                    if "AMD Catalyst" not in line), ""),
    ])
    _install_recorder(monkeypatch, recorder)
    c = AppCatalog(catalog_path=catalog_path)
    c.remove_app_winget(r"ARP\Machine\X64\AMD Catalyst Install Manager")
    uninstall = [call for call in recorder.calls if "uninstall" in call]
    assert uninstall, "nothing ran an uninstall"
    args = uninstall[0]
    assert "--id" in args
    assert args[args.index("--id") + 1] == \
        r"ARP\Machine\X64\AMD Catalyst Install Manager"
    assert "--exact" in args


# --- a package that puts itself back -----------------------------------
#
# Measured on this machine, 2026-08-29, in
# Microsoft-Windows-AppXDeploymentServer/Operational: the removal of
# JAMSoftware.TreeSizeContextMenu SUCCEEDED (14:46:46, "Deployment Remove
# operation ... finished successfully", folder moved to WindowsApps\Deleted),
# and ten seconds later the package was ADDED back from TreeSize's own
# install directory. A before/after snapshot cannot tell that apart from a
# removal that never happened, so it said "still installed" and left the user
# to guess. Windows knows which of the two it was; ask it.

_REAL_LOG_LINES = (
    "854\tSuccessfully added the following uri(s) to be processed: "
    "file:///C:/Users/iorda/AppData/Local/Programs/JAM%20Software/TreeSize/"
    "TreeSizeContextMenu.msix.\n"
    "603\tStarted deployment Add operation on a package with main parameter "
    "TreeSizeContextMenu.msix and Options ForceUpdateFromAnyVersion,"
    "NormalPriorityRequest and 0.\n"
    "400\tDeployment Add operation with target volume C: on Package "
    "JAMSoftware.TreeSizeContextMenu_2.0.0.0_x64__w54gjky5rxhza from: "
    "(TreeSizeContextMenu.msix) finished successfully.\n"
)


def test_the_readd_source_is_the_real_path_the_installer_used(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    source = c._parse_readd_source(_REAL_LOG_LINES,
                                   "JAMSoftware.TreeSizeContextMenu")
    assert source == (r"C:\Users\iorda\AppData\Local\Programs\JAM Software"
                      r"\TreeSize\TreeSizeContextMenu.msix")


def test_an_add_for_a_different_package_is_not_our_readd(catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    assert c._parse_readd_source(_REAL_LOG_LINES, "Microsoft.XboxGameBar") is None


def test_an_add_with_no_uri_still_names_what_it_came_from(catalog_path):
    """Event 854 is Verbose and may be filtered out; 400 still names the
    package file, and half an answer beats none."""
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    only_400 = (
        "400\tDeployment Add operation with target volume C: on Package "
        "JAMSoftware.TreeSizeContextMenu_2.0.0.0_x64__w54gjky5rxhza from: "
        "(TreeSizeContextMenu.msix) finished successfully.\n"
    )
    assert c._parse_readd_source(
        only_400, "JAMSoftware.TreeSizeContextMenu") == "TreeSizeContextMenu.msix"


def test_a_remove_line_alone_is_not_a_readd(catalog_path):
    """The log carries our own Remove events too. Reading one of those as a
    re-add would report self-healing on every successful removal."""
    from modules.tweaks.app_catalog import AppCatalog
    c = AppCatalog(catalog_path=catalog_path)
    removal_only = (
        "400\tDeployment Remove operation with target volume C: on Package "
        "JAMSoftware.TreeSizeContextMenu_2.0.0.0_x64__w54gjky5rxhza from: "
        "(JAMSoftware.TreeSizeContextMenu_2.0.0.0_x64__w54gjky5rxhza) "
        "finished successfully.\n"
    )
    assert c._parse_readd_source(
        removal_only, "JAMSoftware.TreeSizeContextMenu") is None


def test_a_package_put_back_by_its_own_installer_says_so(monkeypatch,
                                                         catalog_path):
    """The whole point: "still installed" is true but useless when the
    removal worked and something reinstalled it."""
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([
        (0, "JAMSoftware.TreeSizeContextMenu\nOther.Package", ""),  # before
        (0, "", ""),                                                # removal
        (0, "JAMSoftware.TreeSizeContextMenu\nOther.Package", ""),  # after
        (0, _REAL_LOG_LINES, ""),                                   # the log
    ])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu",
                         on_output=lines.append) is False
    said = " ".join(lines)
    assert "reinstalled" in said.lower()
    assert r"JAM Software\TreeSize\TreeSizeContextMenu.msix" in said


def test_a_removal_that_stuck_never_asks_the_log(monkeypatch, catalog_path):
    """Nothing to explain when the package is gone -- and the log query costs
    a PowerShell launch."""
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([
        (0, "JAMSoftware.TreeSizeContextMenu\nOther.Package", ""),  # before
        (0, "", ""),                                                # removal
        (0, "Other.Package", ""),                                   # after
    ])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu") is True
    assert len(recorder.calls) == 3


def test_a_log_that_says_nothing_invents_no_explanation(monkeypatch,
                                                        catalog_path):
    """An unreadable or silent log means we do not know why the package is
    still there -- which is the honest flat message, not a made-up culprit."""
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([
        (0, "JAMSoftware.TreeSizeContextMenu", ""),   # before
        (0, "", ""),                                  # removal
        (0, "JAMSoftware.TreeSizeContextMenu", ""),   # after
        (1, "", "No events were found that match the specified selection."),
    ])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_appx("JAMSoftware.TreeSizeContextMenu",
                         on_output=lines.append) is False
    said = " ".join(lines).lower()
    assert "still installed" in said
    assert "reinstalled" not in said


def test_the_reason_a_check_failed_is_reported(monkeypatch, catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([(1, "", "the RPC server is unavailable")])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    c.remove_appx("Whatever", on_output=lines.append)
    assert any("RPC server" in line for line in lines)
