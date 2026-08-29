"""Being refused costs five seconds. Do not buy it when the answer is known.

Measured unelevated on this machine, 2026-08-29, opening Device & Boot:

    bitlocker_encryption_detail   5.41s   -> None    (Get-BitLockerVolume)
    secure_boot                   5.24s   -> None    (MicrosoftTpm namespace)
    bitlocker_system_drive        5.02s   -> False   (MicrosoftVolumeEncryption)

16.79s for that one tab, against 1.9s elevated. Every second of it is spent
being told "no" by something that cannot answer an ordinary user, and a
process cannot gain elevation while it runs -- so the refusal is knowable
before it is paid for.

The third line is worse than slow. `read()` documents that None means "we
could not look" and is "never collapsed into False", and a reader says so with
`available: False`. check_bitlocker's WMI failure path returned only a status
string, so `read_value` -- `"Protected" in status` -- turned "Requires
administrator" into **False**: not "we could not look" but "your system drive
is NOT encrypted". `tools/security_refusal_sweep.py` swept all 149 controls
and this was the only one. It is invisible here, on a machine whose C: really
is unencrypted, and wrong on any machine that is -- and `read()` is what
staging, baselines and profiles compare, not just what the card prints.
"""
import pytest

from modules.security_dashboard import security_reader
from modules.security_dashboard.security_reader import NEEDS_ADMIN
from modules.security_dashboard.catalog import load_catalog


@pytest.fixture(autouse=True)
def clear_cache():
    security_reader._denied_namespaces.clear()
    yield
    security_reader._denied_namespaces.clear()


@pytest.fixture
def unelevated(monkeypatch):
    monkeypatch.setattr(security_reader, "is_admin", lambda: False)


@pytest.fixture
def elevated(monkeypatch):
    monkeypatch.setattr(security_reader, "is_admin", lambda: True)


@pytest.fixture
def count_wmi(monkeypatch):
    """Every namespace actually dialled. Dialling is the 5 seconds."""
    dialled = []

    def fake_wmi(*args, **kwargs):
        dialled.append(kwargs.get("namespace"))
        raise AssertionError("this test must not reach a real WMI connect")

    import wmi
    monkeypatch.setattr(wmi, "WMI", fake_wmi)
    return dialled


@pytest.fixture
def count_powershell(monkeypatch):
    """Every PowerShell command run."""
    ran = []

    def fake_ps(cmd, timeout=30):
        ran.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(security_reader, "_ps", fake_ps)
    return ran


# --- the correctness half ---------------------------------------------------

def test_a_refused_bitlocker_read_is_never_a_verdict_of_unprotected(
        unelevated, count_wmi):
    """THE bug: 'Requires administrator' does not contain 'Protected', so
    read_value answered False -- a claim that the disk is not encrypted."""
    result = security_reader.check_bitlocker()
    assert result["available"] is False, (
        "a reading nobody was allowed to take must say so, or read() falls "
        "through to read_value and invents an answer")
    assert result["status"] == NEEDS_ADMIN

    control = load_catalog()["bitlocker_system_drive"]
    assert control.read() is None, "a refusal was reported as a value"


def test_the_refusal_reaches_the_card_as_a_reason(unelevated, count_wmi):
    security_reader.check_bitlocker()
    control = load_catalog()["bitlocker_system_drive"]
    result = control.reader()
    assert NEEDS_ADMIN in str(result["status"])
    assert result["color"] == "amber", "an unknown is not a red verdict"


# --- the cost half ----------------------------------------------------------

def test_an_unelevated_bitlocker_read_never_dials_the_namespace(
        unelevated, count_wmi):
    """5.02s, measured, to be told no by MicrosoftVolumeEncryption."""
    security_reader.check_bitlocker()
    assert count_wmi == [], f"it paid to be refused: dialled {count_wmi}"


def test_an_unelevated_tpm_read_never_dials_the_namespace(
        unelevated, count_wmi, count_powershell):
    """5.24s, measured, and secure_boot's own registry half still runs."""
    security_reader.check_secure_boot_tpm()
    assert count_wmi == [], f"it paid to be refused: dialled {count_wmi}"
    assert any("SecureBoot" in cmd for cmd in count_powershell), (
        "the Secure Boot half reads fine unelevated and must still be asked")


def test_an_unelevated_encryption_detail_read_never_runs_the_cmdlet(
        unelevated, count_powershell):
    """5.41s, measured. Get-BitLockerVolume exits 0 while refusing, so the
    cost buys nothing at all."""
    result = security_reader.check_bitlocker_encryption()
    assert not any("BitLockerVolume" in cmd for cmd in count_powershell), (
        f"it paid to be refused: ran {count_powershell}")
    assert result["available"] is False
    assert NEEDS_ADMIN in str(result["status"])


# --- and none of this may cost the elevated run its answer ------------------

def test_an_elevated_run_still_asks_wmi(elevated, count_wmi):
    """The skip is about a refusal that is certain, not about not looking.

    check_bitlocker catches everything the connect can throw, so the fake's
    own error never escapes -- what proves it looked is the dial itself.
    """
    security_reader.check_bitlocker()
    assert count_wmi == [r"root\cimv2\Security\MicrosoftVolumeEncryption"]


def test_an_elevated_encryption_detail_run_still_runs_the_cmdlet(
        elevated, count_powershell):
    security_reader.check_bitlocker_encryption()
    assert any("BitLockerVolume" in cmd for cmd in count_powershell)


def test_a_namespace_that_ordinary_users_can_read_is_not_skipped(
        unelevated, count_wmi):
    """Only the two namespaces measured at a fixed ~5s denial are pre-empted.
    Defender's namespace answers unelevated, so it must still be dialled."""
    with pytest.raises(AssertionError):
        security_reader._wmi_namespace(r"root\Microsoft\Windows\Defender")
    assert count_wmi == [r"root\Microsoft\Windows\Defender"]
