"""Being told "no" by a WMI namespace costs five seconds. Pay it once.

Measured on this box, unelevated, 2026-08-24 -- three attempts at each of the
two namespaces the dashboard needs:

    MicrosoftVolumeEncryption  connect#1..3   5.02s  5.01s  5.00s  all DENIED
    MicrosoftTpm               connect#1..3   5.01s  5.01s  5.02s  all DENIED

It is not a connect cost. Every one of those six attempts FAILED, with
`wmi.x_access_denied`, after a fixed ~5s. The Overview dialled both on every
refresh, so ten of its 12.4 seconds went on being refused twice -- and the
auto-refresh timer did it again every 30 seconds for as long as the tab was
open.

A process cannot gain elevation while it runs, so one refusal settles the
question for the session.
"""
import pytest

from modules.security_dashboard import security_reader
from modules.security_dashboard.security_reader import NEEDS_ADMIN


@pytest.fixture(autouse=True)
def clear_cache():
    security_reader._denied_namespaces.clear()
    yield
    security_reader._denied_namespaces.clear()


@pytest.fixture(autouse=True)
def elevated(monkeypatch):
    """These tests are about what happens once a namespace IS dialled.

    Unelevated, the two security namespaces are no longer dialled at all --
    the refusal is certain in advance and cost 5s to confirm (see
    test_security_unelevated_reads.py). The caching below still decides what
    happens when an elevated process is refused anyway, and what happens to
    every namespace outside that pair, so it is pinned here with the dial
    reached.
    """
    monkeypatch.setattr(security_reader, "is_admin", lambda: True)


@pytest.fixture
def denying_wmi(monkeypatch):
    """Count how often the namespace is actually dialled."""
    import pywintypes
    import wmi

    attempts = []

    def deny(*args, **kwargs):
        attempts.append(kwargs.get("namespace"))
        raise wmi.x_access_denied(
            "Unexpected COM Error",
            pywintypes.com_error(-2147217405, "OLE error 0x80041003", None, None),
        )

    monkeypatch.setattr(wmi, "WMI", deny)
    return attempts


def test_a_refused_namespace_is_dialled_once_per_process(denying_wmi):
    security_reader.check_bitlocker()
    security_reader.check_bitlocker()
    security_reader.check_bitlocker()

    assert len(denying_wmi) == 1, (
        f"paid the ~5s refusal {len(denying_wmi)} times"
    )


def test_the_cached_refusal_still_reports_requires_administrator(denying_wmi):
    first = security_reader.check_bitlocker()
    second = security_reader.check_bitlocker()

    assert first["status"] == NEEDS_ADMIN
    assert second == first, "the remembered refusal must read the same"


def test_each_namespace_is_remembered_separately(denying_wmi):
    security_reader.check_bitlocker()          # MicrosoftVolumeEncryption
    security_reader.check_secure_boot_tpm()    # MicrosoftTpm
    security_reader.check_bitlocker()
    security_reader.check_secure_boot_tpm()

    assert len(denying_wmi) == 2
    assert len(set(denying_wmi)) == 2


def test_a_namespace_that_answers_is_not_cached_as_denied(monkeypatch):
    """Only a refusal is remembered. A working namespace stays live."""
    import wmi

    calls = []

    class FakeVolume:
        ProtectionStatus, DriveLetter = 1, "C:"

    class FakeConn:
        def Win32_EncryptableVolume(self):
            return [FakeVolume()]

    def connect(*args, **kwargs):
        calls.append(kwargs.get("namespace"))
        return FakeConn()

    monkeypatch.setattr(wmi, "WMI", connect)

    assert security_reader.check_bitlocker()["status"] == "C: Protected"
    assert security_reader.check_bitlocker()["status"] == "C: Protected"
    assert len(calls) == 2, "a namespace that works must not be cached away"


def test_a_failure_that_is_not_a_denial_is_not_remembered(monkeypatch):
    """A transient WMI error must be retried, not latched for the session."""
    import wmi

    calls = []

    def flaky(*args, **kwargs):
        calls.append(kwargs.get("namespace"))
        raise wmi.x_wmi("RPC server is unavailable")

    monkeypatch.setattr(wmi, "WMI", flaky)

    security_reader.check_bitlocker()
    security_reader.check_bitlocker()

    assert len(calls) == 2, "a transient failure was latched as permanent"
