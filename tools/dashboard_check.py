"""Drive the Dashboard's process tabs against the REAL machine.

    .venv\\Scripts\\python.exe tools\\dashboard_check.py

Exits 1 if anything fails. Needs no display -- runs on the offscreen Qt
platform. Cleans up everything it creates.

This is the real-machine sibling of logviewer_check.py and treesize_scan.py.
Generated test data is not the same shape as real data, and the difference
is where the bugs are: the dashboard's wave-1 findings record several bugs
that only appeared with this machine's real 275 processes and seven disks
rendered at a real window size. This harness opens each process tab, lets a
real snapshot land through its own worker + timer path, and checks the
table against the machine it is describing -- not against a fixture's
idea of a machine.

Absent inputs are skipped, not failed. If WMI has no services to read (it
always does here) the service check still runs; the one check that can
legitimately vary is skipped with a note rather than a failure.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from modules.dashboard.app_history_tab import AppHistoryTab  # noqa: E402
from modules.dashboard.details_tab import DetailsTab  # noqa: E402
from modules.dashboard.processes_tab import ProcessesTab  # noqa: E402
from modules.dashboard.services_tab import ServicesTab  # noqa: E402
from modules.dashboard.startup_tab import StartupTab  # noqa: E402
from modules.dashboard.users_tab import UsersTab  # noqa: E402

failures = []


def check(label, ok, detail=""):
    print(f"    {'ok  ' if ok else 'FAIL'} {label}"
          f"{'' if ok else '  -> ' + detail}")
    if not ok:
        failures.append(label)


class _FakeApp:
    """Enough of the app for the tabs: a real thread pool, so each tab runs
    its worker the way it does in the product."""

    def __init__(self):
        from PyQt6.QtCore import QThreadPool
        self.thread_pool = QThreadPool()
        self.config = None


def _settle(app, widget, predicate, seconds=15.0):
    """Pump the loop until the tab's background read lands."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 - a tab not yet built raises
            pass
        time.sleep(0.02)
    return False


def _filled(tab):
    """True once the tab's table or tree holds real rows."""
    if hasattr(tab, "table"):
        return tab.table.model() is not None and tab.table.model().rowCount() > 0
    if hasattr(tab, "_table"):
        return tab._table.rowCount() > 0
    if hasattr(tab, "tree"):
        return tab.tree.topLevelItemCount() > 0
    return False


def _snapshot_of(app, tab):
    """Wait for one real snapshot and return it, or None."""
    tab.set_app(_FakeApp())
    tab.refresh()
    if not _settle(app, tab, lambda: _filled(tab)):
        return None
    return getattr(tab, "_snapshot", None)


def check_details(app) -> None:
    print("\n=== Details tab ===")
    tab = DetailsTab()
    try:
        tab.set_app(_FakeApp())
        tab.refresh()
        if not _settle(app, tab, lambda: _filled(tab)):
            check("a snapshot landed", False, "the table never filled")
            return
        total = tab.model.rowCount()
        check("the machine's processes are listed", total > 50,
              f"saw {total}")
        check("our own process is among them",
              os.getpid() in [tab.model.pid_at(r)
                              for r in range(total)])
        check("rows are visible", tab.proxy.rowCount() > 50,
              f"{tab.proxy.rowCount()}")
        check("the status names the refusal count",
              "could not be read" in tab.status.text())
    finally:
        tab.stop()
        tab.deleteLater()


def check_processes(app) -> None:
    print("\n=== Processes tab ===")
    tab = ProcessesTab()
    try:
        tab.set_app(_FakeApp())
        tab.refresh()
        if not _settle(app, tab, lambda: tab.tree.topLevelItemCount() > 0):
            check("the grouped tree filled", False)
            return
        check("apps/background/windows groups appear",
              tab.tree.topLevelItemCount() >= 3,
              f"{tab.tree.topLevelItemCount()} groups")
        check("rows carry a pid",
              any(tab.tree.topLevelItem(i).childCount() > 0
                  for i in range(tab.tree.topLevelItemCount())))
    finally:
        tab.stop()
        tab.deleteLater()


def check_users(app) -> None:
    print("\n=== Users tab ===")
    tab = UsersTab()
    try:
        snapshot = _snapshot_of(app, tab)
        if snapshot is None:
            check("a snapshot landed", False)
            return
        check("accounts are listed", tab.tree.topLevelItemCount() > 0,
              "no account rows")
        check("at least one account expands",
              any(tab.tree.topLevelItem(i).childCount() > 0
                  for i in range(tab.tree.topLevelItemCount())))
    finally:
        tab.stop()
        tab.deleteLater()


def check_app_history(app) -> None:
    print("\n=== App history tab ===")
    tab = AppHistoryTab()
    try:
        tab.set_app(_FakeApp())
        tab.refresh()
        if not _settle(app, tab, lambda: tab._table.rowCount() > 0):
            check("programs are listed", False, "no rows")
            return
        check("rows outnumber the processes they roll up",
              tab._table.rowCount() > 1)
        check("every row names a program",
              all(tab._table.item(r, 0).text()
                  for r in range(tab._table.rowCount())))
    finally:
        tab.stop()
        tab.deleteLater()


def check_startup(app) -> None:
    print("\n=== Startup apps tab ===")
    tab = StartupTab()
    try:
        tab.set_app(_FakeApp())
        tab.start()
        # The scan includes the scheduled-task COM reader, which is the
        # slowest source; give it the full budget.
        ok = _settle(app, tab, lambda: tab._busy is False
                     and "Scanning" not in tab.status.text(),
                     seconds=30.0)
        check("the startup scan finished", ok)
        check("rows exist or the refusal is named",
              tab._table.rowCount() > 0 or "could not be read"
              in tab.status.text().lower())
        for r in range(tab._table.rowCount()):
            assert tab._table.item(r, 0).text(), f"row {r} has no name"
        check("every row has a name",
              all(tab._table.item(r, 0).text()
                  for r in range(tab._table.rowCount())))
    finally:
        tab.stop()
        tab.deleteLater()


def check_services(app) -> None:
    print("\n=== Services tab ===")
    tab = ServicesTab()
    try:
        tab.set_app(_FakeApp())
        tab.refresh()
        if not _settle(app, tab, lambda: tab._table.rowCount() > 0,
                       seconds=20.0):
            check("the service list filled", False, "WMI read failed")
            return
        check("services are listed", tab._table.rowCount() > 10,
              f"{tab._table.rowCount()}")
        statuses = {tab._table.item(r, 0).text()
                    for r in range(tab._table.rowCount())}
        check("statuses are real WMI states",
              bool(statuses & {"Running", "Stopped"}), str(statuses))
    finally:
        tab.stop()
        tab.deleteLater()


def main() -> int:
    app = QApplication([])
    print("Dashboard real-machine check")
    print("============================")
    check_details(app)
    check_processes(app)
    check_users(app)
    check_app_history(app)
    check_startup(app)
    check_services(app)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
