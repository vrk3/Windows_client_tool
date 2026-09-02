"""Tables and chrome say what they are.

There were zero `setAccessibleName` calls in 92,000 lines. A screen reader
announces an unnamed QTableWidget as a grid of cells: the user can read the
values but has no way to know whether they are in the process list, the
firewall rules or the certificate store, and no way to tell the navigation
from the pane it controls.

Named centrally rather than per pane: `core.table_ui.describe_table` builds
the name from the column headers, which every table has and which describe
it accurately, and `fit_table`/`fit_last` call it — so all 51 call sites got
it without each having to invent a name.
"""
import tempfile

import pytest
from PyQt6.QtWidgets import QTableWidget

from core.table_ui import describe_table, fit_last, fit_table


def _table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    return table


def test_a_table_is_named_after_its_columns(qapp):
    table = _table(["Name", "PID", "User name", "CPU"])
    describe_table(table)
    assert table.accessibleName() == "table with columns Name, PID, User name, CPU"


def test_an_explicit_name_wins(qapp):
    table = _table(["A", "B"])
    describe_table(table, "Firewall rules")
    assert table.accessibleName() == "Firewall rules"


def test_a_table_with_no_headers_still_gets_a_name(qapp):
    table = QTableWidget(0, 2)
    describe_table(table)
    assert table.accessibleName() == "table"


def test_the_description_says_how_big_it_is(qapp):
    table = _table(["A", "B", "C"])
    table.setRowCount(7)
    describe_table(table)
    assert "7 rows" in table.accessibleDescription()
    assert "3 columns" in table.accessibleDescription()


@pytest.mark.parametrize("helper", [fit_table, fit_last])
def test_the_shared_layout_helpers_name_the_table(qapp, helper):
    """The point of doing it here: 51 call sites, one change."""
    table = _table(["Rule", "Action"])
    helper(table)
    assert table.accessibleName()


def test_the_main_window_chrome_is_named(qapp, monkeypatch):
    import ui.main_window as mw
    from app import App

    monkeypatch.setattr(mw, "is_admin", lambda: True)
    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    window = mw.MainWindow(app)
    try:
        assert window._sidebar.accessibleName() == "Module navigation"
        assert window._sidebar.accessibleDescription()
        assert window._stack.accessibleName() == "Current module"
        assert window._search_bar.accessibleName()
        assert window._search_results.accessibleName()
        assert window._filter_panel.accessibleName()
    finally:
        try:
            app.shutdown()
        except Exception:  # noqa: BLE001 - teardown
            pass


def test_the_app_has_more_than_a_handful_of_shortcuts():
    """A correction to the audit, kept as a test so the claim stays true.

    Audit #29 said "three keyboard shortcuts in 92,078 lines". That counted
    only `setShortcut(...)`; the app mostly uses the `QShortcut(...)`
    constructor form, and there are 18 bindings in total — F5, Ctrl+F,
    Ctrl+Shift+F, Ctrl+P, Ctrl+W, Ctrl+C, F6, Escape and the menu
    accelerators. The accessibility half of that finding was real; the
    shortcut half was a miscount.
    """
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parent.parent / "src"
    bindings = 0
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        bindings += len(re.findall(r"QShortcut\(", text))
        bindings += len(re.findall(r"\.setShortcut\(", text))
    assert bindings >= 15, f"only {bindings} shortcut bindings found"
