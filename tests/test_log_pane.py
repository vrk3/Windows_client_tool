"""The one log-reading pane behind every diagnostic tab.

Diagnose built this widget inline and the six standalone modules each built a
thinner version of their own. This is the Diagnose one, extracted, so the
error path and the empty state are testable for the first time.
"""
from datetime import datetime

from core.types import LogEntry
from ui.log_pane import LogPane


def _entry(message="hello"):
    return LogEntry(
        timestamp=datetime(2026, 8, 21, 12, 0, 0),
        source="test",
        level="Information",
        message=message,
    )


def test_it_starts_on_the_empty_page(qapp):
    pane = LogPane(loader=lambda worker: [])
    assert pane.is_showing_empty_state() is True


def test_set_entries_fills_the_table_and_leaves_the_empty_page(qapp):
    pane = LogPane(loader=lambda worker: [])

    pane.set_entries([_entry("first"), _entry("second")])

    assert pane.is_showing_empty_state() is False
    assert pane.row_count() == 2


def test_an_error_shows_the_banner_and_keeps_the_pane_usable(qapp):
    pane = LogPane(loader=lambda worker: [])

    pane.show_error("C:\\Windows\\Logs\\CBS\\CBS.log not found")

    assert pane.is_showing_error() is True
    assert "CBS.log" in pane.error_text()
    assert pane.row_count() == 0


def test_a_later_load_clears_an_earlier_error(qapp):
    pane = LogPane(loader=lambda worker: [])
    pane.show_error("gone missing")

    pane.set_entries([_entry()])
    pane.clear_error()

    assert pane.is_showing_error() is False


def test_extra_controls_land_in_the_toolbar(qapp):
    from PyQt6.QtWidgets import QComboBox

    seen = {}

    def add_controls(toolbar, extra):
        combo = QComboBox()
        combo.addItems(["24", "48"])
        toolbar.addWidget(combo)
        extra["hours"] = combo
        seen["called"] = True

    pane = LogPane(loader=lambda worker: [], extra_controls=add_controls)

    assert seen["called"] is True
    assert pane.extra["hours"].count() == 2
