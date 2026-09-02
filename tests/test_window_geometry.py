"""The window comes back where you left it.

Only `[width, height]` was saved. Maximise the window, quit, reopen — it
returned windowed, at whatever size it happened to have, centred on the
primary display. On a multi-monitor desk that is a per-launch annoyance:
the app you keep on the second screen opens on the first one every time.

Qt has `saveGeometry`/`restoreGeometry` for exactly this. They encode
position, size, maximised/fullscreen state and the screen identity, in one
opaque blob.

The one thing they do NOT do is protect you from a monitor that is no
longer there: restoring geometry from a screen that has been unplugged
leaves the window somewhere you cannot reach, and there is no visible
failure — the app is simply not on screen anywhere.
"""
import tempfile

import pytest
from PyQt6.QtCore import QRect


@pytest.fixture
def window(qapp, monkeypatch):
    import ui.main_window as mw
    from app import App

    monkeypatch.setattr(mw, "is_admin", lambda: True)
    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    win = mw.MainWindow(app)
    yield win
    try:
        app.shutdown()
    except Exception:  # noqa: BLE001 - teardown
        pass


def test_geometry_round_trips_through_config(window):
    # Deliberately smaller than the screen. Qt's restoreGeometry clamps a
    # restored window to the available screen area, which is correct
    # behaviour — a window bigger than the display cannot come back at its
    # saved size, and asserting that it does only tests the test runner's
    # virtual screen (800x800 under QT_QPA_PLATFORM=offscreen).
    window.resize(640, 480)
    window._save_window_geometry()

    stored = window._app.config.get("app.window_geometry")
    assert stored, "nothing was saved"

    window.resize(320, 200)
    window._restore_window_geometry()

    assert window.size().width() == 640
    assert window.size().height() == 480


def test_a_maximised_window_reopens_maximised(window):
    window.showMaximized()
    window._save_window_geometry()

    window.showNormal()
    window._restore_window_geometry()

    assert window.isMaximized()


def test_an_old_config_with_only_a_size_still_works(window):
    """Existing installs have app.window_size and no app.window_geometry;
    they must not open at the default size and lose the user's setup."""
    window._app.config.set("app.window_geometry", None)
    window._app.config.set("app.window_size", [700, 500])

    window._restore_window_geometry()

    assert window.size().width() == 700
    assert window.size().height() == 500


def test_a_corrupt_geometry_blob_falls_back_instead_of_raising(window):
    """It is base64 in a JSON file a human can edit."""
    window._app.config.set("app.window_geometry", "not base64 at all!!")

    window._restore_window_geometry()   # must not raise

    assert window.size().width() > 0


def test_a_window_restored_off_screen_is_brought_back(window, monkeypatch):
    """Geometry saved on a monitor that has since been unplugged puts the
    window somewhere unreachable, with nothing on screen to say so."""
    window.setGeometry(QRect(-9000, -9000, 800, 600))

    window._ensure_on_screen()

    frame = window.frameGeometry()
    assert any(screen.availableGeometry().intersects(frame)
               for screen in window.screen().virtualSiblings()), (
        "the window was left outside every available screen")
