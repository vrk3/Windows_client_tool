# tests/test_app_catalog.py
import json, os, pytest
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
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([(0, "", ""),                    # the removal
                          (0, "Microsoft.BingSearch", "")])  # still installed
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    assert c.remove_appx("Microsoft.BingSearch") is False
    assert len(recorder.calls) == 2, "it never checked whether the package went"


def test_a_removal_that_actually_removed_it_is_a_success(monkeypatch,
                                                         catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([(0, "", ""), (0, "", "")])   # gone afterwards
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    assert c.remove_appx("Microsoft.BingSearch") is True


def test_a_refusal_is_reported_with_its_reason(monkeypatch, catalog_path):
    from modules.tweaks.app_catalog import AppCatalog
    recorder = _Recorder([(0, "", "Access is denied."),
                          (0, "Microsoft.BingSearch", "")])
    monkeypatch.setattr("modules.tweaks.app_catalog.subprocess.run", recorder)
    c = AppCatalog(catalog_path=catalog_path)
    lines = []
    assert c.remove_appx("Microsoft.BingSearch", on_output=lines.append) is False
    assert any("Access is denied" in line for line in lines)
