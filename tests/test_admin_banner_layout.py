"""The unelevated admin banner took half the window.

`_create_admin_banner()` returns a plain QWidget, whose size policy is
Preferred/Preferred -- growable. The splitter below it is a *horizontal*
QSplitter, and Qt gives a splitter the Expanding flag only along its own
orientation, so its VERTICAL policy is Preferred too. Neither item in the
root QVBoxLayout carried a stretch factor.

With no item claiming the vertical space and none of them Expanding, Qt
splits the surplus equally between the two growable items. The banner's
size hint is 28px; on a 900px window it was drawn 450px tall, with its one
line of text floating in the middle of an olive slab, and the whole
application squeezed into the bottom half.

It only shows up unelevated -- elevated there is no banner at all -- and it
disappears the moment the search-results table (Expanding/Expanding) becomes
visible, which is why it survived this long.

The fix is to say which widget owns the leftover space, rather than to pin
the banner's height: the same trap is waiting for anything else added to
this layout. `FilterPanel` is inserted into it too.
"""
import tempfile

import pytest
from PyQt6.QtWidgets import QLabel, QSplitter

_BANNER_TEXT = "Some features require administrator privileges."


@pytest.fixture
def window(qapp, monkeypatch):
    """A MainWindow that believes it is running unelevated."""
    import ui.main_window as mw
    from app import App

    monkeypatch.setattr(mw, "is_admin", lambda: False)

    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    win = mw.MainWindow(app)
    win.resize(1400, 900)
    win.centralWidget().layout().activate()
    yield win
    win.close()
    try:
        app.shutdown()
    except Exception:
        pass


def _banner(win):
    for label in win.centralWidget().findChildren(QLabel):
        if label.text() == _BANNER_TEXT:
            return label.parentWidget()
    raise AssertionError("no admin banner in an unelevated window")


def test_banner_does_not_take_the_window(window):
    """One line of text and a button is worth its size hint, not half a screen."""
    banner = _banner(window)
    hint = banner.sizeHint().height()
    assert banner.height() <= hint + 4, (
        "admin banner is %dpx tall against a %dpx size hint"
        % (banner.height(), hint)
    )


def test_the_splitter_gets_the_space(window):
    """Whatever the banner does not take belongs to the content area."""
    banner = _banner(window)
    splitter = window.centralWidget().findChild(QSplitter)
    central_height = window.centralWidget().height()
    assert splitter.height() > central_height - banner.height() - 8, (
        "splitter got %dpx of a %dpx central widget"
        % (splitter.height(), central_height)
    )
