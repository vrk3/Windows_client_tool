import pytest
from unittest.mock import MagicMock, patch
from PyQt6.QtWidgets import QLabel
from core.base_module import BaseModule
from core.module_registry import ModuleRegistry


class FakeModule(BaseModule):
    name = "Fake"
    icon = ""
    description = "Fake module"
    requires_admin = False

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False
        self.activated = False

    def create_widget(self):
        return QLabel("fake")

    def on_activate(self):
        self.activated = True

    def on_deactivate(self):
        self.activated = False

    def on_start(self, app):
        self.app = app
        self.started = True

    def on_stop(self):
        self.stopped = True


class AdminModule(FakeModule):
    name = "AdminOnly"
    requires_admin = True


def test_register_and_start_modules():
    registry = ModuleRegistry()
    mod = FakeModule()
    registry.register(mod)
    app_mock = MagicMock()
    registry.start_all(app_mock)
    assert mod.started
    assert mod.app is app_mock


def test_stop_all_calls_on_stop():
    registry = ModuleRegistry()
    mod = FakeModule()
    registry.register(mod)
    registry.start_all(MagicMock())
    registry.stop_all()
    assert mod.stopped


@patch("core.module_registry.is_admin", return_value=False)
def test_admin_module_disabled_when_not_admin(mock_admin):
    registry = ModuleRegistry()
    mod = AdminModule()
    registry.register(mod)
    registry.start_all(MagicMock())
    assert not mod.started
    assert mod in registry.disabled_modules


@patch("core.module_registry.is_admin", return_value=True)
def test_admin_module_enabled_when_admin(mock_admin):
    registry = ModuleRegistry()
    mod = AdminModule()
    registry.register(mod)
    registry.start_all(MagicMock())
    assert mod.started


def test_module_error_during_start_disables_module():
    registry = ModuleRegistry()

    class BrokenModule(FakeModule):
        name = "Broken"
        def on_start(self, app):
            raise RuntimeError("I broke")

    mod = BrokenModule()
    registry.register(mod)
    registry.start_all(MagicMock())  # Should not raise
    assert mod in registry.disabled_modules


def test_get_modules_returns_all_registered():
    registry = ModuleRegistry()
    m1 = FakeModule()
    m2 = FakeModule()
    m2.name = "Fake2"
    registry.register(m1)
    registry.register(m2)
    assert len(registry.modules) == 2


def test_search_providers_auto_registered():
    from core.search_provider import SearchProvider, SearchQuery, SearchResult, FilterField

    class SearchModule(FakeModule):
        name = "Searchable"
        def get_search_provider(self):
            class FakeProvider(SearchProvider):
                def search(self, q):
                    return []
                def get_filterable_fields(self):
                    return []
            return FakeProvider()

    registry = ModuleRegistry()
    mod = SearchModule()
    registry.register(mod)
    app_mock = MagicMock()
    registry.start_all(app_mock)
    app_mock.search.register_provider.assert_called_once()
