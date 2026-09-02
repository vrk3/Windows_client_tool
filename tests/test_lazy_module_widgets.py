"""A module's widget is built when it is first shown, not at launch.

Building all 33 up front cost 1.78s of a 2.10s startup — measured against
0.17s to import every module package and 0.05s to stand up App. Widget
construction *was* the startup cost, and 32 of the 33 were for panes the
user was not looking at.

CompositeModule already builds its tabs this way; the trap it documents
applies here too, so a module's page is permanent and the real widget is
added into its layout. Never removeWidget/insertWidget on the current page:
that re-enters the handler that asked for the build.
"""
import tempfile

import pytest
from PyQt6.QtWidgets import QLabel, QWidget

from core.base_module import BaseModule


class _CountingModule(BaseModule):
    """Records how many times its widget was built."""

    icon = ""
    description = "test double"
    group = "TOOLS"

    def __init__(self, name: str = "Counter") -> None:
        super().__init__()
        self.name = name
        self.builds = 0
        self.activations = 0

    def create_widget(self) -> QWidget:
        self.builds += 1
        return QLabel(f"{self.name} built")

    def on_activate(self) -> None:
        self.activations += 1


class _ExplodingModule(_CountingModule):
    def create_widget(self) -> QWidget:
        self.builds += 1
        raise RuntimeError("this pane cannot be built")


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


def test_registering_a_module_does_not_build_its_widget(window):
    second = _CountingModule("Second")
    window.register_module(_CountingModule("First"))
    window.register_module(second)

    assert second.builds == 0, "a pane nobody has opened must not be built"


def test_selecting_a_module_builds_it_once(window):
    module = _CountingModule()
    window.register_module(module)

    window._on_module_selected("Counter")
    assert module.builds == 1

    window._on_module_selected("Counter")
    assert module.builds == 1, "a second visit must reuse the widget"


def test_the_widget_is_reachable_after_it_is_built(window):
    """_navigate_to_module and the composite tab routing read
    _module_widgets; a lazily built widget has to land there too."""
    module = _CountingModule()
    window.register_module(module)
    window._on_module_selected("Counter")

    widget = window._module_widgets.get("Counter")
    assert widget is not None
    assert widget.parent() is not None, "it must be inside its page, not orphaned"


def test_the_first_module_is_built_by_the_time_the_window_is_shown(window):
    """The auto-selected first module must exist before the user sees the
    window, or the app opens on an empty pane."""
    module = _CountingModule()
    window.register_module(module)

    window.showEvent(None)

    assert module.builds == 1
    assert module.activations == 1


def test_a_module_that_cannot_be_built_says_so_instead_of_crashing(window):
    """create_widget() runs user-facing code that touches WMI, the registry
    and subprocesses. One pane failing must not take the window with it —
    it used to run during register_module, where nothing caught it."""
    module = _ExplodingModule("Broken")
    window.register_module(module)

    window._on_module_selected("Broken")

    widget = window._module_widgets.get("Broken")
    assert widget is not None
    assert "failed" in widget.text().lower()


def test_a_failed_build_is_not_retried_on_every_visit(window):
    module = _ExplodingModule("Broken")
    window.register_module(module)

    window._on_module_selected("Broken")
    window._on_module_selected("Broken")

    assert module.builds == 1


def test_a_disabled_module_still_shows_its_admin_placeholder(window, monkeypatch):
    module = _CountingModule("NeedsAdmin")
    monkeypatch.setattr(
        type(window._app.module_registry), "disabled_modules",
        property(lambda self: [module]))

    window.register_module(module)
    window._on_module_selected("NeedsAdmin")

    assert module.builds == 0, "a disabled module's widget is never built"
    widget = window._module_widgets.get("NeedsAdmin")
    assert widget is not None and "administrator" in widget.text().lower()
