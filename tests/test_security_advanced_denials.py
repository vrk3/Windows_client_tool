r"""Two more checks that state hardware facts they were refused.

2026-08-22 fixed this shape in `check_secure_boot_tpm`: a check that could not
run is Unknown, not False. The same bug was still live in two Advanced-tab
checks, and the reason it survived is that **PowerShell exits 0 in both
cases** -- so the `rc != 0` guard each one opens with never fires.

Captured from this box, unelevated, 2026-08-24:

    Get-Tpm              rc=0  out={"TpmPresent":null,"TpmReady":null,
                                    "TpmEnabled":null}          err=''
    Get-BitLockerVolume  rc=0  out=''   err='Get-CimInstance : Access denied'

`bool(None)` is `False`, so the nulls sailed through into a red
"No TPM -- Not present" verdict about a machine with a TPM 2.0 (proven
elevated on 2026-08-22). The BitLocker one reported a refusal as "No volumes
or not available".
"""
import pytest

from modules.security_dashboard import security_reader
from modules.security_dashboard.security_reader import NEEDS_ADMIN


REAL_TPM_DENIED = '{"TpmPresent":null,"TpmReady":null,"TpmEnabled":null}'
REAL_BL_DENIED = (
    "Get-CimInstance : Access denied\n"
    r"At C:\WINDOWS\system32\WindowsPowerShell\v1.0\Modules\BitLocker"
    r"\BitLocker.psm1:144 char:13"
)


@pytest.fixture
def ps(monkeypatch):
    """Pin what `_ps` returns for the check under test."""
    def _install(rc, out, err=""):
        monkeypatch.setattr(
            security_reader, "_ps", lambda *a, **k: (rc, out, err))
    return _install


# ── Get-Tpm ───────────────────────────────────────────────────────────────

def test_null_tpm_fields_are_a_refusal_not_an_absent_chip(ps):
    ps(0, REAL_TPM_DENIED)

    result = security_reader.check_tpm_details()

    assert "No TPM" not in result["status"]
    assert "Not present" not in str(result["details"])
    assert NEEDS_ADMIN in result["status"] + str(result["details"])


def test_a_refused_tpm_is_not_scored_red(ps):
    """Red is a finding about the machine. We have no finding."""
    ps(0, REAL_TPM_DENIED)

    assert security_reader.check_tpm_details()["color"] != "red"


def test_a_genuinely_absent_tpm_is_still_reported_absent(ps):
    ps(0, '{"TpmPresent":false,"TpmReady":false,"TpmEnabled":false}')

    result = security_reader.check_tpm_details()

    assert result["status"] == "No TPM"
    assert result["color"] == "red"


def test_a_readable_tpm_still_reads(ps):
    ps(0, '{"TpmPresent":true,"TpmReady":true,"TpmEnabled":true}')

    result = security_reader.check_tpm_details()

    assert result["status"] == "Ready"
    assert result["color"] == "green"


# ── Get-BitLockerVolume ───────────────────────────────────────────────────

def test_access_denied_on_stderr_is_not_an_absence_of_volumes(ps):
    ps(0, "", REAL_BL_DENIED)

    result = security_reader.check_bitlocker_encryption()

    assert "No volumes" not in str(result["details"])
    assert NEEDS_ADMIN in result["status"] + str(result["details"])


def test_a_machine_with_genuinely_no_volumes_still_says_so(ps):
    ps(0, "", "")

    result = security_reader.check_bitlocker_encryption()

    assert NEEDS_ADMIN not in result["status"]


def test_a_readable_bitlocker_volume_still_reads(ps):
    ps(0, '{"MountPoint":"C:","EncryptionMethod":"XtsAes128",'
          '"VolumeStatus":"FullyEncrypted","ProtectionStatus":1}')

    result = security_reader.check_bitlocker_encryption()

    assert result["status"] == "C: Protected"
    assert result["color"] == "green"
