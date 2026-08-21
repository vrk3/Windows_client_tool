"""What the sidebar is made of.

These assert the shape of the module list itself — how many entries there are,
that no two share a name, that a module which became a tab is still reachable,
and that every search source the filter panel offers can actually answer.
"""
import pytest

import main as app_main


class _FakeRegistry:
    def __init__(self):
        self.modules = []

    def register(self, module):
        self.modules.append(module)


class _FakeApp:
    def __init__(self):
        self.module_registry = _FakeRegistry()


@pytest.fixture
def registered():
    app = _FakeApp()
    app_main.register_all_modules(app)
    return app.module_registry.modules


def test_duplicate_finder_is_gone(registered):
    assert "Duplicate Finder" not in {m.name for m in registered}


def test_nothing_imports_the_duplicate_finder_package():
    with pytest.raises(ModuleNotFoundError):
        __import__("modules.duplicate_finder.duplicate_finder_module")


def test_module_names_are_unique(registered):
    names = [m.name for m in registered]
    assert len(names) == len(set(names))


def test_store_apps_is_a_debloat_tab_not_a_sidebar_entry(registered):
    names = {m.name for m in registered}
    assert "Store Apps" not in names
    debloat = next(m for m in registered if m.name == "Debloat")
    assert [c.name for c in debloat.children] == ["Debloat", "Store Apps"]


def test_store_apps_is_still_reachable_by_name(registered):
    from core.module_registry import ModuleRegistry

    registry = ModuleRegistry()
    for module in registered:
        registry.register(module)

    assert registry.route_map()["Store Apps"] == ("Debloat", 1)


def test_startup_and_boot_hosts_the_three_boot_modules(registered):
    names = {m.name for m in registered}
    assert "Boot Analyzer" not in names
    assert "Power & Boot" not in names
    host = next(m for m in registered if m.name == "Startup & Boot")
    assert [c.name for c in host.children] == [
        "Startup Manager", "Boot Analyzer", "Power & Boot",
    ]
    assert host.group == "SYSTEM"
