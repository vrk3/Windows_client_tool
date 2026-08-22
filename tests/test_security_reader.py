"""The Security Dashboard must not invent hardware facts it could not read.

Three of its four checks need administrator rights: BitLocker and TPM go
through WMI namespaces that answer WBEM_E_ACCESS_DENIED (0x80041003) to an
ordinary user, and `Confirm-SecureBootUEFI` fails with "Unable to set proper
privileges. Access was denied." Every one of those was being rendered as a
statement about the machine rather than about the query:

    Secure Boot   N/A (BIOS/Legacy)      <- this box is UEFI
    TPM           Error: <x_wmi: ...>    <- unreadable, and scored as absent
    verdict       Insecure  (red)        <- because nothing could be asked

The strings below are the ones this machine really produced, unelevated,
on 2026-08-22.
"""
import pytest

from modules.security_dashboard import security_reader


REAL_SECUREBOOT_DENIED = "Unable to set proper privileges. Access was denied."


@pytest.fixture
def denied_wmi(monkeypatch):
    """Make every WMI namespace answer access-denied, as it does unelevated."""
    import pywintypes
    import wmi

    def deny(*args, **kwargs):
        raise wmi.x_access_denied(
            "Unexpected COM Error",
            pywintypes.com_error(
                -2147217405, "OLE error 0x80041003", None, None
            ),
        )

    monkeypatch.setattr(wmi, "WMI", deny)
    return deny


def _detail(result, label):
    for name, value in result["details"]:
        if name == label:
            return value
    return None


def test_bitlocker_access_denied_asks_for_administrator(denied_wmi):
    result = security_reader.check_bitlocker()

    assert "admin" in result["status"].lower()
    assert "x_wmi" not in result["status"]
    assert "0x80041003" not in result["status"]


def test_tpm_access_denied_is_not_scored_as_absent(denied_wmi, monkeypatch):
    monkeypatch.setattr(
        security_reader, "_ps", lambda *a, **k: (0, "True", "")
    )

    result = security_reader.check_secure_boot_tpm()

    assert "admin" in _detail(result, "TPM").lower()
    assert result["color"] != "red"


def test_secure_boot_denied_is_not_reported_as_legacy_bios(monkeypatch):
    monkeypatch.setattr(
        security_reader, "_ps",
        lambda *a, **k: (1, "", REAL_SECUREBOOT_DENIED),
    )
    monkeypatch.setattr(
        security_reader, "_secure_boot_from_registry", lambda: None
    )

    result = security_reader.check_secure_boot_tpm()

    assert "BIOS/Legacy" not in _detail(result, "Secure Boot")


def test_secure_boot_falls_back_to_the_registry_when_denied(monkeypatch):
    """The State key is readable without elevation and holds the real answer."""
    monkeypatch.setattr(
        security_reader, "_ps",
        lambda *a, **k: (1, "", REAL_SECUREBOOT_DENIED),
    )
    monkeypatch.setattr(
        security_reader, "_secure_boot_from_registry", lambda: False
    )

    result = security_reader.check_secure_boot_tpm()

    assert _detail(result, "Secure Boot") == "Disabled"


def test_secure_boot_registry_reader_agrees_with_this_machine():
    """No mocks: the real key, read unelevated."""
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\SecureBoot\State",
        )
        expected = bool(winreg.QueryValueEx(key, "UEFISecureBootEnabled")[0])
    except OSError:
        expected = None  # legacy BIOS: the key does not exist

    assert security_reader._secure_boot_from_registry() is expected
