"""The Startup apps tab, as a widget.

Runs against the real machine: HKCU\\Run and the Startup folder are read-only
and cheap, while the scheduled-task and service scans take longer. A bare
machine (or a CI host with nothing in Run) can legitimately return no rows,
so these tests assert the tab's structure and hold whatever rows appear to
exact rules -- every row must name itself and carry an Enabled/Disabled
status -- rather than requiring a minimum count.
"""
import time

from PyQt6.QtCore import QThreadPool
from PyQt6.QtWidgets import QLabel, QTableWidget

from modules.dashboard.startup_tab import StartupTab


class _FakeApp:
    """Enough of the app singleton for the tab: a real thread pool, so the
    scan runs on a COMWorker the way it does in the product."""

    def __init__(self):
        self.thread_pool = QThreadPool()


def _settle(qapp, widget, predicate, seconds=8.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _scanned(qapp, view):
    """Start a scan and pump until it lands (or times out gracefully)."""
    view.set_app(_FakeApp())
    view.start()
    _settle(qapp, view, lambda: view._table.rowCount() > 0)


def test_startup_tab_builds_a_table(qapp):
    view = StartupTab()
    _scanned(qapp, view)
    try:
        assert isinstance(view._table, QTableWidget)
        assert view._table.columnCount() == 5
        headers = [view._table.horizontalHeaderItem(c).text()
                   for c in range(view._table.columnCount())]
        assert headers[0] == "Name"
        assert headers[2] == "Status"
        assert headers[3] == "Source"
    finally:
        view.stop()
        view.deleteLater()


def test_every_row_has_a_name_and_a_status(qapp):
    view = StartupTab()
    _scanned(qapp, view)
    try:
        # No row may be a silent blank; a name or a status we cannot read
        # must say so rather than show "".
        for row in range(view._table.rowCount()):
            assert view._table.item(row, 0).text(), f"row {row} has no name"
            status = view._table.item(row, 2).text()
            assert status in ("Enabled", "Disabled"), \
                f"row {row} status is {status!r}"
            source = view._table.item(row, 3).text()
            assert source, f"row {row} has no source"
    finally:
        view.stop()
        view.deleteLater()


def test_the_honesty_note_is_present(qapp):
    """Task Manager's startup-impact grades come from boot traces this tool
    does not read; the tab must say that instead of showing an invented
    High/Medium/Low column."""
    view = StartupTab()
    try:
        text = _note_text(view)
        assert "impact" in text, "the tab must name startup impact"
        assert "boot" in text, "the note must say impact comes from boot traces"
    finally:
        view.deleteLater()


def _note_text(view):
    for child in view.findChildren(QLabel):
        if "impact" in child.text():
            return child.text()
    return ""
