r"""Some services refuse an Administrator, and saying so is not optional.

From the real 2026-08-29 session, in an instance that was definitely elevated
(it started Services, Firewall Rules, System Restore and Disk Health, every
one of them admin-gated):

    Step failed (service DoSvc): (5, 'ChangeServiceConfig', 'Access is denied.')

and DoSvc's start type is still 2 (Automatic), so "Disable Delivery
Optimization" did not take. That reads as a bug in this app. It is not.

`tools/service_config_probe.py` asked Windows the permission question directly
-- ChangeServiceConfig with SERVICE_NO_CHANGE for every field, which alters
nothing -- across the ten services the tweaks touch:

    elevated:   DoSvc REFUSED; RemoteRegistry, DiagTrack, SysMain, WSearch,
                MapsBroker, RetailDemo, WMPNetworkSvc, lfsvc all ALLOWED
    unelevated: every one of them refused at OpenService, a step earlier

So DoSvc is refused on its own, by an elevated administrator, while nine
siblings accept the identical call -- and `sc sdshow DoSvc` grants Builtin
Administrators DC (SERVICE_CHANGE_CONFIG), so the DACL is not what is
stopping it. Windows protects that service beyond its ACL.

The registry path already turns this exact class of refusal into a sentence
that explains itself, for TrustedInstaller-locked keys. The service path let a
pywin32 tuple through instead.
"""
import pytest

from modules.tweaks.tweak_engine import TweakEngine


class _Backup:
    def create_restore_point(self, label, module):
        return "rp-1"

    def record_steps(self, *a, **k):
        pass

    def backup_service_state(self, *a, **k):
        pass

    def backup_registry_key(self, *a, **k):
        from core.backup_service import BackupOutcome
        return BackupOutcome(True, False, "", "nothing to export")


@pytest.fixture
def engine():
    return TweakEngine(backup_service=_Backup())


def _denied(*a, **k):
    import pywintypes
    raise pywintypes.error(5, "ChangeServiceConfig", "Access is denied.")


def test_a_service_windows_protects_says_so_in_plain_words(engine, monkeypatch):
    """Measured: DoSvc refuses an elevated admin while nine sibling services
    accept the same call."""
    import win32service

    monkeypatch.setattr(win32service, "OpenSCManager", lambda *a, **k: 1)
    monkeypatch.setattr(win32service, "OpenService", lambda *a, **k: 2)
    monkeypatch.setattr(win32service, "QueryServiceConfig",
                        lambda h: (0, 2, 0, 0, "", "", 0, "", "", "", ""))
    monkeypatch.setattr(win32service, "CloseServiceHandle", lambda h: None)
    monkeypatch.setattr(win32service, "ChangeServiceConfig", _denied)

    errors = []
    tweak = {"id": "t", "name": "Disable Delivery Optimization",
             "requires_admin": True,
             "steps": [{"type": "service", "name": "DoSvc",
                        "start_type": "disabled"}]}
    engine.apply_tweak(tweak, "rp-1", on_error=errors.append)

    assert errors, "the failure was swallowed"
    message = " ".join(errors).lower()
    assert "dosvc" in message
    assert "windows" in message, (
        "it blamed nothing, so the user reads it as our bug")
    assert "administrator" in message
    # The raw tuple is the thing being replaced.
    assert "changeserviceconfig'" not in message


def test_an_ordinary_service_failure_is_not_dressed_up(engine, monkeypatch):
    """Only an access-denied refusal gets the explanation. Anything else must
    keep saying what it actually was."""
    import win32service
    import pywintypes

    def missing(*a, **k):
        raise pywintypes.error(1060, "OpenService",
                               "The specified service does not exist.")

    monkeypatch.setattr(win32service, "OpenSCManager", lambda *a, **k: 1)
    monkeypatch.setattr(win32service, "OpenService", missing)
    monkeypatch.setattr(win32service, "CloseServiceHandle", lambda h: None)

    errors = []
    tweak = {"id": "t", "name": "T", "requires_admin": True,
             "steps": [{"type": "service", "name": "Nope",
                        "start_type": "disabled"}]}
    engine.apply_tweak(tweak, "rp-1", on_error=errors.append)

    assert errors
    message = " ".join(errors).lower()
    # Already handled upstream, and handled well: an absent service is
    # "not applicable", not a failure to explain away.
    assert "not installed" in message
    assert "protect" not in message, "an absent service is not a protected one"
