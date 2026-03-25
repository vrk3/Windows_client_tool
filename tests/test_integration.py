import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QLabel

from core.base_module import BaseModule
from core.event_bus import EventBus
from core.config_manager import ConfigManager
from core.search_engine import SearchEngine
from core.logging_service import LoggingService
from core.module_registry import ModuleRegistry


class TestModule(BaseModule):
    name = "Test Module"
    icon = ""
    description = "Integration test module"
    requires_admin = False

    def __init__(self):
        super().__init__()
        self.started = False
        self.stopped = False

    def create_widget(self):
        return QLabel("Test")

    def on_activate(self):
        pass

    def on_deactivate(self):
        pass

    def on_start(self, app):
        self.app = app
        self.started = True

    def on_stop(self):
        self.stopped = True


@pytest.fixture
def services():
    """Create all core services with temp dirs."""
    tmpdir = tempfile.mkdtemp()
    defaults = {
        "version": 1,
        "app": {"theme": "dark", "log_level": "DEBUG", "window_size": [800, 600]},
        "modules": {"enabled": []},
        "search": {"presets": {}},
    }
    event_bus = EventBus()
    config = ConfigManager(config_dir=tmpdir, defaults=defaults, event_bus=event_bus)
    config.load()
    log_svc = LoggingService(log_dir=os.path.join(tmpdir, "logs"), log_level="DEBUG")
    log_svc.setup()
    search = SearchEngine()
    registry = ModuleRegistry()
    yield {
        "event_bus": event_bus,
        "config": config,
        "logger": log_svc,
        "search": search,
        "registry": registry,
        "tmpdir": tmpdir,
    }
    log_svc.shutdown()


@patch("core.module_registry.is_admin", return_value=True)
def test_full_lifecycle(mock_admin, services):
    """Test: register module -> start -> verify -> stop."""
    app_mock = MagicMock()
    app_mock.search = services["search"]

    mod = TestModule()
    services["registry"].register(mod)
    services["registry"].start_all(app_mock)

    assert mod.started
    assert mod.app is app_mock

    services["registry"].stop_all()
    assert mod.stopped


def test_event_bus_round_trip(services):
    """Test: publish event -> subscriber receives it."""
    received = []
    services["event_bus"].subscribe("test.ping", lambda d: received.append(d))
    services["event_bus"].publish("test.ping", {"msg": "hello"})
    assert received == [{"msg": "hello"}]


def test_config_save_and_reload(services):
    """Test: set value -> save -> reload -> value persists."""
    services["config"].set("app.theme", "light")
    services["config"].save()

    config2 = ConfigManager(
        config_dir=services["tmpdir"],
        defaults={"version": 1, "app": {"theme": "dark"}},
    )
    config2.load()
    assert config2.get("app.theme") == "light"


def test_search_engine_with_no_providers(services):
    """Test: search with no providers returns empty."""
    from core.search_provider import SearchQuery
    results = services["search"].execute(SearchQuery(text="anything"))
    assert results == []
