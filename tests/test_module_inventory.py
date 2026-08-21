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


def test_network_extras_no_longer_carries_its_own_hosts_editor(qapp):
    """There were two HOSTS editors: this tab, and the Hosts Editor module."""
    from modules.network_extras.net_extras_module import NetExtrasModule

    widget = NetExtrasModule().create_widget()
    labels = [widget.tabText(i) for i in range(widget.count())]

    assert labels == ["DNS Switcher", "Proxy Settings", "Quick Actions"]


def test_a_module_survives_being_stopped_without_ever_being_built(qapp):
    """A composite child's widget is built lazily, but on_stop still runs.

    wifi_module._stop_scan reached self._progress, which only exists after
    create_widget(). Nothing hit it while every module's widget was built
    eagerly at startup; a never-opened tab makes it reachable.
    """
    from modules.wifi_analyzer.wifi_module import WifiAnalyzerModule

    module = WifiAnalyzerModule()
    module.on_start(_FakeApp())

    module.on_deactivate()   # must not raise
    module.on_stop()         # must not raise


def test_the_network_tools_are_tabs_of_network_diagnostics(registered):
    names = {m.name for m in registered}
    for gone in ("Wi-Fi Analyzer", "Hosts Editor", "Network Extras"):
        assert gone not in names
    host = next(m for m in registered if m.name == "Network Diagnostics")
    assert [c.name for c in host.children] == [
        "Network Diagnostics", "Wi-Fi Analyzer", "Hosts Editor", "Network Extras",
    ]
