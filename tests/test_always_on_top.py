"""Wave 5 window polish: the Always-on-top toggle (W5-02).

Task Manager's "Always on top" kept the window above everything else; this
app's version is a persisted View-menu toggle. The genuinely new piece of
W5-02 -- the update-speed and minimise-on-use items already exist as the
Overview refresh slider, the global Pause/Resume toolbar action, and the
hide-pauses-refresh behaviour -- so this file pins the one thing that did
not.
"""
import tempfile

import pytest
from PyQt6.QtCore import Qt


@pytest.fixture
def window(qapp, monkeypatch):
    import ui.main_window as mw
    from app import App

    monkeypatch.setattr(mw, "is_admin", lambda: True)
    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    win = mw.MainWindow(app)
    win.resize(1400, 900)
    yield win
    win.close()
    try:
        app.shutdown()
    except Exception:  # noqa: BLE001 - teardown
        pass


def test_always_on_top_defaults_off(window):
    assert window._always_on_top is False
    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint


def test_the_view_menu_offers_the_toggle(window):
    labels = []
    for action in window.menuBar().actions():
        if action.text() == "&View":
            view_menu = action.menu()
            for entry in view_menu.actions():
                labels.append(entry.text())
    assert any("Always on" in label and "top" in label
               for label in labels)


def test_toggling_on_sets_the_flag_and_persists_it(window):
    window._toggle_always_on_top(True)
    assert window._always_on_top is True
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window._app.config.get("app.always_on_top") is True


def test_toggling_off_clears_the_flag(window):
    window._toggle_always_on_top(True)
    window._toggle_always_on_top(False)
    assert window._always_on_top is False
    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window._app.config.get("app.always_on_top") is False


def test_a_persisted_setting_is_applied_at_startup(qapp, monkeypatch):
    """If the user left it on, the NEXT launch comes up on top -- the flag
    must be applied at construction, not only when toggled."""
    import ui.main_window as mw
    from app import App

    monkeypatch.setattr(mw, "is_admin", lambda: True)
    data_dir = tempfile.mkdtemp()
    App.instance = None
    first = App(app_data_dir=data_dir)
    first.config.set("app.always_on_top", True)
    first.shutdown()

    App.instance = None
    app = App(app_data_dir=data_dir)
    win = mw.MainWindow(app)
    try:
        assert win._always_on_top is True
        assert win.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    finally:
        win.close()
        try:
            app.shutdown()
        except Exception:  # noqa: BLE001
            pass
