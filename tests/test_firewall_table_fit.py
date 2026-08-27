"""The firewall table has to fit its own data and let the user resize it.

Every one of these guards a defect that was live in the pane: the columns
were ``Fixed``, so a value that did not fit could not be widened by anyone;
the narrowest column in the table (Profile) was the stretch section, so it
soaked up the leftover width while Name and Program starved; a program path
elided on the right rendered as the useless ``C:...``; and there was no way
at all to change the text size.

Widths are asserted against real netsh-shaped values, because a table built
from three-character fixtures fits anything.
"""
import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QHeaderView

from modules.firewall_rules.firewall_manager_module import (
    FirewallManagerModule, FirewallRule, _MAX_FONT_PT, _MIN_FONT_PT,
)

# Shapes taken from a real 544-rule dump of a Windows 11 machine.
REAL_RULES = [
    FirewallRule(
        name="Wireless Display Infrastructure Back Channel (TCP-In)",
        enabled="Yes", direction="In", action="Allow", protocol="TCP",
        local_port="7250", remote_port="Any",
        program=r"C:\WINDOWS\system32\CastSrv.exe",
        profile="Domain,Private,Public",
    ),
    FirewallRule(
        name="Microsoft Office Hub", enabled="No", direction="Out",
        action="Block", protocol="TCP", local_port="Any", remote_port="Any",
        program=(r"C:\Program Files\WindowsApps\Microsoft.MicrosoftOfficeHub"
                 r"_19.2506.1421.0_x64__8wekyb3d8bbwe\LocalBridge.exe"),
        profile="Domain,Private,Public",
    ),
]


@pytest.fixture
def pane(qapp):
    module = FirewallManagerModule()
    module.on_start(None)
    module.create_widget()
    module._on_rules_loaded(list(REAL_RULES))
    return module


def _needed(pane, row, col):
    """Pixels the value in this cell wants, padding included."""
    text = pane._table.item(row, col).text()
    return pane._table.fontMetrics().horizontalAdvance(text) + 12


# ------------------------------------------------------------------
# Fitting
# ------------------------------------------------------------------

def test_every_column_is_user_resizable(pane):
    """Fixed sections refuse the drag silently -- there is no error, the
    column simply never moves."""
    header = pane._table.horizontalHeader()
    modes = {header.sectionResizeMode(i)
             for i in range(pane._table.columnCount())}
    assert modes == {QHeaderView.ResizeMode.Interactive}

    header.resizeSection(0, 700)
    assert pane._table.columnWidth(0) == 700


def test_profile_is_not_the_stretch_section(pane):
    """Profile holds the shortest text in the table; stretching it wasted
    hundreds of pixels the Name and Program columns needed."""
    assert pane._table.horizontalHeader().stretchLastSection() is False


def test_short_columns_fit_their_widest_real_value(pane):
    """Enabled/Direction/Action/Protocol/Profile have a bounded vocabulary --
    if these ever clip, the defaults are simply wrong."""
    for col in (1, 2, 3, 4, 8):
        for row in range(pane._table.rowCount()):
            assert _needed(pane, row, col) <= pane._table.columnWidth(col), (
                "column %r clips %r"
                % (pane._table.horizontalHeaderItem(col).text(),
                   pane._table.item(row, col).text()))


def test_program_column_holds_an_ordinary_system32_path(pane):
    assert _needed(pane, 0, 7) <= pane._table.columnWidth(7)


def test_paths_elide_in_the_middle(pane):
    """ElideRight turns every path into 'C:...'; ElideMiddle keeps the drive
    and the executable name, which is the part that identifies the rule."""
    assert pane._table.textElideMode() == Qt.TextElideMode.ElideMiddle


def test_every_cell_carries_the_full_values_as_a_tooltip(pane):
    """Whatever is elided has to stay reachable."""
    for row in range(pane._table.rowCount()):
        for col in range(pane._table.columnCount()):
            tip = pane._table.item(row, col).toolTip()
            assert REAL_RULES[row].name in tip
            assert REAL_RULES[row].program in tip


def test_fit_columns_caps_a_runaway_path(pane):
    """One 645px WindowsApps path must not push the rest off-screen."""
    from modules.firewall_rules.firewall_manager_module import _FIT_MAX_WIDTH
    pane._fit_columns()
    for col in range(pane._table.columnCount()):
        assert pane._table.columnWidth(col) <= _FIT_MAX_WIDTH


# ------------------------------------------------------------------
# Text size
# ------------------------------------------------------------------

def test_zoom_moves_font_row_height_and_columns_together(pane):
    """A bigger font in a fixed row clips descenders, and in the old widths
    clips more text rather than less -- all three have to move."""
    before = (pane._font_pt, pane._table.rowHeight(0),
              pane._table.columnWidth(0))
    pane._nudge_font(4)
    after = (pane._font_pt, pane._table.rowHeight(0),
             pane._table.columnWidth(0))
    assert all(a > b for a, b in zip(after, before)), (before, after)


def test_zoom_is_clamped_at_both_ends(pane):
    for _ in range(50):
        pane._nudge_font(1)
    assert pane._font_pt == _MAX_FONT_PT
    for _ in range(50):
        pane._nudge_font(-1)
    assert pane._font_pt == _MIN_FONT_PT


def test_reset_returns_to_the_application_font(pane):
    base = pane._base_font_pt
    pane._nudge_font(5)
    pane._reset_font()
    assert pane._font_pt == base
    assert pane._table.font().pointSize() == base


def _wheel(modifier, dy=120):
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, modifier, Qt.ScrollPhase.NoScrollPhase, False)


def test_ctrl_wheel_zooms_and_is_swallowed(pane):
    """If the event is not consumed the table zooms *and* scrolls away from
    the row the user was pointing at."""
    before = pane._font_pt
    handled = pane._wheel_filter.eventFilter(
        pane._table.viewport(), _wheel(Qt.KeyboardModifier.ControlModifier))
    assert handled is True
    assert pane._font_pt == before + 1


def test_plain_wheel_still_scrolls(pane):
    before = pane._font_pt
    handled = pane._wheel_filter.eventFilter(
        pane._table.viewport(), _wheel(Qt.KeyboardModifier.NoModifier))
    assert handled is False
    assert pane._font_pt == before


def test_font_size_survives_a_restart(qapp):
    """The setting is worthless if the user has to redo it every launch."""
    class FakeConfig:
        def __init__(self):
            self.data = {}

        def get(self, key, default=None):
            return self.data.get(key, default)

        def set(self, key, value):
            self.data[key] = value

    class FakeApp:
        def __init__(self):
            self.config = FakeConfig()

    app = FakeApp()

    first = FirewallManagerModule()
    first.on_start(app)
    first.create_widget()
    first._nudge_font(3)
    chosen = first._font_pt

    second = FirewallManagerModule()
    second.on_start(app)
    second.create_widget()
    assert second._font_pt == chosen


def test_a_junk_saved_size_falls_back_to_the_default(qapp):
    class FakeConfig:
        def get(self, key, default=None):
            return "not a number"

        def set(self, key, value):
            pass

    class FakeApp:
        config = FakeConfig()

    module = FirewallManagerModule()
    module.on_start(FakeApp())
    module.create_widget()
    assert module._font_pt == module._base_font_pt
