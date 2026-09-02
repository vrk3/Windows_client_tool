"""The Dashboard as a host for the process views.

The decision this pins: Process Explorer is a CHILD of the Dashboard, not its
own sidebar entry. Two doors to the same room means two places to kill a
process from and two process engines to keep honest.
"""
import pytest

from modules.dashboard.dashboard_module import DashboardModule, OverviewModule


@pytest.fixture
def module():
    return DashboardModule()


def test_the_dashboard_hosts_the_process_views(module):
    """Processes before Details: the grouped view is the one most people
    want, and the 40-column table is the one you go to next. Users files
    every process under its account. PerfMon was absorbed as its last tab
    -- one place for the live performance picture."""
    assert [child.name for child in module.children] == \
        ["Overview", "Processes", "Performance", "Details", "Users",
         "Process Explorer", "PerfMon"]


def test_the_old_overview_is_still_the_first_tab(module):
    """It is what someone opening a dashboard expects to see first."""
    assert isinstance(module.children[0], OverviewModule)


def test_the_dashboard_is_not_gated_behind_elevation(module):
    """Unelevated it still shows every process and most of the numbers."""
    assert module.requires_admin is False


def test_process_explorer_is_no_longer_registered_on_its_own(qapp):
    """The absorption, checked where it actually matters: the sidebar."""
    import inspect

    from modules.dashboard import dashboard_module
    import main

    source = inspect.getsource(main.register_modules) \
        if hasattr(main, "register_modules") else inspect.getsource(main)
    assert "register(ProcessExplorerModule())" not in source


def test_the_composite_answers_with_a_refresh_interval(module):
    """A composite that does not answer leaves every child it hosts with no
    auto-refresh at all -- which is exactly what happened to six modules the
    first time this pattern was used here."""
    assert module.get_refresh_interval() is not None


def test_the_details_child_drives_its_own_timer(module):
    """So the host does not read the machine a second time per tick."""
    details = module.children[1]
    assert details.get_refresh_interval() is None


def test_every_child_is_in_hidden_imports():
    """They are imported inside __init__, so PyInstaller's static analysis
    can miss them and the frozen build would show the tabs absent."""
    import io

    source = io.open("pyinstaller_common.py", encoding="utf-8").read()
    for name in ("modules.dashboard.details_module",
                 "modules.process_explorer.process_explorer_module",
                 "modules.dashboard.procengine.ntquery",
                 "modules.perfmon.perfmon_module",
                 "modules.dashboard.users_module"):
        assert f'"{name}"' in source, f"{name} is not in HIDDEN_IMPORTS"
