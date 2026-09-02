"""Hiding to the tray must not be a one-way door for auto-refresh.

`closeEvent` stopped and CLEARED `_module_refresh_timers` before it checked
`app.minimize_to_tray`. With that setting on it then called `event.ignore()`
and hid the window — but the dict was already empty, so `showEvent`'s resume
loop had nothing to restart. Every live pane went quiet for the rest of the
session, and the only way back was selecting a different module.

Nothing logged, nothing shown: the Dashboard simply stopped updating and
looked like a very idle machine.
"""
import tempfile

import pytest
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QLabel, QWidget

from core.base_module import BaseModule


class _RefreshingModule(BaseModule):
    """A module that wants a refresh timer, so the window creates one."""

    name = "Ticker"
    icon = ""
    description = "test double"
    group = "TOOLS"

    def __init__(self) -> None:
        super().__init__()
        self.refreshes = 0

    def create_widget(self) -> QWidget:
        return QLabel("ticker")

    def get_refresh_interval(self):
        return 60_000

    def refresh_data(self) -> None:
        self.refreshes += 1


@pytest.fixture
def window(qapp, monkeypatch):
    import ui.main_window as mw
    from app import App

    monkeypatch.setattr(mw, "is_admin", lambda: True)
    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    win = mw.MainWindow(app)
    win.resize(1400, 900)

    module = _RefreshingModule()
    module.on_start(app)
    win.register_module(module)
    # Selecting it is what starts the timer, exactly as the sidebar does.
    win._on_module_selected("Ticker")

    yield win

    try:
        app.shutdown()
    except Exception:  # noqa: BLE001 - teardown
        pass


def test_the_fixture_actually_has_a_running_timer(window):
    """If this ever stops holding, the two tests below prove nothing."""
    assert "Ticker" in window._module_refresh_timers
    assert window._module_refresh_timers["Ticker"].isActive()


def test_hiding_to_the_tray_keeps_the_refresh_timers(window):
    window._app.config.set("app.minimize_to_tray", True)

    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted(), "closing to the tray must not accept the close"
    assert "Ticker" in window._module_refresh_timers, (
        "the timer must survive so showEvent can resume it")


def test_restoring_from_the_tray_resumes_refreshing(window):
    """The whole point: after a hide/show round trip the pane still ticks."""
    window._app.config.set("app.minimize_to_tray", True)
    window.closeEvent(QCloseEvent())
    window.hideEvent(None)
    window.showEvent(None)

    timer = window._module_refresh_timers.get("Ticker")
    assert timer is not None and timer.isActive()


def test_a_real_close_still_stops_the_timers(window):
    window._app.config.set("app.minimize_to_tray", False)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert window._module_refresh_timers == {}
