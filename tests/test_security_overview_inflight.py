"""One overview sweep at a time.

`get_refresh_interval()` is 30 seconds and the sweep it launches took 37 --
so `MainWindow`'s auto-refresh QTimer started a second COMWorker before the
first had returned, then a third, for as long as the tab stayed open. Every
one of them was appended to `self._workers` and none was ever removed, so the
list grew for the life of the session and the global QThreadPool carried a
permanent backlog of duplicate WMI and PowerShell work.

Narrowing the sweep to the fourteen cards the pane draws (12.4s) makes the
overlap unlikely on THIS box. It does not make it impossible: a slower
machine, a stalled WMI namespace or a BitLocker volume that takes its time
puts the job back over 30 seconds. The guard is what makes it impossible.
"""
import pytest

from modules.security_dashboard.security_module import SecurityDashboardModule


@pytest.fixture
def module(qapp, monkeypatch):
    """A dashboard whose overview sweep never returns on its own."""
    mod = SecurityDashboardModule()
    mod.on_start(None)
    widget = mod.create_widget()   # held: dropping it deletes the Qt children

    started = []
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.QThreadPool.globalInstance",
        lambda: type("Pool", (), {"start": lambda _s, w: started.append(w)})(),
    )
    monkeypatch.setattr(
        "modules.security_dashboard.security_module.get_overview_status",
        lambda: pytest.fail("the sweep must not run on the test thread"),
    )
    mod._test_widget = widget
    return mod, started


def test_a_second_refresh_does_not_start_a_second_sweep(module):
    mod, started = module

    mod._refresh_overview()
    mod._refresh_overview()
    mod._refresh_overview()

    assert len(started) == 1, (
        f"{len(started)} overlapping sweeps; the timer fires every 30s"
    )


def test_the_next_refresh_runs_once_the_first_has_finished(module):
    mod, started = module

    mod._refresh_overview()
    started[0].signals.finished.emit()
    mod._refresh_overview()

    assert len(started) == 2, "the guard latched and refresh never resumed"


def test_finished_sweeps_do_not_accumulate_in_the_worker_list(module):
    mod, started = module

    for _ in range(5):
        mod._refresh_overview()
        started[-1].signals.finished.emit()

    assert len(started) == 5
    assert len(mod._workers) <= 1, (
        f"{len(mod._workers)} workers retained after five completed sweeps"
    )
