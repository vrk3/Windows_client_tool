# Core Framework & GUI Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the core framework and GUI shell that all future modules (Data Collection, Process Explorer, AI & Learning) plug into.

**Architecture:** Modular host with PyQt6. An `App` singleton owns all core services (EventBus, ConfigManager, SearchEngine, ThemeManager, LoggingService, ModuleRegistry). Modules implement a `BaseModule` ABC and are registered explicitly. Communication between modules uses a pub/sub EventBus with typed payloads.

**Tech Stack:** Python 3.12+, PyQt6 6.6+, psutil 5.9+, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-core-framework-design.md`

---

## File Map

### Files to Create

| File | Responsibility |
|------|---------------|
| `src/core/__init__.py` | Package init, re-exports core classes |
| `src/core/events.py` | Event name constants + typed dataclass payloads |
| `src/core/types.py` | Shared data models (LogEntry, ProcessInfo, Recommendation) |
| `src/core/event_bus.py` | Pub/sub EventBus with error isolation |
| `src/core/logging_service.py` | Configures Python logging with rotation |
| `src/core/config_manager.py` | JSON config with dot-notation, atomic writes, versioning |
| `src/core/worker.py` | Worker/WorkerSignals for thread pool tasks |
| `src/core/search_provider.py` | SearchProvider ABC, SearchQuery, SearchResult, FilterField |
| `src/core/search_engine.py` | SearchEngine: multi-provider search with presets |
| `src/core/admin_utils.py` | UAC elevation detection and relaunch |
| `src/core/base_module.py` | BaseModule ABC with lifecycle hooks |
| `src/core/module_registry.py` | Module lifecycle management |
| `src/core/theme_manager.py` | Dark/light theme switching via QSS |
| `src/app.py` | App singleton owning all services |
| `src/ui/__init__.py` | Package init |
| `src/ui/main_window.py` | Shell: tabs, menu bar, admin banner |
| `src/ui/toolbar.py` | Dynamic toolbar that changes per active module |
| `src/ui/status_bar.py` | Status bar with module info |
| `src/ui/notification_tray.py` | In-app notification area + system tray icon |
| `src/ui/settings_dialog.py` | Global + per-module settings dialog |
| `src/ui/search_bar.py` | Global search bar widget |
| `src/ui/filter_panel.py` | Expandable filter panel |
| `src/ui/search_results.py` | Results table with sorting/grouping |
| `src/ui/styles/dark.qss` | Dark theme stylesheet |
| `src/ui/styles/light.qss` | Light theme stylesheet |
| `src/modules/__init__.py` | Package init for future modules |
| `config/default_config.json` | Default settings shipped with app |
| `tests/__init__.py` | Test package init |
| `tests/test_events.py` | Tests for event constants and payloads |
| `tests/test_event_bus.py` | Tests for EventBus |
| `tests/test_config_manager.py` | Tests for ConfigManager |
| `tests/test_worker.py` | Tests for Worker cancellation |
| `tests/test_search_engine.py` | Tests for SearchEngine |
| `tests/test_module_registry.py` | Tests for ModuleRegistry |
| `tests/test_logging_service.py` | Tests for LoggingService |
| `tests/test_admin_utils.py` | Tests for admin detection |
| `tests/test_base_module.py` | Tests for BaseModule ABC |
| `tests/test_theme_manager.py` | Tests for ThemeManager |
| `tests/test_filter_panel.py` | Tests for FilterPanel query building |
| `tests/test_notification_tray.py` | Tests for NotificationTray |
| `tests/test_integration.py` | Full app startup integration test |

### Files to Remove

| File | Reason |
|------|--------|
| `src/gui.py` | Replaced by `src/ui/main_window.py` |
| `src/log_reader.py` | Replaced by Data Collection module (Sub-project #2) |

---

## Task 1: Project Scaffolding & Default Config

**Files:**
- Create: `config/default_config.json`
- Create: `src/core/__init__.py`
- Create: `src/ui/__init__.py`
- Create: `src/ui/styles/` (directory)
- Create: `src/modules/__init__.py`
- Create: `tests/__init__.py`
- Modify: `requirements.txt`
- Remove: `src/gui.py`, `src/log_reader.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p src/core src/ui/styles src/modules tests config
```

- [ ] **Step 2: Create default_config.json**

Create `config/default_config.json`:
```json
{
  "version": 1,
  "app": {
    "theme": "dark",
    "window_size": [1400, 900],
    "start_minimized": false,
    "check_admin_on_start": true,
    "log_level": "INFO",
    "shortcuts": {}
  },
  "modules": {
    "enabled": [],
    "data_collection": {},
    "process_explorer": {},
    "ai_learning": {
      "ollama_url": "http://localhost:11434",
      "ollama_model": "llama3",
      "use_remote": false
    }
  },
  "learning": {
    "local_db_path": "history.db",
    "sync_enabled": false,
    "sync_url": ""
  },
  "search": {
    "presets": {}
  }
}
```

- [ ] **Step 3: Create package __init__.py files**

Create empty `src/core/__init__.py`, `src/ui/__init__.py`, `src/modules/__init__.py`, `tests/__init__.py`.

- [ ] **Step 4: Update requirements.txt**

Write `requirements.txt`:
```
PyQt6>=6.6
psutil>=5.9
pytest>=7.0
```

- [ ] **Step 5: Remove old placeholder files**

```bash
rm src/gui.py src/log_reader.py
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "scaffold: project structure, default config, clean up placeholders"
```

---

## Task 2: Event Constants & Shared Types

**Files:**
- Create: `src/core/events.py`
- Create: `src/core/types.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write the failing test for events**

Create `tests/test_events.py`:
```python
from core.events import (
    LOG_ERRORS_FOUND,
    AI_RECOMMENDATION_READY,
    AI_RECOMMENDATION_APPLIED,
    CONFIG_CHANGED,
    MODULE_ERROR,
    LogErrorsFoundData,
    RecommendationReadyData,
    ConfigChangedData,
)
from datetime import datetime


def test_event_constants_are_strings():
    assert isinstance(LOG_ERRORS_FOUND, str)
    assert isinstance(AI_RECOMMENDATION_READY, str)
    assert isinstance(AI_RECOMMENDATION_APPLIED, str)
    assert isinstance(CONFIG_CHANGED, str)
    assert isinstance(MODULE_ERROR, str)


def test_log_errors_found_data():
    data = LogErrorsFoundData(
        source="EventViewer",
        errors=[{"id": 1, "msg": "disk error"}],
        timestamp=datetime(2026, 3, 25, 12, 0, 0),
    )
    assert data.source == "EventViewer"
    assert len(data.errors) == 1
    assert data.timestamp.year == 2026


def test_config_changed_data():
    data = ConfigChangedData(key="app.theme", old_value="light", new_value="dark")
    assert data.key == "app.theme"
    assert data.old_value == "light"
    assert data.new_value == "dark"


def test_recommendation_ready_data():
    data = RecommendationReadyData(
        module="ai_learning", summary="Disable startup service X", details={"confidence": 0.9}
    )
    assert data.module == "ai_learning"
    assert data.summary == "Disable startup service X"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd src && python -m pytest ../tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core'`

- [ ] **Step 3: Implement events.py**

Create `src/core/events.py`:
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List

# Event name constants
LOG_ERRORS_FOUND = "log.errors_found"
AI_RECOMMENDATION_READY = "ai.recommendation_ready"
AI_RECOMMENDATION_APPLIED = "ai.recommendation_applied"
CONFIG_CHANGED = "config.changed"
MODULE_ERROR = "module.error"

# Typed payloads

@dataclass
class LogErrorsFoundData:
    source: str
    errors: List[dict]
    timestamp: datetime


@dataclass
class RecommendationReadyData:
    module: str
    summary: str
    details: dict


@dataclass
class ConfigChangedData:
    key: str
    old_value: Any
    new_value: Any
```

- [ ] **Step 4: Implement types.py**

Create `src/core/types.py`:
```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import List


@dataclass
class LogEntry:
    timestamp: datetime
    source: str
    level: str       # Error, Warning, Info, Debug
    message: str
    raw: dict = field(default_factory=dict)


@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_bytes: int


@dataclass
class Recommendation:
    id: str
    summary: str
    details: str
    confidence: float
    source_entries: List[LogEntry] = field(default_factory=list)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_events.py -v`
Expected: All 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/events.py src/core/types.py tests/test_events.py
git commit -m "feat: add event constants, typed payloads, and shared data types"
```

---

## Task 3: EventBus

**Files:**
- Create: `src/core/event_bus.py`
- Test: `tests/test_event_bus.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_event_bus.py`:
```python
import pytest
from core.event_bus import EventBus


def test_subscribe_and_publish():
    bus = EventBus()
    received = []
    bus.subscribe("test.event", lambda data: received.append(data))
    bus.publish("test.event", {"key": "value"})
    assert received == [{"key": "value"}]


def test_multiple_subscribers():
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("test.event", lambda d: results_a.append(d))
    bus.subscribe("test.event", lambda d: results_b.append(d))
    bus.publish("test.event", "hello")
    assert results_a == ["hello"]
    assert results_b == ["hello"]


def test_unsubscribe():
    bus = EventBus()
    received = []
    callback = lambda d: received.append(d)
    bus.subscribe("test.event", callback)
    bus.unsubscribe("test.event", callback)
    bus.publish("test.event", "ignored")
    assert received == []


def test_publish_no_subscribers_does_not_raise():
    bus = EventBus()
    bus.publish("nonexistent.event", {})  # Should not raise


def test_subscriber_exception_does_not_break_others():
    bus = EventBus()
    results = []

    def bad_callback(data):
        raise ValueError("I broke")

    def good_callback(data):
        results.append(data)

    bus.subscribe("test.event", bad_callback)
    bus.subscribe("test.event", good_callback)
    bus.publish("test.event", "data")
    assert results == ["data"]


def test_different_event_types_are_isolated():
    bus = EventBus()
    results_a = []
    results_b = []
    bus.subscribe("event.a", lambda d: results_a.append(d))
    bus.subscribe("event.b", lambda d: results_b.append(d))
    bus.publish("event.a", "a_data")
    assert results_a == ["a_data"]
    assert results_b == []


def test_unsubscribe_nonexistent_callback_does_not_raise():
    bus = EventBus()
    bus.unsubscribe("test.event", lambda d: None)  # Should not raise


def test_publish_with_typed_dataclass():
    from core.events import ConfigChangedData
    bus = EventBus()
    received = []
    bus.subscribe("config.changed", lambda d: received.append(d))
    payload = ConfigChangedData(key="app.theme", old_value="light", new_value="dark")
    bus.publish("config.changed", payload)
    assert len(received) == 1
    assert received[0].key == "app.theme"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_event_bus.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.event_bus'`

- [ ] **Step 3: Implement EventBus**

Create `src/core/event_bus.py`:
```python
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)


class EventBus:
    """Lightweight in-process pub/sub system.

    Catches per-subscriber exceptions and continues dispatching.
    """

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable) -> None:
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        try:
            self._subscribers[event_type].remove(callback)
        except ValueError:
            pass

    def publish(self, event_type: str, data: object) -> None:
        for callback in self._subscribers.get(event_type, []):
            try:
                callback(data)
            except Exception:
                logger.exception(
                    "EventBus: subscriber %r raised on event %s",
                    callback,
                    event_type,
                )

    def publish_async(self, event_type: str, data: object) -> None:
        """Marshal event to Qt main thread via QTimer.singleShot.
        Requires a running QApplication."""
        from PyQt6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self.publish(event_type, data))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_event_bus.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/event_bus.py tests/test_event_bus.py
git commit -m "feat: add EventBus with per-subscriber error isolation"
```

---

## Task 4: Logging Service

**Files:**
- Create: `src/core/logging_service.py`
- Test: `tests/test_logging_service.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_logging_service.py`:
```python
import logging
import os
import tempfile
from core.logging_service import LoggingService


def test_setup_creates_log_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "logs")
        svc = LoggingService(log_dir=log_path, log_level="DEBUG")
        svc.setup()
        test_logger = logging.getLogger("test.setup")
        test_logger.info("hello from test")
        svc.shutdown()
        log_file = os.path.join(log_path, "app.log")
        assert os.path.exists(log_file)
        with open(log_file) as f:
            content = f.read()
        assert "hello from test" in content


def test_log_level_is_respected():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "logs")
        svc = LoggingService(log_dir=log_path, log_level="WARNING")
        svc.setup()
        test_logger = logging.getLogger("test.level")
        test_logger.debug("debug msg")
        test_logger.warning("warning msg")
        svc.shutdown()
        log_file = os.path.join(log_path, "app.log")
        with open(log_file) as f:
            content = f.read()
        assert "debug msg" not in content
        assert "warning msg" in content


def test_format_includes_level_and_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "logs")
        svc = LoggingService(log_dir=log_path, log_level="INFO")
        svc.setup()
        test_logger = logging.getLogger("mymodule")
        test_logger.info("formatted message")
        svc.shutdown()
        log_file = os.path.join(log_path, "app.log")
        with open(log_file) as f:
            content = f.read()
        assert "[INFO]" in content
        assert "mymodule" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_logging_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.logging_service'`

- [ ] **Step 3: Implement LoggingService**

Create `src/core/logging_service.py`:
```python
import logging
import os
from logging.handlers import RotatingFileHandler


class LoggingService:
    """Configures Python logging with file rotation and console output."""

    LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    def __init__(self, log_dir: str, log_level: str = "INFO"):
        self._log_dir = log_dir
        self._log_level = getattr(logging, log_level.upper(), logging.INFO)
        self._handlers: list[logging.Handler] = []

    def setup(self) -> None:
        os.makedirs(self._log_dir, exist_ok=True)
        log_file = os.path.join(self._log_dir, "app.log")

        formatter = logging.Formatter(self.LOG_FORMAT)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(self._log_level)
        self._handlers.append(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        self._handlers.append(console_handler)

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        for handler in self._handlers:
            root.addHandler(handler)

    def shutdown(self) -> None:
        root = logging.getLogger()
        for handler in self._handlers:
            handler.flush()
            handler.close()
            root.removeHandler(handler)
        self._handlers.clear()

    def set_level(self, level: str) -> None:
        self._log_level = getattr(logging, level.upper(), logging.INFO)
        for handler in self._handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.setLevel(self._log_level)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_logging_service.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/logging_service.py tests/test_logging_service.py
git commit -m "feat: add LoggingService with rotating file handler"
```

---

## Task 5: ConfigManager

**Files:**
- Create: `src/core/config_manager.py`
- Test: `tests/test_config_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_manager.py`:
```python
import json
import os
import tempfile
import pytest
from core.config_manager import ConfigManager


@pytest.fixture
def config_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def default_config():
    return {
        "version": 1,
        "app": {
            "theme": "dark",
            "window_size": [1400, 900],
            "log_level": "INFO",
        },
        "modules": {"enabled": []},
        "search": {"presets": {}},
    }


@pytest.fixture
def manager(config_dir, default_config):
    return ConfigManager(config_dir=config_dir, defaults=default_config)


def test_get_with_dot_notation(manager):
    manager.load()
    assert manager.get("app.theme") == "dark"
    assert manager.get("app.window_size") == [1400, 900]


def test_get_default_value(manager):
    manager.load()
    assert manager.get("nonexistent.key", "fallback") == "fallback"


def test_set_and_get(manager):
    manager.load()
    manager.set("app.theme", "light")
    assert manager.get("app.theme") == "light"


def test_get_module_config(manager):
    manager.load()
    manager.set("modules.process_explorer.refresh_rate", 2000)
    cfg = manager.get_module_config("process_explorer")
    assert cfg["refresh_rate"] == 2000


def test_save_creates_file(manager, config_dir):
    manager.load()
    manager.set("app.theme", "light")
    manager.save()
    config_path = os.path.join(config_dir, "config.json")
    assert os.path.exists(config_path)
    with open(config_path) as f:
        saved = json.load(f)
    assert saved["app"]["theme"] == "light"


def test_save_creates_backup(manager, config_dir):
    manager.load()
    manager.save()
    manager.set("app.theme", "light")
    manager.save()
    backup_path = os.path.join(config_dir, "config.json.bak")
    assert os.path.exists(backup_path)


def test_load_from_existing_file(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    custom = {**default_config, "app": {**default_config["app"], "theme": "light"}}
    with open(config_path, "w") as f:
        json.dump(custom, f)
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.load()
    assert mgr.get("app.theme") == "light"


def test_load_corrupt_file_falls_back_to_defaults(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    with open(config_path, "w") as f:
        f.write("{corrupt json!!!")
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.load()
    assert mgr.get("app.theme") == "dark"  # default


def test_load_corrupt_file_uses_backup(config_dir, default_config):
    config_path = os.path.join(config_dir, "config.json")
    backup_path = os.path.join(config_dir, "config.json.bak")
    backup = {**default_config, "app": {**default_config["app"], "theme": "custom"}}
    with open(backup_path, "w") as f:
        json.dump(backup, f)
    with open(config_path, "w") as f:
        f.write("corrupt!")
    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.load()
    assert mgr.get("app.theme") == "custom"


def test_reset_to_defaults(manager, default_config):
    manager.load()
    manager.set("app.theme", "light")
    manager.reset_to_defaults()
    assert manager.get("app.theme") == "dark"


def test_version_field_preserved(manager):
    manager.load()
    assert manager.get("version") == 1


def test_migration_v1_to_v2(config_dir, default_config):
    """Test that registered migrations run on load."""
    # Write a v1 config file
    config_path = os.path.join(config_dir, "config.json")
    v1_config = {**default_config, "version": 1}
    with open(config_path, "w") as f:
        json.dump(v1_config, f)

    def migrate_v1_to_v2(data):
        data["app"]["new_field"] = "added_by_migration"
        return data

    mgr = ConfigManager(config_dir=config_dir, defaults=default_config)
    mgr.register_migration(1, migrate_v1_to_v2)
    mgr.load()
    assert mgr.get("version") == 2
    assert mgr.get("app.new_field") == "added_by_migration"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_config_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.config_manager'`

- [ ] **Step 3: Implement ConfigManager**

Create `src/core/config_manager.py`:
```python
import copy
import json
import logging
import os
import shutil
from typing import Any, Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Current config schema version
CURRENT_VERSION = 1


class ConfigManager:
    """JSON config with dot-notation access, atomic writes, versioning, and auto-save."""

    AUTOSAVE_DELAY_MS = 2000

    def __init__(self, config_dir: str, defaults: dict, event_bus=None):
        self._config_dir = config_dir
        self._defaults = defaults
        self._data: dict = {}
        self._event_bus = event_bus
        self._config_path = os.path.join(config_dir, "config.json")
        self._backup_path = os.path.join(config_dir, "config.json.bak")
        self._migrations: List[Tuple[int, Callable[[dict], dict]]] = []
        self._autosave_timer = None

    def _ensure_autosave_timer(self):
        """Lazily create QTimer for debounced auto-save (only when Qt is available)."""
        if self._autosave_timer is None:
            try:
                from PyQt6.QtCore import QTimer
                self._autosave_timer = QTimer()
                self._autosave_timer.setSingleShot(True)
                self._autosave_timer.setInterval(self.AUTOSAVE_DELAY_MS)
                self._autosave_timer.timeout.connect(self.save)
            except ImportError:
                pass  # No Qt available (testing without QApp)

    def register_migration(self, from_version: int, fn: Callable[[dict], dict]) -> None:
        """Register a migration function from from_version to from_version+1."""
        self._migrations.append((from_version, fn))
        self._migrations.sort(key=lambda x: x[0])

    def load(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        loaded = self._try_load(self._config_path)
        if loaded is None:
            logger.warning("Config file corrupt or missing, trying backup")
            loaded = self._try_load(self._backup_path)
        if loaded is None:
            logger.warning("No valid config found, using defaults")
            loaded = copy.deepcopy(self._defaults)
        self._data = self._run_migrations(loaded)

    def _run_migrations(self, data: dict) -> dict:
        """Run sequential migrations if config version is outdated."""
        version = data.get("version", 1)
        for from_ver, migrate_fn in self._migrations:
            if version == from_ver:
                logger.info("Migrating config from v%d to v%d", from_ver, from_ver + 1)
                data = migrate_fn(data)
                data["version"] = from_ver + 1
                version = from_ver + 1
        return data

    def _try_load(self, path: str) -> Optional[dict]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def get(self, key: str, default=None) -> Any:
        keys = key.split(".")
        node = self._data
        for k in keys:
            if isinstance(node, dict) and k in node:
                node = node[k]
            else:
                return default
        return node

    def set(self, key: str, value: Any) -> None:
        keys = key.split(".")
        node = self._data
        for k in keys[:-1]:
            if k not in node or not isinstance(node[k], dict):
                node[k] = {}
            node = node[k]
        old_value = node.get(keys[-1])
        node[keys[-1]] = value

        if self._event_bus and old_value != value:
            from core.events import CONFIG_CHANGED, ConfigChangedData
            self._event_bus.publish(
                CONFIG_CHANGED,
                ConfigChangedData(key=key, old_value=old_value, new_value=value),
            )

        # Trigger debounced auto-save
        self._ensure_autosave_timer()
        if self._autosave_timer is not None:
            self._autosave_timer.start()

    def get_module_config(self, module_name: str) -> dict:
        return self.get(f"modules.{module_name}", {})

    def save(self) -> None:
        os.makedirs(self._config_dir, exist_ok=True)
        # Backup existing file before overwrite
        if os.path.exists(self._config_path):
            shutil.copy2(self._config_path, self._backup_path)
        # Atomic write: write to temp, then rename
        tmp_path = self._config_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp_path, self._config_path)

    def reset_to_defaults(self) -> None:
        self._data = copy.deepcopy(self._defaults)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_config_manager.py -v`
Expected: All 11 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/config_manager.py tests/test_config_manager.py
git commit -m "feat: add ConfigManager with atomic writes and corruption recovery"
```

---

## Task 6: Worker Base Classes

**Files:**
- Create: `src/core/worker.py`
- Test: `tests/test_worker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_worker.py`:
```python
from core.worker import Worker, WorkerSignals


def test_worker_cancel_flag():
    def task(worker):
        return "done"

    w = Worker(task)
    assert not w.is_cancelled()
    w.cancel()
    assert w.is_cancelled()


def test_worker_signals_exist():
    signals = WorkerSignals()
    assert hasattr(signals, "result")
    assert hasattr(signals, "error")
    assert hasattr(signals, "progress")
    assert hasattr(signals, "cancelled")


def test_worker_callable_receives_worker_ref():
    received_ref = []

    def task(worker):
        received_ref.append(worker)
        return 42

    w = Worker(task)
    # Simulate what QThreadPool.start() does
    w.run()
    assert len(received_ref) == 1
    assert received_ref[0] is w
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.worker'`

- [ ] **Step 3: Implement Worker**

Create `src/core/worker.py`:
```python
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal


class WorkerSignals(QObject):
    """Signals emitted by Worker during execution."""
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    cancelled = pyqtSignal()


class Worker(QRunnable):
    """Wraps a callable for QThreadPool execution with cancellation support.

    The callable receives the Worker instance as its first argument so it can
    check is_cancelled() cooperatively.

    Usage:
        def my_task(worker):
            for i in range(100):
                if worker.is_cancelled():
                    return
                # do work
                worker.signals.progress.emit(i)
            return result

        w = Worker(my_task)
        w.signals.result.connect(on_done)
        thread_pool.start(w)
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancelled = False

    def run(self):
        try:
            result = self.fn(self, *self.args, **self.kwargs)
            if self._cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_worker.py -v`
Expected: All 3 tests PASS

Note: These tests may require a `QApplication` instance. If so, add a `conftest.py`:

Create `tests/conftest.py`:
```python
import sys
import pytest
from PyQt6.QtWidgets import QApplication

@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app
```

- [ ] **Step 5: Commit**

```bash
git add src/core/worker.py tests/test_worker.py tests/conftest.py
git commit -m "feat: add Worker with cancellation support and WorkerSignals"
```

---

## Task 7: SearchProvider ABC & SearchEngine

**Files:**
- Create: `src/core/search_provider.py`
- Create: `src/core/search_engine.py`
- Test: `tests/test_search_engine.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_search_engine.py`:
```python
import pytest
from datetime import datetime
from core.search_provider import SearchProvider, SearchQuery, SearchResult, FilterField
from core.search_engine import SearchEngine


class MockProvider(SearchProvider):
    def __init__(self, results):
        self._results = results

    def search(self, query):
        return [r for r in self._results if query.text.lower() in r.summary.lower()]

    def get_filterable_fields(self):
        return [FilterField(name="type", label="Type", values=["Error", "Warning"])]


def _make_result(summary, source="test", type_="Error"):
    return SearchResult(
        timestamp=datetime(2026, 3, 25),
        source=source,
        type=type_,
        summary=summary,
        detail=None,
        relevance=1.0,
    )


def test_register_provider_and_search():
    engine = SearchEngine()
    provider = MockProvider([_make_result("disk error"), _make_result("network ok")])
    engine.register_provider(provider)
    query = SearchQuery(text="disk")
    results = engine.execute(query)
    assert len(results) == 1
    assert results[0].summary == "disk error"


def test_multiple_providers():
    engine = SearchEngine()
    p1 = MockProvider([_make_result("disk error", source="logs")])
    p2 = MockProvider([_make_result("disk full", source="events")])
    engine.register_provider(p1)
    engine.register_provider(p2)
    query = SearchQuery(text="disk")
    results = engine.execute(query)
    assert len(results) == 2


def test_empty_query_returns_no_results():
    engine = SearchEngine()
    provider = MockProvider([_make_result("something")])
    engine.register_provider(provider)
    query = SearchQuery(text="nonexistent")
    results = engine.execute(query)
    assert len(results) == 0


def test_no_providers_returns_empty():
    engine = SearchEngine()
    query = SearchQuery(text="anything")
    results = engine.execute(query)
    assert results == []


def test_save_and_load_preset():
    engine = SearchEngine()
    query = SearchQuery(text="critical errors", types=["Error"], regex_enabled=True)
    engine.save_preset("critical_only", query)
    loaded = engine.load_preset("critical_only")
    assert loaded.text == "critical errors"
    assert loaded.types == ["Error"]
    assert loaded.regex_enabled is True


def test_load_nonexistent_preset_returns_none():
    engine = SearchEngine()
    assert engine.load_preset("nonexistent") is None


def test_get_all_presets():
    engine = SearchEngine()
    engine.save_preset("a", SearchQuery(text="a"))
    engine.save_preset("b", SearchQuery(text="b"))
    presets = engine.get_all_presets()
    assert sorted(presets) == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_search_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.search_provider'`

- [ ] **Step 3: Implement SearchProvider ABC**

Create `src/core/search_provider.py`:
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, List, Optional


@dataclass
class FilterField:
    name: str
    label: str
    values: List[str] = field(default_factory=list)


@dataclass
class SearchQuery:
    text: str = ""
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    time_from: Optional[time] = None
    time_to: Optional[time] = None
    types: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    severity: Optional[str] = None
    module: Optional[str] = None
    regex_enabled: bool = False


@dataclass
class SearchResult:
    timestamp: datetime
    source: str
    type: str
    summary: str
    detail: Any
    relevance: float


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: SearchQuery) -> List[SearchResult]:
        ...

    @abstractmethod
    def get_filterable_fields(self) -> List[FilterField]:
        ...
```

- [ ] **Step 4: Implement SearchEngine**

Create `src/core/search_engine.py`:
```python
import logging
from dataclasses import asdict
from typing import List, Optional
from core.search_provider import SearchProvider, SearchQuery, SearchResult

logger = logging.getLogger(__name__)


class SearchEngine:
    """Aggregates search results from multiple providers with persistent presets."""

    def __init__(self, config_manager=None):
        self._providers: List[SearchProvider] = []
        self._presets: dict[str, SearchQuery] = {}
        self._config = config_manager
        # Load presets from config if available
        if self._config:
            self._load_presets_from_config()

    def _load_presets_from_config(self):
        saved = self._config.get("search.presets", {})
        for name, data in saved.items():
            try:
                self._presets[name] = SearchQuery(**data)
            except (TypeError, KeyError):
                logger.warning("Failed to load preset '%s'", name)

    def _save_presets_to_config(self):
        if self._config:
            serialized = {}
            for name, query in self._presets.items():
                serialized[name] = asdict(query)
            self._config.set("search.presets", serialized)

    def register_provider(self, provider: SearchProvider) -> None:
        self._providers.append(provider)

    def execute(self, query: SearchQuery) -> List[SearchResult]:
        results: List[SearchResult] = []
        for provider in self._providers:
            try:
                results.extend(provider.search(query))
            except Exception:
                logger.exception("SearchEngine: provider %r failed", provider)
        results.sort(key=lambda r: r.relevance, reverse=True)
        return results

    def save_preset(self, name: str, query: SearchQuery) -> None:
        self._presets[name] = query
        self._save_presets_to_config()

    def load_preset(self, name: str) -> Optional[SearchQuery]:
        return self._presets.get(name)

    def get_all_presets(self) -> List[str]:
        return list(self._presets.keys())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_search_engine.py -v`
Expected: All 7 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/core/search_provider.py src/core/search_engine.py tests/test_search_engine.py
git commit -m "feat: add SearchProvider ABC and SearchEngine with presets"
```

---

## Task 8: Admin Utils

**Files:**
- Create: `src/core/admin_utils.py`
- Test: `tests/test_admin_utils.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_admin_utils.py`:
```python
import sys
from core.admin_utils import is_admin, get_restart_as_admin_command


def test_is_admin_returns_bool():
    result = is_admin()
    assert isinstance(result, bool)


def test_get_restart_command_returns_executable():
    cmd = get_restart_as_admin_command()
    assert cmd["executable"] == sys.executable
    assert isinstance(cmd["args"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_admin_utils.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.admin_utils'`

- [ ] **Step 3: Implement admin_utils**

Create `src/core/admin_utils.py`:
```python
import ctypes
import sys


def is_admin() -> bool:
    """Check if the current process is running with administrator privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def get_restart_as_admin_command() -> dict:
    """Return the executable and args needed to relaunch as admin.

    Usage with ShellExecuteW:
        info = get_restart_as_admin_command()
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", info["executable"], " ".join(info["args"]), None, 1
        )
    """
    return {
        "executable": sys.executable,
        "args": sys.argv,
    }


def restart_as_admin() -> None:
    """Relaunch the current process with administrator privileges via UAC prompt."""
    info = get_restart_as_admin_command()
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", info["executable"], " ".join(info["args"]), None, 1
    )
    sys.exit(0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_admin_utils.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/admin_utils.py tests/test_admin_utils.py
git commit -m "feat: add admin elevation detection and relaunch utils"
```

---

## Task 9: BaseModule ABC

**Files:**
- Create: `src/core/base_module.py`
- Test: `tests/test_base_module.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_base_module.py`:
```python
from PyQt6.QtWidgets import QWidget, QLabel
from core.base_module import BaseModule


class StubModule(BaseModule):
    name = "Stub"
    icon = ""
    description = "A stub module"
    requires_admin = False

    def create_widget(self):
        return QLabel("stub")

    def on_activate(self):
        pass

    def on_deactivate(self):
        pass

    def on_start(self, app):
        self.app = app

    def on_stop(self):
        pass


def test_stub_module_can_be_instantiated():
    mod = StubModule()
    assert mod.name == "Stub"
    assert mod.requires_admin is False


def test_create_widget_returns_qwidget():
    mod = StubModule()
    widget = mod.create_widget()
    assert isinstance(widget, QWidget)


def test_default_search_provider_is_none():
    mod = StubModule()
    assert mod.get_search_provider() is None


def test_default_toolbar_actions_is_empty():
    mod = StubModule()
    assert mod.get_toolbar_actions() == []


def test_default_menu_actions_is_empty():
    mod = StubModule()
    assert mod.get_menu_actions() == []


def test_cancel_all_workers():
    mod = StubModule()
    # Simulate tracked workers
    class FakeWorker:
        def __init__(self):
            self.cancelled = False
        def cancel(self):
            self.cancelled = True
    w1, w2 = FakeWorker(), FakeWorker()
    mod._workers.append(w1)
    mod._workers.append(w2)
    mod.cancel_all_workers()
    assert w1.cancelled
    assert w2.cancelled
    assert mod._workers == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_base_module.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.base_module'`

- [ ] **Step 3: Implement BaseModule**

Create `src/core/base_module.py`:
```python
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional

from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from core.search_provider import SearchProvider


class BaseModule(ABC):
    """Abstract base class for all application modules.

    Modules implement this interface and register with ModuleRegistry.
    The App instance is passed via on_start() for access to core services.
    """

    name: str
    icon: str
    description: str
    requires_admin: bool

    def __init__(self):
        self._workers: List = []
        self.app = None

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Return the main widget for this module's tab."""
        ...

    @abstractmethod
    def on_activate(self) -> None:
        """Called when this module's tab is selected."""
        ...

    @abstractmethod
    def on_deactivate(self) -> None:
        """Called when this module's tab loses focus."""
        ...

    @abstractmethod
    def on_start(self, app) -> None:
        """Called at app startup. Store app reference: self.app = app"""
        ...

    @abstractmethod
    def on_stop(self) -> None:
        """Called at app shutdown."""
        ...

    def get_config_schema(self) -> dict:
        return {}

    def get_toolbar_actions(self) -> list:
        return []

    def get_menu_actions(self) -> list:
        return []

    def get_status_info(self) -> str:
        return ""

    def get_search_provider(self) -> Optional["SearchProvider"]:
        return None

    def cancel_all_workers(self) -> None:
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_base_module.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/base_module.py tests/test_base_module.py
git commit -m "feat: add BaseModule ABC with lifecycle hooks and worker tracking"
```

---

## Task 10: ThemeManager

**Files:**
- Create: `src/core/theme_manager.py`
- Create: `src/ui/styles/dark.qss`
- Create: `src/ui/styles/light.qss`
- Test: `tests/test_theme_manager.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_theme_manager.py`:
```python
import os
import tempfile
from core.theme_manager import ThemeManager


def test_apply_valid_theme(tmp_path):
    styles_dir = str(tmp_path)
    (tmp_path / "dark.qss").write_text("QMainWindow { background: #1e1e1e; }")
    (tmp_path / "light.qss").write_text("QMainWindow { background: #f5f5f5; }")
    tm = ThemeManager(styles_dir=styles_dir)
    tm.apply_theme("dark")
    assert tm.current_theme == "dark"
    tm.apply_theme("light")
    assert tm.current_theme == "light"


def test_apply_invalid_theme_falls_back_to_dark(tmp_path):
    styles_dir = str(tmp_path)
    (tmp_path / "dark.qss").write_text("QMainWindow { background: #1e1e1e; }")
    tm = ThemeManager(styles_dir=styles_dir)
    tm.apply_theme("neon")
    assert tm.current_theme == "dark"


def test_toggle(tmp_path):
    styles_dir = str(tmp_path)
    (tmp_path / "dark.qss").write_text("body {}")
    (tmp_path / "light.qss").write_text("body {}")
    tm = ThemeManager(styles_dir=styles_dir)
    assert tm.current_theme == "dark"
    result = tm.toggle()
    assert result == "light"
    assert tm.current_theme == "light"
    result = tm.toggle()
    assert result == "dark"


def test_missing_qss_file_does_not_crash(tmp_path):
    styles_dir = str(tmp_path)
    tm = ThemeManager(styles_dir=styles_dir)
    tm.apply_theme("dark")  # File does not exist — should not crash
    # Theme stays at default since load failed
    assert tm.current_theme == "dark"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_theme_manager.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.theme_manager'`

- [ ] **Step 3: Create dark.qss**

Create `src/ui/styles/dark.qss`:
```css
QMainWindow {
    background-color: #1e1e1e;
    color: #d4d4d4;
}

QTabWidget::pane {
    border: 1px solid #3c3c3c;
    background-color: #252526;
}

QTabBar::tab {
    background-color: #2d2d2d;
    color: #d4d4d4;
    padding: 8px 16px;
    border: 1px solid #3c3c3c;
    border-bottom: none;
}

QTabBar::tab:selected {
    background-color: #1e1e1e;
    border-bottom: 2px solid #007acc;
}

QToolBar {
    background-color: #333333;
    border: none;
    spacing: 4px;
    padding: 2px;
}

QStatusBar {
    background-color: #007acc;
    color: white;
}

QLineEdit {
    background-color: #3c3c3c;
    color: #d4d4d4;
    border: 1px solid #555555;
    padding: 4px 8px;
    border-radius: 2px;
}

QLineEdit:focus {
    border: 1px solid #007acc;
}

QPushButton {
    background-color: #0e639c;
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 2px;
}

QPushButton:hover {
    background-color: #1177bb;
}

QPushButton:pressed {
    background-color: #094771;
}

QTreeView, QTableView, QListView {
    background-color: #1e1e1e;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    alternate-background-color: #252526;
}

QHeaderView::section {
    background-color: #333333;
    color: #d4d4d4;
    padding: 4px 8px;
    border: 1px solid #3c3c3c;
}

QMenuBar {
    background-color: #333333;
    color: #d4d4d4;
}

QMenuBar::item:selected {
    background-color: #094771;
}

QMenu {
    background-color: #252526;
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
}

QMenu::item:selected {
    background-color: #094771;
}

QCheckBox {
    color: #d4d4d4;
}

QLabel {
    color: #d4d4d4;
}

QGroupBox {
    color: #d4d4d4;
    border: 1px solid #3c3c3c;
    margin-top: 8px;
    padding-top: 8px;
}
```

- [ ] **Step 2: Create light.qss**

Create `src/ui/styles/light.qss`:
```css
QMainWindow {
    background-color: #f5f5f5;
    color: #1e1e1e;
}

QTabWidget::pane {
    border: 1px solid #d4d4d4;
    background-color: #ffffff;
}

QTabBar::tab {
    background-color: #ececec;
    color: #1e1e1e;
    padding: 8px 16px;
    border: 1px solid #d4d4d4;
    border-bottom: none;
}

QTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom: 2px solid #007acc;
}

QToolBar {
    background-color: #e8e8e8;
    border: none;
    spacing: 4px;
    padding: 2px;
}

QStatusBar {
    background-color: #007acc;
    color: white;
}

QLineEdit {
    background-color: #ffffff;
    color: #1e1e1e;
    border: 1px solid #c8c8c8;
    padding: 4px 8px;
    border-radius: 2px;
}

QLineEdit:focus {
    border: 1px solid #007acc;
}

QPushButton {
    background-color: #0e639c;
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 2px;
}

QPushButton:hover {
    background-color: #1177bb;
}

QTreeView, QTableView, QListView {
    background-color: #ffffff;
    color: #1e1e1e;
    border: 1px solid #d4d4d4;
    alternate-background-color: #f5f5f5;
}

QHeaderView::section {
    background-color: #e8e8e8;
    color: #1e1e1e;
    padding: 4px 8px;
    border: 1px solid #d4d4d4;
}

QMenuBar {
    background-color: #e8e8e8;
    color: #1e1e1e;
}

QMenu {
    background-color: #ffffff;
    color: #1e1e1e;
    border: 1px solid #d4d4d4;
}

QMenu::item:selected {
    background-color: #cce5ff;
}

QCheckBox {
    color: #1e1e1e;
}

QLabel {
    color: #1e1e1e;
}
```

- [ ] **Step 3: Implement ThemeManager**

Create `src/core/theme_manager.py`:
```python
import logging
import os
from typing import Optional

from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class ThemeManager:
    """Manages dark/light theme switching via QSS stylesheets."""

    THEMES = ("dark", "light")

    def __init__(self, styles_dir: str):
        self._styles_dir = styles_dir
        self._current_theme: str = "dark"

    @property
    def current_theme(self) -> str:
        return self._current_theme

    def apply_theme(self, theme: str) -> None:
        if theme not in self.THEMES:
            logger.warning("Unknown theme '%s', falling back to dark", theme)
            theme = "dark"
        qss_path = os.path.join(self._styles_dir, f"{theme}.qss")
        stylesheet = self._load_qss(qss_path)
        if stylesheet is not None:
            app = QApplication.instance()
            if app:
                app.setStyleSheet(stylesheet)
            self._current_theme = theme
            logger.info("Applied theme: %s", theme)
        else:
            logger.error("Failed to load theme '%s' from %s", theme, qss_path)

    def _load_qss(self, path: str) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def toggle(self) -> str:
        new_theme = "light" if self._current_theme == "dark" else "dark"
        self.apply_theme(new_theme)
        return new_theme
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_theme_manager.py -v`
Expected: All 4 tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/theme_manager.py src/ui/styles/dark.qss src/ui/styles/light.qss tests/test_theme_manager.py
git commit -m "feat: add ThemeManager with dark and light QSS themes"
```

---

## Task 11: ModuleRegistry

**Files:**
- Create: `src/core/module_registry.py`
- Test: `tests/test_module_registry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_module_registry.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && python -m pytest ../tests/test_module_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.module_registry'`

- [ ] **Step 3: Implement ModuleRegistry**

Create `src/core/module_registry.py`:
```python
import logging
from typing import List

from core.admin_utils import is_admin
from core.base_module import BaseModule

logger = logging.getLogger(__name__)


class ModuleRegistry:
    """Manages module lifecycle: registration, startup, shutdown."""

    def __init__(self):
        self._modules: List[BaseModule] = []
        self._disabled: List[BaseModule] = []

    @property
    def modules(self) -> List[BaseModule]:
        return list(self._modules)

    @property
    def disabled_modules(self) -> List[BaseModule]:
        return list(self._disabled)

    def register(self, module: BaseModule) -> None:
        self._modules.append(module)
        logger.info("Registered module: %s", module.name)

    def start_all(self, app) -> None:
        running_as_admin = is_admin()
        for module in self._modules:
            if module.requires_admin and not running_as_admin:
                logger.warning(
                    "Module '%s' requires admin — disabled", module.name
                )
                self._disabled.append(module)
                continue
            try:
                module.on_start(app)
                # Auto-register search provider if module provides one
                provider = module.get_search_provider()
                if provider is not None:
                    app.search.register_provider(provider)
                logger.info("Started module: %s", module.name)
            except Exception:
                logger.exception("Module '%s' failed to start", module.name)
                self._disabled.append(module)

    def stop_all(self) -> None:
        for module in self._modules:
            if module in self._disabled:
                continue
            try:
                module.cancel_all_workers()
                module.on_stop()
                logger.info("Stopped module: %s", module.name)
            except Exception:
                logger.exception("Module '%s' failed to stop cleanly", module.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && python -m pytest ../tests/test_module_registry.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/module_registry.py tests/test_module_registry.py
git commit -m "feat: add ModuleRegistry with lifecycle management and admin checks"
```

---

## Task 12: App Singleton

**Files:**
- Create: `src/app.py`

- [ ] **Step 1: Implement App singleton**

Create `src/app.py`:
```python
import os
import sys
from typing import ClassVar, Optional

from PyQt6.QtCore import QThreadPool

from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.logging_service import LoggingService
from core.module_registry import ModuleRegistry
from core.search_engine import SearchEngine
from core.theme_manager import ThemeManager


def _get_app_data_dir() -> str:
    """Return %APPDATA%/WindowsTweaker, creating it if needed."""
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    app_dir = os.path.join(base, "WindowsTweaker")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def _get_default_config() -> dict:
    """Load default config from config/default_config.json."""
    import json
    config_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "config", "default_config.json"
    )
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


class App:
    """Singleton that owns all core services. Created once in main.py."""

    instance: ClassVar[Optional["App"]] = None

    def __init__(self, app_data_dir: Optional[str] = None):
        if App.instance is not None:
            raise RuntimeError("App is a singleton — use App.get()")
        App.instance = self

        self._app_data_dir = app_data_dir or _get_app_data_dir()
        defaults = _get_default_config()

        # Core services
        self.event_bus = EventBus()
        self.config = ConfigManager(
            config_dir=self._app_data_dir,
            defaults=defaults,
            event_bus=self.event_bus,
        )
        self.config.load()

        log_dir = os.path.join(self._app_data_dir, "logs")
        log_level = self.config.get("app.log_level", "INFO")
        self.logger = LoggingService(log_dir=log_dir, log_level=log_level)
        self.logger.setup()

        styles_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "ui", "styles"
        )
        self.theme = ThemeManager(styles_dir=styles_dir)

        self.search = SearchEngine(config_manager=self.config)
        self.module_registry = ModuleRegistry()
        self.thread_pool = QThreadPool.globalInstance()

    @classmethod
    def get(cls) -> "App":
        assert cls.instance is not None, "App not initialized"
        return cls.instance

    def start(self) -> None:
        """Initialize theme and start all registered modules."""
        theme = self.config.get("app.theme", "dark")
        self.theme.apply_theme(theme)
        self.module_registry.start_all(self)

    def shutdown(self) -> None:
        """Stop modules, save config, shut down logging."""
        self.module_registry.stop_all()
        self.config.save()
        self.logger.shutdown()
        self.thread_pool.waitForDone(5000)
        App.instance = None
```

- [ ] **Step 2: Commit**

```bash
git add src/app.py
git commit -m "feat: add App singleton wiring all core services together"
```

---

## Task 13: Main Window Shell

**Files:**
- Create: `src/ui/main_window.py`
- Create: `src/ui/toolbar.py`
- Create: `src/ui/status_bar.py`

- [ ] **Step 1: Implement toolbar.py**

Create `src/ui/toolbar.py`:
```python
from PyQt6.QtWidgets import QToolBar, QWidget


class DynamicToolbar(QToolBar):
    """Toolbar that updates actions based on the active module."""

    def __init__(self, parent: QWidget = None):
        super().__init__("Main Toolbar", parent)
        self.setMovable(False)
        self._module_actions = []

    def set_module_actions(self, actions: list) -> None:
        """Replace module-specific actions."""
        for action in self._module_actions:
            self.removeAction(action)
        self._module_actions = list(actions)
        for action in self._module_actions:
            self.addAction(action)
```

- [ ] **Step 2: Implement status_bar.py**

Create `src/ui/status_bar.py`:
```python
from PyQt6.QtWidgets import QStatusBar, QLabel, QWidget


class AppStatusBar(QStatusBar):
    """Status bar showing module info and admin status."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._module_label = QLabel("")
        self._admin_label = QLabel("")
        self.addPermanentWidget(self._module_label)
        self.addPermanentWidget(self._admin_label)

    def set_module_info(self, text: str) -> None:
        self._module_label.setText(text)

    def set_admin_status(self, is_admin: bool) -> None:
        if is_admin:
            self._admin_label.setText("Admin")
            self._admin_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        else:
            self._admin_label.setText("User")
            self._admin_label.setStyleSheet("color: #ce9178;")
```

- [ ] **Step 3: Implement main_window.py**

Create `src/ui/main_window.py`:
```python
import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.admin_utils import is_admin, restart_as_admin
from core.base_module import BaseModule
from ui.status_bar import AppStatusBar
from ui.toolbar import DynamicToolbar

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Application shell with tabs, toolbar, menu bar, and admin banner."""

    def __init__(self, app_instance):
        super().__init__()
        self._app = app_instance
        self.setWindowTitle("Windows 11 Tweaker & Optimizer")
        self._restore_window_size()

        # Central layout
        central = QWidget()
        self._layout = QVBoxLayout(central)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Admin banner
        if not is_admin():
            self._layout.addWidget(self._create_admin_banner())

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._layout.addWidget(self._tabs)

        self.setCentralWidget(central)

        # Toolbar
        self._toolbar = DynamicToolbar(self)
        self.addToolBar(self._toolbar)

        # Status bar
        self._status_bar = AppStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.set_admin_status(is_admin())

        # Menu bar
        self._setup_menus()

        # Keyboard shortcuts
        self._setup_shortcuts()

        # Track modules per tab index
        self._tab_modules: list[BaseModule] = []
        self._active_tab_index: int = -1

    def _restore_window_size(self):
        size = self._app.config.get("app.window_size", [1400, 900])
        self.resize(size[0], size[1])

    def _create_admin_banner(self) -> QWidget:
        banner = QWidget()
        banner.setStyleSheet("background-color: #805500; padding: 4px;")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel("Some features require administrator privileges.")
        label.setStyleSheet("color: white;")
        layout.addWidget(label)
        layout.addStretch()
        btn = QPushButton("Restart as Admin")
        btn.clicked.connect(self._on_restart_as_admin)
        layout.addWidget(btn)
        return banner

    def _on_restart_as_admin(self):
        reply = QMessageBox.question(
            self,
            "Restart as Administrator",
            "The application will restart with elevated privileges. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            restart_as_admin()

    def add_module_tab(self, module: BaseModule, enabled: bool = True) -> None:
        widget = module.create_widget()
        index = self._tabs.addTab(widget, module.name)
        self._tab_modules.append(module)
        if not enabled:
            self._tabs.setTabEnabled(index, False)
            self._tabs.setTabToolTip(index, "Requires administrator privileges")

    def _on_tab_changed(self, index: int):
        # Deactivate only the previously active module
        if 0 <= self._active_tab_index < len(self._tab_modules):
            old_mod = self._tab_modules[self._active_tab_index]
            if old_mod not in self._app.module_registry.disabled_modules:
                try:
                    old_mod.on_deactivate()
                except Exception:
                    logger.exception("Error deactivating module %s", old_mod.name)

        # Activate current
        self._active_tab_index = index
        if 0 <= index < len(self._tab_modules):
            mod = self._tab_modules[index]
            if mod not in self._app.module_registry.disabled_modules:
                try:
                    mod.on_activate()
                    self._toolbar.set_module_actions(mod.get_toolbar_actions())
                    self._status_bar.set_module_info(mod.get_status_info())
                except Exception:
                    logger.exception("Error activating module %s", mod.name)

    def _setup_menus(self):
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        theme_action = QAction("Toggle &Theme", self)
        theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(theme_action)

    def _setup_shortcuts(self):
        # Ctrl+Tab / Ctrl+Shift+Tab for tab navigation
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self._next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(self._prev_tab)

        # Ctrl+1..9 for direct tab access
        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda idx=i - 1: self._tabs.setCurrentIndex(idx))

        # F5 refresh
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_current)

    def _next_tab(self):
        idx = (self._tabs.currentIndex() + 1) % max(self._tabs.count(), 1)
        self._tabs.setCurrentIndex(idx)

    def _prev_tab(self):
        idx = (self._tabs.currentIndex() - 1) % max(self._tabs.count(), 1)
        self._tabs.setCurrentIndex(idx)

    def _refresh_current(self):
        # Modules can override on_activate to handle refresh
        idx = self._tabs.currentIndex()
        if 0 <= idx < len(self._tab_modules):
            mod = self._tab_modules[idx]
            mod.on_activate()

    def _open_settings(self):
        # Placeholder — implemented in Task 16
        logger.info("Settings dialog requested")

    def _toggle_theme(self):
        new_theme = self._app.theme.toggle()
        self._app.config.set("app.theme", new_theme)

    def closeEvent(self, event):
        size = self.size()
        self._app.config.set("app.window_size", [size.width(), size.height()])
        self._app.shutdown()
        event.accept()
```

- [ ] **Step 4: Commit**

```bash
git add src/ui/main_window.py src/ui/toolbar.py src/ui/status_bar.py
git commit -m "feat: add MainWindow shell with tabs, toolbar, status bar, and admin banner"
```

---

## Task 14: Notification Tray

**Files:**
- Create: `src/ui/notification_tray.py`

- [ ] **Step 1: Implement notification_tray.py**

Create `src/ui/notification_tray.py`:
```python
import logging
from typing import List

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class NotificationItem:
    def __init__(self, title: str, message: str, level: str = "info"):
        self.title = title
        self.message = message
        self.level = level  # info, warning, error


class NotificationTray(QWidget):
    """In-app notification area showing recent alerts."""

    MAX_VISIBLE = 50

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._notifications: List[NotificationItem] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Notifications"))
        header.addStretch()
        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.clicked.connect(self.clear_all)
        header.addWidget(self._clear_btn)
        layout.addLayout(header)

        # Scroll area for notifications
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll)

    def add_notification(self, item: NotificationItem) -> None:
        self._notifications.insert(0, item)
        if len(self._notifications) > self.MAX_VISIBLE:
            self._notifications = self._notifications[: self.MAX_VISIBLE]
        self._render_item(item)

    def _render_item(self, item: NotificationItem) -> None:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        colors = {"info": "#264f78", "warning": "#805500", "error": "#6e1e1e"}
        frame.setStyleSheet(
            f"background-color: {colors.get(item.level, '#264f78')}; "
            f"border-radius: 4px; padding: 4px; margin: 2px;"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 4, 8, 4)
        title = QLabel(f"<b>{item.title}</b>")
        title.setStyleSheet("color: white;")
        layout.addWidget(title)
        msg = QLabel(item.message)
        msg.setStyleSheet("color: #d4d4d4;")
        msg.setWordWrap(True)
        layout.addWidget(msg)
        self._scroll_layout.insertWidget(0, frame)

    def clear_all(self) -> None:
        self._notifications.clear()
        while self._scroll_layout.count():
            child = self._scroll_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()


class SystemTrayManager:
    """Manages the system tray icon with context menu and balloon notifications."""

    def __init__(self, main_window, icon: QIcon = None):
        self._window = main_window
        self._tray = QSystemTrayIcon(icon or QIcon(), main_window)
        self._setup_menu()
        self._unread_count = 0

    def _setup_menu(self):
        menu = QMenu()
        show_action = QAction("Show/Hide", self._window)
        show_action.triggered.connect(self._toggle_window)
        menu.addAction(show_action)
        menu.addSeparator()
        exit_action = QAction("Exit", self._window)
        exit_action.triggered.connect(self._window.close)
        menu.addAction(exit_action)
        self._tray.setContextMenu(menu)

    def show(self) -> None:
        self._tray.show()

    def _toggle_window(self):
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
            self._window.activateWindow()

    def show_balloon(self, title: str, message: str, icon_type=None) -> None:
        if icon_type is None:
            icon_type = QSystemTrayIcon.MessageIcon.Information
        self._tray.showMessage(title, message, icon_type, 5000)

    def set_unread_count(self, count: int) -> None:
        self._unread_count = count
        tooltip = f"Windows Tweaker — {count} unread" if count else "Windows Tweaker"
        self._tray.setToolTip(tooltip)
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/notification_tray.py
git commit -m "feat: add in-app notification tray and system tray icon manager"
```

---

## Task 15: Search UI Components

**Files:**
- Create: `src/ui/search_bar.py`
- Create: `src/ui/filter_panel.py`
- Create: `src/ui/search_results.py`

- [ ] **Step 1: Implement search_bar.py**

Create `src/ui/search_bar.py`:
```python
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SearchBar(QWidget):
    """Global search bar with regex toggle and filter expand button."""

    search_requested = pyqtSignal(str, bool)  # text, regex_enabled
    filter_toggled = pyqtSignal(bool)  # expanded

    DEBOUNCE_MS = 300

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._filter_expanded = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Search all logs, events, recommendations...")
        self._input.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._input, stretch=1)

        self._regex_cb = QCheckBox("Regex")
        layout.addWidget(self._regex_cb)

        self._filter_btn = QPushButton("Filters")
        self._filter_btn.setCheckable(True)
        self._filter_btn.toggled.connect(self._on_filter_toggled)
        layout.addWidget(self._filter_btn)

        # Debounce timer
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self.DEBOUNCE_MS)
        self._debounce.timeout.connect(self._emit_search)

    def _on_text_changed(self, text: str):
        self._debounce.start()

    def _emit_search(self):
        self.search_requested.emit(self._input.text(), self._regex_cb.isChecked())

    def _on_filter_toggled(self, checked: bool):
        self._filter_expanded = checked
        self.filter_toggled.emit(checked)

    def focus_search(self):
        self._input.setFocus()
        self._input.selectAll()

    def focus_search_with_filters(self):
        self.focus_search()
        if not self._filter_expanded:
            self._filter_btn.setChecked(True)

    def clear(self):
        self._input.clear()
        if self._filter_expanded:
            self._filter_btn.setChecked(False)
```

- [ ] **Step 2: Implement filter_panel.py**

Create `src/ui/filter_panel.py`:
```python
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from core.search_provider import SearchQuery


class FilterPanel(QWidget):
    """Expandable filter panel for refining search queries."""

    filters_changed = pyqtSignal(object)  # emits SearchQuery

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Date range
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Date:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        date_row.addWidget(self._date_from)
        date_row.addWidget(QLabel("to"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        date_row.addWidget(self._date_to)

        date_row.addWidget(QLabel("Time:"))
        self._time_from = QTimeEdit()
        date_row.addWidget(self._time_from)
        date_row.addWidget(QLabel("to"))
        self._time_to = QTimeEdit()
        date_row.addWidget(self._time_to)
        date_row.addStretch()
        layout.addLayout(date_row)

        # Type checkboxes
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._type_checks = {}
        for t in ["Error", "Warning", "Info", "Debug"]:
            cb = QCheckBox(t)
            cb.setChecked(t in ("Error", "Warning"))
            cb.stateChanged.connect(lambda _: self._emit_filters())
            self._type_checks[t] = cb
            type_row.addWidget(cb)
        type_row.addStretch()
        layout.addLayout(type_row)

        # Source checkboxes
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        self._source_checks = {}
        for s in ["EventViewer", "CBS", "DISM", "PerfMon", "AI"]:
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda _: self._emit_filters())
            self._source_checks[s] = cb
            source_row.addWidget(cb)
        source_row.addStretch()
        layout.addLayout(source_row)

        # Actions row
        action_row = QHBoxLayout()
        self._preset_combo = QComboBox()
        self._preset_combo.setPlaceholderText("Load Preset...")
        action_row.addWidget(self._preset_combo)
        save_btn = QPushButton("Save Preset")
        action_row.addWidget(save_btn)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        action_row.addWidget(clear_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

    def _emit_filters(self):
        query = self.build_query("")
        self.filters_changed.emit(query)

    def build_query(self, text: str, regex: bool = False) -> SearchQuery:
        types = [t for t, cb in self._type_checks.items() if cb.isChecked()]
        sources = [s for s, cb in self._source_checks.items() if cb.isChecked()]
        return SearchQuery(
            text=text,
            types=types,
            sources=sources,
            regex_enabled=regex,
        )

    def _clear_all(self):
        for cb in self._type_checks.values():
            cb.setChecked(False)
        for cb in self._source_checks.values():
            cb.setChecked(True)
        self._emit_filters()
```

- [ ] **Step 3: Implement search_results.py**

Create `src/ui/search_results.py`:
```python
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QHeaderView, QTableView, QVBoxLayout, QWidget

from core.search_provider import SearchResult


class SearchResultsTable(QWidget):
    """Table displaying search results with sortable columns."""

    result_activated = pyqtSignal(object)  # emits SearchResult on double-click

    COLUMNS = ["Time", "Source", "Type", "Summary", "Module"]

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(self.COLUMNS)

        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.doubleClicked.connect(self._on_double_click)
        layout.addWidget(self._table)

        self._results: list[SearchResult] = []

    def set_results(self, results: list[SearchResult]) -> None:
        self._results = results
        self._model.removeRows(0, self._model.rowCount())
        for r in results:
            row = [
                QStandardItem(r.timestamp.strftime("%Y-%m-%d %H:%M:%S")),
                QStandardItem(r.source),
                QStandardItem(r.type),
                QStandardItem(r.summary),
                QStandardItem(r.source),  # Module = source for now
            ]
            for item in row:
                item.setEditable(False)
            self._model.appendRow(row)

    def clear(self) -> None:
        self._model.removeRows(0, self._model.rowCount())
        self._results.clear()

    def _on_double_click(self, index):
        row = index.row()
        if 0 <= row < len(self._results):
            self.result_activated.emit(self._results[row])
```

- [ ] **Step 4: Write tests for FilterPanel**

Create `tests/test_filter_panel.py`:
```python
from ui.filter_panel import FilterPanel


def test_build_query_defaults():
    panel = FilterPanel()
    query = panel.build_query("test search")
    assert query.text == "test search"
    assert "Error" in query.types
    assert "Warning" in query.types
    assert query.regex_enabled is False


def test_build_query_with_regex():
    panel = FilterPanel()
    query = panel.build_query("error.*disk", regex=True)
    assert query.text == "error.*disk"
    assert query.regex_enabled is True


def test_build_query_sources_default_checked():
    panel = FilterPanel()
    query = panel.build_query("")
    assert "EventViewer" in query.sources
    assert "CBS" in query.sources
```

- [ ] **Step 5: Write tests for NotificationTray**

Create `tests/test_notification_tray.py`:
```python
from ui.notification_tray import NotificationTray, NotificationItem


def test_add_notification():
    tray = NotificationTray()
    item = NotificationItem(title="Test", message="Something happened", level="info")
    tray.add_notification(item)
    assert len(tray._notifications) == 1
    assert tray._notifications[0].title == "Test"


def test_clear_all():
    tray = NotificationTray()
    tray.add_notification(NotificationItem("A", "msg"))
    tray.add_notification(NotificationItem("B", "msg"))
    tray.clear_all()
    assert len(tray._notifications) == 0


def test_max_notifications():
    tray = NotificationTray()
    for i in range(60):
        tray.add_notification(NotificationItem(f"N{i}", "msg"))
    assert len(tray._notifications) == tray.MAX_VISIBLE
```

- [ ] **Step 6: Run UI tests**

Run: `cd src && python -m pytest ../tests/test_filter_panel.py ../tests/test_notification_tray.py -v`
Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add src/ui/search_bar.py src/ui/filter_panel.py src/ui/search_results.py tests/test_filter_panel.py tests/test_notification_tray.py
git commit -m "feat: add search bar, filter panel, and results table UI components"
```

---

## Task 16: Settings Dialog

**Files:**
- Create: `src/ui/settings_dialog.py`

- [ ] **Step 1: Implement settings_dialog.py**

Create `src/ui/settings_dialog.py`:
```python
import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Global and per-module settings dialog."""

    def __init__(self, app_instance, parent: QWidget = None):
        super().__init__(parent)
        self._app = app_instance
        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 400)

        layout = QVBoxLayout(self)

        # General settings
        general_group = QGroupBox("General")
        general_layout = QFormLayout(general_group)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "light"])
        self._theme_combo.setCurrentText(self._app.config.get("app.theme", "dark"))
        general_layout.addRow("Theme:", self._theme_combo)

        self._log_level_combo = QComboBox()
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level_combo.setCurrentText(
            self._app.config.get("app.log_level", "INFO")
        )
        general_layout.addRow("Log Level:", self._log_level_combo)

        self._start_minimized = QCheckBox()
        self._start_minimized.setChecked(
            self._app.config.get("app.start_minimized", False)
        )
        general_layout.addRow("Start Minimized:", self._start_minimized)

        self._admin_check = QCheckBox()
        self._admin_check.setChecked(
            self._app.config.get("app.check_admin_on_start", True)
        )
        general_layout.addRow("Check Admin on Start:", self._admin_check)

        layout.addWidget(general_group)

        # Module manager
        modules_group = QGroupBox("Modules")
        modules_layout = QVBoxLayout(modules_group)
        self._module_list = QListWidget()
        for mod in self._app.module_registry.modules:
            self._module_list.addItem(mod.name)
        modules_layout.addWidget(QLabel("Registered modules:"))
        modules_layout.addWidget(self._module_list)
        layout.addWidget(modules_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_and_close(self):
        self._app.config.set("app.theme", self._theme_combo.currentText())
        self._app.config.set("app.log_level", self._log_level_combo.currentText())
        self._app.config.set("app.start_minimized", self._start_minimized.isChecked())
        self._app.config.set(
            "app.check_admin_on_start", self._admin_check.isChecked()
        )
        self._app.theme.apply_theme(self._theme_combo.currentText())
        self._app.logger.set_level(self._log_level_combo.currentText())
        self._app.config.save()
        self.accept()
```

- [ ] **Step 2: Wire settings dialog into MainWindow**

In `src/ui/main_window.py`, update the `_open_settings` method:

Replace the placeholder:
```python
    def _open_settings(self):
        # Placeholder — implemented in Task 16
        logger.info("Settings dialog requested")
```
With:
```python
    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self._app, self)
        dialog.exec()
```

- [ ] **Step 3: Commit**

```bash
git add src/ui/settings_dialog.py src/ui/main_window.py
git commit -m "feat: add settings dialog with theme, log level, and module manager"
```

---

## Task 17: Updated Entry Point

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Rewrite main.py**

Replace `src/main.py` with:
```python
import logging
import sys
import os
import traceback

# Add src/ to Python path so imports like `core.event_bus` work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox

from app import App
from ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _global_exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler — logs traceback and shows error dialog."""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Unhandled exception:\n%s", tb_text)

    # Show non-fatal error dialog with Copy to Clipboard
    try:
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setWindowTitle("Unexpected Error")
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setText("An unexpected error occurred. The application may continue running.")
            msg.setDetailedText(tb_text)
            copy_btn = msg.addButton("Copy to Clipboard", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            msg.exec()
            if msg.clickedButton() == copy_btn:
                app.clipboard().setText(tb_text)
    except Exception:
        pass  # If dialog fails, at least the log was written


def main():
    qt_app = QApplication(sys.argv)

    # Initialize App singleton (wires all core services)
    app = App()

    # Install global exception handler (after logging is set up)
    sys.excepthook = _global_exception_handler

    # Start modules first (calls on_start before create_widget)
    app.start()

    # Create and show main window
    window = MainWindow(app)

    # Add module tabs (after on_start so modules have app reference)
    for module in app.module_registry.modules:
        enabled = module not in app.module_registry.disabled_modules
        window.add_module_tab(module, enabled=enabled)

    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the app launches**

Run: `cd src && python main.py`
Expected: Window opens with title "Windows 11 Tweaker & Optimizer", dark theme, empty tab widget, toolbar, status bar. No errors in console.

- [ ] **Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: update entry point to wire App, MainWindow, and module lifecycle"
```

---

## Task 18: Integration Test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/test_integration.py`:
```python
import os
import sys
import tempfile
import pytest
from unittest.mock import patch
from PyQt6.QtWidgets import QLabel

# Ensure src/ is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

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
    from unittest.mock import MagicMock

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
```

- [ ] **Step 2: Run all tests**

Run: `cd src && python -m pytest ../tests/ -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration test for full module lifecycle and core services"
```

---

## Task 19: Wire Search into MainWindow

**Files:**
- Modify: `src/ui/main_window.py`

- [ ] **Step 1: Add search components to MainWindow**

In `src/ui/main_window.py`, add the search bar, filter panel, and results table to the layout. Update imports and `__init__`:

Add these imports at top:
```python
from ui.search_bar import SearchBar
from ui.filter_panel import FilterPanel
from ui.search_results import SearchResultsTable
```

In `__init__`, after the admin banner and before the tab widget, add:
```python
        # Search bar
        self._search_bar = SearchBar(self)
        self._search_bar.search_requested.connect(self._on_search)
        self._search_bar.filter_toggled.connect(self._on_filter_toggled)
        self._toolbar.addWidget(self._search_bar)

        # Filter panel (hidden by default)
        self._filter_panel = FilterPanel(self)
        self._layout.addWidget(self._filter_panel)

        # Search results (hidden by default)
        self._search_results = SearchResultsTable(self)
        self._search_results.setVisible(False)
        self._layout.addWidget(self._search_results)
```

Add search shortcut wiring in `_setup_shortcuts`:
```python
        # Ctrl+F focus search
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self._search_bar.focus_search
        )
        # Ctrl+Shift+F focus search with filters
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(
            self._search_bar.focus_search_with_filters
        )
        # Escape clears search
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._clear_search)
```

Add handler methods:
```python
    def _on_search(self, text: str, regex: bool):
        if not text.strip():
            self._search_results.setVisible(False)
            return
        query = self._filter_panel.build_query(text, regex)
        results = self._app.search.execute(query)
        self._search_results.set_results(results)
        self._search_results.setVisible(True)

    def _on_filter_toggled(self, expanded: bool):
        self._filter_panel.setVisible(expanded)

    def _clear_search(self):
        self._search_bar.clear()
        self._search_results.setVisible(False)
        self._filter_panel.setVisible(False)
```

- [ ] **Step 2: Commit**

```bash
git add src/ui/main_window.py
git commit -m "feat: wire search bar, filter panel, and results table into MainWindow"
```

---

## Task 20: Final Cleanup & Run

- [ ] **Step 1: Delete old pycache**

```bash
rm -rf src/__pycache__
```

- [ ] **Step 2: Update core/__init__.py with re-exports**

Create `src/core/__init__.py`:
```python
from core.event_bus import EventBus
from core.config_manager import ConfigManager
from core.search_engine import SearchEngine
from core.base_module import BaseModule
from core.worker import Worker, WorkerSignals
from core.logging_service import LoggingService
from core.theme_manager import ThemeManager
from core.module_registry import ModuleRegistry

__all__ = [
    "EventBus",
    "ConfigManager",
    "SearchEngine",
    "BaseModule",
    "Worker",
    "WorkerSignals",
    "LoggingService",
    "ThemeManager",
    "ModuleRegistry",
]
```

- [ ] **Step 3: Run the full test suite**

Run: `cd src && python -m pytest ../tests/ -v --tb=short`
Expected: All tests PASS

- [ ] **Step 4: Launch the app manually**

Run: `cd src && python main.py`
Expected: App launches with dark theme, empty tabs, search bar in toolbar, status bar showing "User" or "Admin", no errors.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup, core re-exports, delete stale pycache"
```
