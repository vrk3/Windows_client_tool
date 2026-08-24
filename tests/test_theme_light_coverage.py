"""Every pane must actually follow the light theme.

`ThemeManager.apply_theme()` only calls `QApplication.setStyleSheet()`. An
inline `widget.setStyleSheet("... background: #2d2d2d ...")` beats the
application sheet and is never revisited, so a pane that hardcodes its colours
stays dark forever while the rest of the app turns light. Light theme is not a
hidden setting: there is a "Toggle &Theme" menu item and a Settings combo.

A sweep of all 34 panes measured 13 of them rendering dark under the light
theme, and the split had no middle ground -- dominant background luminance
0.013-0.045 against 1.000 for the panes that behave. This test is that
measurement, kept.

Luminance, not a stylesheet grep, because a grep cannot tell which frames
actually carry text and cannot see a pane at all. It also cannot be fooled by
a colour that is themed correctly but painted by a delegate.

The consequence is worse than an inconsistent colour. A dark card whose label
sets no colour of its own takes `QLabel { color: #1e1e1e }` from `light.qss`:
the Security Dashboard's card titles measured 1.51:1 against their own
background, which is unreadable. Fixing the background fixes the text with it.
"""
import sys

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

QApplication.instance() or QApplication(sys.argv)

from core.module_registry import ModuleRegistry
from main import register_all_modules


class _RegistryOnlyStub:
    def __init__(self):
        self.module_registry = ModuleRegistry()


_stub = _RegistryOnlyStub()
register_all_modules(_stub)
_MODULES = [(type(m), m.name) for m in _stub.module_registry.modules]

#: TreeSize owns its own theme (`modules/treesize/ui/theme.py`) on purpose --
#: the binding spec is to match TreeSize Professional's look, not this app's.
#: It is exempt from the app theme, and that is a decision, not an oversight.
#: Nothing else may join this list without the same kind of reason.
THEME_EXEMPT = {"TreeSize"}

#: light.qss paints #f5f5f5 (0.91) and #ffffff (1.0). Every pane that fails
#: does so at 0.013-0.045, so the threshold sits in an empty band.
MIN_LIGHT_LUMINANCE = 0.5


def _relative_luminance(colour: QColor) -> float:
    def channel(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(x) for x in (colour.red(), colour.green(), colour.blue()))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _dominant_background(widget):
    """The colour covering most of the rendered pane, and its share."""
    from collections import Counter
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(1150, 820)
    widget.show()
    QApplication.instance().processEvents()
    image = widget.grab().toImage()
    step = max(1, min(image.width(), image.height()) // 120)
    counts = Counter()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            counts[image.pixel(x, y)] += 1
    pixel, hits = counts.most_common(1)[0]
    return QColor(pixel), hits / sum(counts.values())


def _dark_os_palette() -> QPalette:
    """A palette standing in for a machine whose OS colour scheme is dark.

    This is the whole point of the test and it must not be left to chance.
    Qt6 adopts the system colour scheme, so the fallback a pane lands on when
    nothing styles it is the OS's, not the app's: on this Windows 11 box
    (dark mode) an unstyled widget came back #1e1e1e under the light theme,
    while the same widget under the offscreen platform -- which has no system
    theme -- came back #efefef and looked fine. CI runs offscreen, so without
    pinning this the test would pass there while the app was visibly broken
    for the user. Forcing the adversarial case makes the result the same
    everywhere.
    """
    palette = QPalette()
    for role, colour in (
        (QPalette.ColorRole.Window, "#1e1e1e"),
        (QPalette.ColorRole.Base, "#2d2d2d"),
        (QPalette.ColorRole.Button, "#1e1e1e"),
        (QPalette.ColorRole.WindowText, "#ffffff"),
        (QPalette.ColorRole.Text, "#ffffff"),
        (QPalette.ColorRole.ButtonText, "#ffffff"),
    ):
        palette.setColor(role, QColor(colour))
    return palette


@pytest.fixture(scope="module")
def light_app():
    """A real App in the LIGHT theme on a machine whose OS theme is DARK.

    Both the stylesheet and the palette are application-wide, so both are put
    back afterwards -- leaving either would silently change every test that
    runs after this module.
    """
    import tempfile
    from app import App

    qapp = QApplication.instance()
    original_palette = qapp.palette()
    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    app.theme.apply_theme("light")
    qapp.setPalette(_dark_os_palette())
    yield app
    qapp.setPalette(original_palette)
    app.theme.apply_theme("dark")
    try:
        app.shutdown()
    except Exception:
        pass
    App.instance = None


def test_the_luminance_helper_agrees_with_known_colours():
    """Guards the maths: white is 1.0, black is 0.0, by definition."""
    assert _relative_luminance(QColor("#ffffff")) == pytest.approx(1.0)
    assert _relative_luminance(QColor("#000000")) == pytest.approx(0.0)


@pytest.mark.parametrize(
    "module_cls,module_name",
    [pytest.param(c, n, id=c.__name__) for c, n in _MODULES],
)
def test_pane_follows_the_light_theme(light_app, module_cls, module_name):
    if module_name in THEME_EXEMPT:
        pytest.skip(f"{module_name} owns its own theme by design")
    module = module_cls()
    module.on_start(light_app)
    widget = module.create_widget()
    colour, share = _dominant_background(widget)
    luminance = _relative_luminance(colour)
    widget.hide()
    try:
        module.on_stop()
    except Exception:
        pass
    assert luminance >= MIN_LIGHT_LUMINANCE, (
        f"{module_name}: dominant background {colour.name()} has luminance "
        f"{luminance:.3f} over {share:.0%} of the pane while the app is in "
        f"the LIGHT theme -- the pane is painting its own dark colours and "
        f"ignoring the application stylesheet"
    )
