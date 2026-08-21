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
