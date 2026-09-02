"""A module that hosts other modules as tabs, and the plumbing it needs.

The sidebar had grown to 41 entries with 15 of them in TOOLS, and several
features were reachable twice by two different implementations. These tests
cover the mechanism that collapses them: lifecycle forwarding, lazy tab
building, admin gating, and the two things that stop a merged-away module
from becoming unreachable — its search provider and its name.
"""
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.module_registry import ModuleRegistry
from core.search_provider import FilterField, SearchProvider


class _Provider(SearchProvider):
    def __init__(self, module_name):
        self.module_name = module_name

    def search(self, query):
        return []

    def get_filterable_fields(self):
        return [FilterField(name="x", label="X")]


class _Leaf(BaseModule):
    name = "Leaf"
    icon = "L"
    description = "leaf"
    group = ModuleGroup.TOOLS

    def __init__(self, provider=None):
        super().__init__()
        self._provider = provider

    def get_search_provider(self):
        return self._provider


class _FakeSearch:
    def __init__(self):
        self.registered = []

    def register_provider(self, provider):
        self.registered.append(provider)


class _FakeApp:
    def __init__(self):
        self.search = _FakeSearch()


def test_get_search_providers_defaults_to_the_single_provider():
    p = _Provider("Leaf")
    assert _Leaf(p).get_search_providers() == [p]


def test_get_search_providers_is_empty_when_there_is_no_provider():
    assert _Leaf(None).get_search_providers() == []


def test_registry_registers_every_provider_a_module_returns():
    a, b = _Provider("A"), _Provider("B")

    class _Multi(_Leaf):
        def get_search_providers(self):
            return [a, b]

    registry = ModuleRegistry()
    registry.register(_Multi())
    app = _FakeApp()
    registry.start_all(app)

    assert app.search.registered == [a, b]


from PyQt6.QtWidgets import QLabel, QTabWidget

from core.composite_module import CompositeModule


class _Recorder(_Leaf):
    """A child that records every lifecycle call it receives."""

    def __init__(self, name, provider=None, requires_admin=False, fail_on_start=False):
        super().__init__(provider)
        self.name = name
        self.requires_admin = requires_admin
        self._fail_on_start = fail_on_start
        self.calls = []
        self.widgets_built = 0

    def create_widget(self):
        self.widgets_built += 1
        return QLabel(self.name)

    def on_start(self, app):
        self.calls.append("start")
        if self._fail_on_start:
            raise RuntimeError("boom")

    def on_activate(self):
        self.calls.append("activate")

    def on_deactivate(self):
        self.calls.append("deactivate")

    def on_stop(self):
        self.calls.append("stop")


def _host(*children, admin=True):
    class _Host(CompositeModule):
        name = "Host"
        icon = "H"
        description = "host"
        group = ModuleGroup.TOOLS

        def __init__(self):
            super().__init__()
            self.children = list(children)

    host = _Host()
    host._is_admin = lambda: admin
    return host


def test_only_the_first_child_widget_is_built_upfront(qapp):
    a, b, c = _Recorder("A"), _Recorder("B"), _Recorder("C")
    host = _host(a, b, c)
    host.on_start(_FakeApp())

    widget = host.create_widget()

    assert isinstance(widget, QTabWidget)
    assert widget.count() == 3
    assert (a.widgets_built, b.widgets_built, c.widgets_built) == (1, 0, 0)


def test_showing_a_tab_builds_exactly_that_child(qapp):
    a, b, c = _Recorder("A"), _Recorder("B"), _Recorder("C")
    host = _host(a, b, c)
    host.on_start(_FakeApp())
    widget = host.create_widget()

    widget.setCurrentIndex(2)

    assert (a.widgets_built, b.widgets_built, c.widgets_built) == (1, 0, 1)


def test_switching_tabs_deactivates_the_outgoing_child_then_activates_the_incoming(qapp):
    a, b = _Recorder("A"), _Recorder("B")
    host = _host(a, b)
    host.on_start(_FakeApp())
    widget = host.create_widget()
    host.on_activate()
    a.calls.clear()
    b.calls.clear()

    widget.setCurrentIndex(1)

    assert a.calls == ["deactivate"]
    assert b.calls == ["activate"]


def test_on_stop_reaches_children_whose_tab_was_never_shown(qapp):
    a, b = _Recorder("A"), _Recorder("B")
    host = _host(a, b)
    host.on_start(_FakeApp())
    host.create_widget()

    host.on_stop()

    assert "stop" in a.calls
    assert "stop" in b.calls


def test_a_child_that_raises_on_start_disables_only_its_own_tab(qapp):
    a, bad, c = _Recorder("A"), _Recorder("Bad", fail_on_start=True), _Recorder("C")
    host = _host(a, bad, c)

    host.on_start(_FakeApp())
    tabs = host.create_widget()

    assert tabs.isTabEnabled(0) is True
    assert tabs.isTabEnabled(1) is False
    assert tabs.isTabEnabled(2) is True
    assert "start" in c.calls


def test_a_crashed_child_does_not_claim_it_needs_admin(qapp):
    """The wrong reason here costs someone an elevated relaunch to disprove."""
    bad = _Recorder("Bad", fail_on_start=True)
    host = _host(_Recorder("A"), bad)
    host.on_start(_FakeApp())
    host.create_widget()

    assert "administrator" not in host.disabled_reason("Bad").lower()
    assert "log" in host.disabled_reason("Bad").lower()


def test_an_admin_child_is_a_disabled_tab_when_unelevated(qapp):
    plain, admin_child = _Recorder("Plain"), _Recorder("Admin", requires_admin=True)
    host = _host(plain, admin_child, admin=False)

    host.on_start(_FakeApp())
    tabs = host.create_widget()

    assert tabs.isTabEnabled(0) is True
    assert tabs.isTabEnabled(1) is False
    assert "administrator" in host.disabled_reason("Admin").lower()
    assert "start" not in admin_child.calls
    assert host.requires_admin is False


def test_a_read_only_admin_child_stays_live_when_unelevated(qapp):
    """Per-module elevation: the tab opens unelevated; writes are gated."""
    plain, ro_child = _Recorder("Plain"), _Recorder("RO", requires_admin=True)
    ro_child.read_only_unelevated = True
    host = _host(plain, ro_child, admin=False)

    host.on_start(_FakeApp())
    tabs = host.create_widget()

    assert tabs.isTabEnabled(0) is True
    assert tabs.isTabEnabled(1) is True
    assert "start" in ro_child.calls


def test_wrap_lets_a_host_keep_its_own_chrome_around_the_tabs(qapp):
    from PyQt6.QtWidgets import QVBoxLayout, QWidget as _QW

    class _Chromed(CompositeModule):
        name = "Chromed"
        icon = "C"
        description = "chromed"
        group = ModuleGroup.TOOLS

        def __init__(self):
            super().__init__()
            self.children = [_Recorder("A")]

        def wrap(self, tabs):
            root = _QW()
            layout = QVBoxLayout(root)
            layout.addWidget(QLabel("search bar"))
            layout.addWidget(tabs)
            return root

    host = _Chromed()
    host._is_admin = lambda: True
    host.on_start(_FakeApp())

    widget = host.create_widget()

    assert not isinstance(widget, QTabWidget)
    assert widget.findChild(QTabWidget) is not None
    assert host.select_child("A") is True


def test_the_host_gathers_its_children_search_providers(qapp):
    pa, pb = _Provider("A"), _Provider("B")
    host = _host(_Recorder("A", pa), _Recorder("B", pb))

    assert host.get_search_providers() == [pa, pb]


def test_the_route_map_resolves_each_child_to_its_host_and_tab(qapp):
    host = _host(_Recorder("A"), _Recorder("B"), _Recorder("C"))

    assert host.route_map() == {
        "A": ("Host", 0),
        "B": ("Host", 1),
        "C": ("Host", 2),
    }


def test_select_child_switches_the_tab_and_reports_unknown_names(qapp):
    a, b = _Recorder("A"), _Recorder("B")
    host = _host(a, b)
    host.on_start(_FakeApp())
    widget = host.create_widget()

    assert host.select_child("B") is True
    assert widget.currentIndex() == 1
    assert host.select_child("Nope") is False


def test_registry_route_map_merges_every_composite(qapp):
    host_a = _host(_Recorder("A1"), _Recorder("A2"))
    host_b = _host(_Recorder("B1"))
    host_b.name = "Host B"

    registry = ModuleRegistry()
    registry.register(host_a)
    registry.register(host_b)
    registry.register(_Leaf(None))

    routes = registry.route_map()

    assert routes["A2"] == ("Host", 1)
    assert routes["B1"] == ("Host B", 0)
    assert "Leaf" not in routes  # a plain module is found by the sidebar itself


def test_registry_route_map_includes_aliases(qapp):
    registry = ModuleRegistry()
    registry.ALIASES = {"Old Name": ("New Home", None)}

    assert registry.route_map()["Old Name"] == ("New Home", None)


def test_resolving_a_child_name_yields_its_host_and_tab():
    from ui.navigation import resolve_target

    routes = {"Wi-Fi Analyzer": ("Network Diagnostics", 1)}

    assert resolve_target("Network Diagnostics", {"Network Diagnostics"}, routes) == (
        "Network Diagnostics", None)
    assert resolve_target("Wi-Fi Analyzer", {"Network Diagnostics"}, routes) == (
        "Network Diagnostics", 1)


def test_a_sidebar_entry_wins_over_a_route_of_the_same_name():
    from ui.navigation import resolve_target

    routes = {"Debloat": ("Somewhere Else", 3)}

    assert resolve_target("Debloat", {"Debloat"}, routes) == ("Debloat", None)


def test_an_unknown_name_resolves_to_nothing():
    from ui.navigation import resolve_target

    assert resolve_target("Nope", {"Debloat"}, {}) == (None, None)


class _Refreshing(_Recorder):
    """A child that wants auto-refresh at its own rate."""

    def __init__(self, name, interval):
        super().__init__(name)
        self._interval = interval
        self.refreshes = 0

    def get_refresh_interval(self):
        return self._interval

    def refresh_data(self):
        self.refreshes += 1


def test_the_host_asks_for_the_fastest_rate_any_child_wants(qapp):
    """A merged child's auto-refresh must survive the merge.

    MainWindow reads get_refresh_interval() off the SELECTED module, so a
    composite that does not answer leaves every child it hosts with no timer
    at all — six modules silently lost auto-refresh this way.
    """
    host = _host(_Refreshing("Fast", 15_000), _Refreshing("Slow", 120_000))
    assert host.get_refresh_interval() == 15_000


def test_a_host_whose_children_all_decline_wants_no_timer(qapp):
    assert _host(_Recorder("A"), _Recorder("B")).get_refresh_interval() is None


def test_a_tick_refreshes_the_visible_child(qapp):
    fast = _Refreshing("Fast", 15_000)
    host = _host(fast, _Refreshing("Slow", 120_000))
    host.on_start(_FakeApp())
    host.create_widget()

    host.refresh_data()

    assert fast.refreshes == 1


def test_a_slow_child_is_not_polled_at_the_fast_childs_rate(qapp):
    """The host ticks at 15s; a child that asked for 120s must not get 8x that."""
    fast, slow = _Refreshing("Fast", 15_000), _Refreshing("Slow", 120_000)
    host = _host(fast, slow)
    host.on_start(_FakeApp())
    widget = host.create_widget()
    widget.setCurrentIndex(1)          # Slow is now visible
    slow.refreshes = 0

    for _ in range(4):                 # four 15s ticks = 60s, still under 120s
        host.refresh_data()

    assert slow.refreshes == 0


def test_a_child_that_declines_auto_refresh_is_never_ticked(qapp):
    plain = _Recorder("Plain")
    host = _host(plain, _Refreshing("Fast", 15_000))
    host.on_start(_FakeApp())
    host.create_widget()

    host.refresh_data()

    assert "activate" not in plain.calls   # refresh_data must not fall back to it
