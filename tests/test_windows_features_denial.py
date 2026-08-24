r""""0 features - 0 enabled" was a refusal, not a machine with no features.

`dism /online /get-features` needs elevation. Unelevated on this box,
2026-08-24:

    rc = 740
    stdout = "\nError: 740\n\nElevated permissions are required to run DISM.\n
              Use an elevated command prompt to complete these tasks.\n"

`_fetch_all_features` never looked at `returncode`. It handed that text to
`_parse_features`, which keeps only lines containing "|", found none, and
returned an empty list -- which the pane rendered as the flat assertion
"0 features - 0 enabled".

Same family as the Get-Tpm and Get-BitLockerVolume fixes: a check that could
not run is Unknown, not zero.
"""
import subprocess

import pytest

from modules.windows_features import features_module


REAL_DISM_740 = (
    "\nError: 740\n\n"
    "Elevated permissions are required to run DISM.\n"
    "Use an elevated command prompt to complete these tasks.\n"
)

REAL_DISM_TABLE = (
    "Features listing for package : Microsoft-Windows-Foundation-Package\n\n"
    "Feature Name                | State\n"
    "----------------------------| -------------\n"
    "Printing-Foundation-Features| Enabled\n"
    "TelnetClient                | Disabled\n"
)


@pytest.fixture
def dism(monkeypatch):
    def _install(returncode, stdout, stderr=""):
        monkeypatch.setattr(
            subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(
                a[0] if a else [], returncode, stdout, stderr),
        )
    return _install


def test_a_refused_dism_does_not_report_zero_features(dism):
    dism(740, REAL_DISM_740)

    with pytest.raises(PermissionError):
        features_module._fetch_all_features()


def test_the_refusal_names_elevation_rather_than_an_exit_code(dism):
    dism(740, REAL_DISM_740)

    with pytest.raises(PermissionError) as caught:
        features_module._fetch_all_features()

    assert "administrator" in str(caught.value).lower()


def test_another_dism_failure_is_reported_but_not_as_a_denial(dism):
    dism(87, "Error: 87\nThe get-features option is unknown.\n")

    with pytest.raises(RuntimeError) as caught:
        features_module._fetch_all_features()

    assert not isinstance(caught.value, PermissionError)
    assert "87" in str(caught.value)


def test_a_successful_listing_still_parses(dism):
    dism(0, REAL_DISM_TABLE)

    features = features_module._fetch_all_features()

    assert ("Printing-Foundation-Features", "Enabled") in features
    assert ("TelnetClient", "Disabled") in features


def test_a_genuinely_empty_but_successful_listing_is_still_empty(dism):
    dism(0, "Feature Name                | State\n")

    assert features_module._fetch_all_features() == []
