"""Task Manager's Memory panel.

The trap pinned here: `GetPerformanceInfo` returns everything in PAGES, not
bytes. Reporting them raw understates memory by 4096x, and the numbers still
look plausible -- 8 GB of commit reads as 2 MB rather than as an obvious
error, which is exactly the kind of wrong that ships.
"""
import pytest

from modules.dashboard.procengine.meminfo import (
    memory_modules, memory_status,
)


@pytest.fixture(scope="module")
def status():
    return memory_status()


# ---- the units ----------------------------------------------------------

def test_the_totals_are_in_bytes_not_pages(status):
    """A machine with 4 GB or more of RAM. In pages this would be a number
    around a million, not billions."""
    assert status.total > 4 * 1024**3, \
        f"total is {status.total}, which looks like pages rather than bytes"


def test_the_commit_limit_is_in_bytes_too(status):
    assert status.commit_limit > 4 * 1024**3


def test_the_pools_are_in_bytes(status):
    """Kernel pools are small, so a page/byte mix-up hides best here."""
    assert status.kernel_nonpaged > 1024 * 1024


# ---- the figures make sense ---------------------------------------------

def test_available_memory_is_not_more_than_total(status):
    assert 0 < status.available <= status.total


def test_memory_in_use_is_the_difference(status):
    assert status.in_use == status.total - status.available


def test_the_used_percentage_is_a_percentage(status):
    assert 0.0 < status.used_percent < 100.0


def test_committed_memory_is_within_its_limit(status):
    assert 0 < status.committed <= status.commit_limit


def test_the_commit_peak_is_at_least_the_current_commit(status):
    assert status.commit_peak >= status.committed


def test_the_kernel_pools_are_reported_separately(status):
    """Paged and non-paged are different things and Task Manager shows both;
    folding them together loses the one that matters when a driver leaks."""
    assert status.kernel_paged > 0
    assert status.kernel_nonpaged > 0


def test_the_cache_is_reported(status):
    assert status.cached > 0


# ---- hardware reserved --------------------------------------------------

def test_installed_memory_is_at_least_what_the_os_can_see(status):
    """Firmware always keeps some back."""
    if status.installed is None:
        pytest.skip("installed memory could not be read on this machine")
    assert status.installed >= status.total


def test_hardware_reserved_is_the_gap(status):
    if status.installed is None:
        pytest.skip("installed memory could not be read")
    assert status.hardware_reserved == status.installed - status.total


def test_hardware_reserved_is_never_negative(status):
    """The two figures come from different sources and can disagree."""
    if status.hardware_reserved is not None:
        assert status.hardware_reserved >= 0


def test_unreadable_installed_memory_is_none_rather_than_zero(status):
    """Zero would claim there is no reserved memory, which is a different
    statement from "we could not tell"."""
    if status.installed is None:
        assert status.hardware_reserved is None


# ---- the counts that ride along -----------------------------------------

def test_the_process_count_is_plausible(status):
    assert 20 < status.processes < 10_000


def test_the_thread_and_handle_counts_are_plausible(status):
    """These feed the CPU panel, which shows all three."""
    assert status.threads > status.processes
    assert status.handles > status.threads


def test_the_counts_agree_with_the_process_engine(status):
    """Two different APIs describing one machine. A large disagreement
    means one of them is being read wrong."""
    from modules.dashboard.procengine.ntquery import system_processes

    counted = len(system_processes())
    assert abs(counted - status.processes) < 25


# ---- the physical sticks ------------------------------------------------

def test_the_memory_modules_are_listed():
    modules = memory_modules()
    if not modules:
        pytest.skip("WMI did not return the physical memory list")
    assert all(module.capacity for module in modules)


def test_the_module_capacities_add_up_to_the_installed_total(status):
    modules = memory_modules()
    if not modules or status.installed is None:
        pytest.skip("no module list or no installed figure")
    total = sum(module.capacity or 0 for module in modules)
    # Within a percent: the two come from different firmware tables.
    assert abs(total - status.installed) < status.installed * 0.01


def test_each_module_names_its_slot_and_form_factor():
    modules = memory_modules()
    if not modules:
        pytest.skip("WMI did not return the physical memory list")
    assert all(module.slot for module in modules)
    assert any(module.form_factor for module in modules)


def test_a_module_speed_is_plausible():
    modules = memory_modules()
    if not modules:
        pytest.skip("WMI did not return the physical memory list")
    speeds = [module.speed_mhz for module in modules if module.speed_mhz]
    assert speeds
    assert all(400 < speed < 20_000 for speed in speeds)


def test_nothing_in_a_module_is_an_empty_string():
    for module in memory_modules():
        for field in ("slot", "form_factor", "manufacturer"):
            assert getattr(module, field) != ""


# ---- Qt-free ------------------------------------------------------------

def test_the_engine_does_not_import_qt():
    import inspect

    from modules.dashboard.procengine import meminfo

    assert "PyQt6" not in inspect.getsource(meminfo)
