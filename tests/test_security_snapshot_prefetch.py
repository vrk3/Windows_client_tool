r"""The expensive snapshot should not be on any tab's critical path.

Measured ELEVATED on this machine, which is how the app is run:

    Firewall & Network   9.47s   <- telnet_client alone 8.10s
    Windows Features     0.03s

Both tabs read `snapshots.optional_features()`, and building it means
`Get-WindowsOptionalFeature -Online` -- a DISM enumeration of every feature on
the box, ~8s. Whichever control asks first pays for it and every later one is
free, so the cost lands on whoever happens to be first. Making `smbv1` read
the SMB server config instead (0.46s, down from 7.9s) did not fix the tab: it
just moved the bill to `telnet_client`, which is on the same tab and needs the
real list.

So the list is built once, deliberately, when the user opens the module --
off the tab reads, in the background. `snapshots._cached` already holds a
per-name lock, so a tab that asks while the prefetch is running waits for that
same build rather than starting a second one.

Unelevated the enumeration is refused in 0.12s, so prefetching costs nothing
there; it is not started at app launch, only when somebody actually opens the
Security Dashboard.
"""
import pytest

from modules.security_dashboard import snapshots
from modules.security_dashboard.security_module import SecurityDashboardModule


@pytest.fixture(autouse=True)
def clear_snapshot_cache():
    snapshots._cache.clear()
    yield
    snapshots._cache.clear()


@pytest.fixture
def module():
    mod = SecurityDashboardModule()
    mod.on_start(None)
    return mod


def test_the_prefetch_builds_the_expensive_snapshot(module, monkeypatch):
    built = []
    monkeypatch.setattr(snapshots, "optional_features",
                        lambda: built.append(1) or {})

    submitted = []
    module._start_snapshot_prefetch(run=submitted.append)

    assert len(submitted) == 1, "nothing was scheduled"
    submitted[0]()                       # what the background thread runs
    assert built == [1], "the prefetch did not build optional_features"


def test_it_is_scheduled_once_however_often_the_module_is_opened(module):
    submitted = []
    module._start_snapshot_prefetch(run=submitted.append)
    module._start_snapshot_prefetch(run=submitted.append)
    module._start_snapshot_prefetch(run=submitted.append)

    assert len(submitted) == 1, (
        f"an 8s DISM enumeration was scheduled {len(submitted)} times")


def test_opening_the_module_starts_it(module, monkeypatch):
    started = []
    monkeypatch.setattr(module, "_start_snapshot_prefetch",
                        lambda **kw: started.append(1))
    monkeypatch.setattr(module, "_refresh_overview", lambda: None)
    monkeypatch.setattr(module, "_load_events", lambda: None)

    module.on_activate()

    assert started == [1], "opening the pane did not warm the snapshot"


def test_a_prefetch_that_fails_never_reaches_the_user(module, monkeypatch):
    """It is an optimisation. If DISM refuses or explodes, the tab that
    actually needs the list reports that in its own reading, as it always
    did -- the prefetch must not raise into a background thread."""
    def explode():
        raise RuntimeError("DISM said no")

    monkeypatch.setattr(snapshots, "optional_features", explode)

    submitted = []
    module._start_snapshot_prefetch(run=submitted.append)
    submitted[0]()          # must not raise
