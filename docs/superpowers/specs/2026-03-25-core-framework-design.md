# Core Framework & GUI Shell — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** #1 — Core Framework & GUI Shell
**Date:** 2026-03-25
**Status:** In Review

---

## Context

### Product Overview

A desktop application for IT professionals and sysadmins that provides Windows system diagnostics, real-time process monitoring, and AI-driven optimization recommendations. The tool aims for Sysinternals-level depth with the added value of an integrated AI assistant powered by Ollama.

### Sub-project Decomposition

The full product is decomposed into 4 sub-projects, each with its own design-plan-build cycle:

1. **Core Framework & GUI Shell** (this spec) — App skeleton, tabbed layout, settings, module system, global search
2. **Data Collection & Analysis** — Event Viewer, CBS, DISM, Windows Update, Reliability Monitor, crash dumps, PerfMon counters, historical graphing, alerting
3. **Process Explorer** — Sysinternals-level process/thread/DLL/handle/network/GPU/IO view with VirusTotal integration
4. **AI & Learning System** — Ollama integration (local + remote), diagnostics recommendations, per-machine history, outcome tracking, central sync, feedback loop

### Target Users

IT professionals and sysadmins managing Windows machines. They expect depth, power, and efficiency over hand-holding.

### Technology Choice

- **Framework:** PyQt6
- **Language:** Python
- **Rationale:** PyQt6 excels at complex, data-heavy desktop apps. Fast table/tree rendering for thousands of processes, native Windows integration, direct access to system APIs via ctypes/psutil. Mature ecosystem, well-documented.

---

## Section 1: Architecture Overview

The application follows a modular host architecture. The shell provides the window, tabs, toolbar, and core services. Modules plug into the shell to provide functionality.

```
+---------------------------------------------+
|              MainWindow (Shell)              |
|  +---------+----------+----------+--------+ |
|  | Toolbar  |  Menu Bar |  Status Bar      | |
|  +---------+----------+----------+--------+ |
|  |              Tab Container              | |
|  |  +----------------------------------+   | |
|  |  |   Module Widget (one per tab)    |   | |
|  |  +----------------------------------+   | |
|  +----------------------------------------+ |
|  |          Notification Tray              | |
|  +----------------------------------------+ |
+---------------------------------------------+
|              Core Services                   |
|  ConfigManager | ModuleRegistry | EventBus   |
|  LoggingService | ThemeManager | SearchEngine |
+---------------------------------------------+
```

### Key Components

- **MainWindow** — The shell that hosts tabs, toolbar, menus, and status bar
- **ModuleRegistry** — Discovers and manages module lifecycle (init, start, stop, configure)
- **EventBus** — Lightweight pub/sub so modules communicate without direct coupling
- **ConfigManager** — Centralized settings with per-module config sections, stored as JSON
- **LoggingService** — Internal app logging (not Windows log parsing)
- **ThemeManager** — Dark/light theme support
- **SearchEngine** — Global search across all modules with filtering

### Service Container (App Singleton)

All core services are accessed through the `App` singleton. This is the single dependency injection point for the entire application. Modules receive the `App` instance in their lifecycle methods.

```python
class App:
    """Singleton that owns all core services. Created once in main.py."""
    instance: ClassVar[Optional['App']] = None

    event_bus: EventBus
    config: ConfigManager
    search: SearchEngine
    theme: ThemeManager
    logger: LoggingService
    module_registry: ModuleRegistry
    thread_pool: QThreadPool

    @classmethod
    def get(cls) -> 'App':
        """Access the singleton. Only use when constructor injection is not possible."""
        assert cls.instance is not None, "App not initialized"
        return cls.instance
```

Modules receive the `App` instance via `on_start(app)` (see Section 2). Direct use of `App.get()` is discouraged — it exists only for cases where constructor injection is impractical (e.g., deep utility functions).

---

## Section 2: Module System

An internal module system using abstract base classes. Modules are built into the app but loosely coupled via well-defined interfaces. No dynamic plugin discovery — modules are registered explicitly in a known list.

### BaseModule ABC

```python
class BaseModule(ABC):
    name: str                    # "Data Collection", "Process Explorer", etc.
    icon: str                    # Path to icon for the tab
    description: str             # Shown in module manager
    requires_admin: bool         # Whether this module needs elevated privileges
    app: 'App'                   # Set by ModuleRegistry before on_start()

    @abstractmethod
    def create_widget(self) -> QWidget:
        """Return the main widget for this module's tab."""

    @abstractmethod
    def on_activate(self) -> None:
        """Called when this module's tab is selected."""

    @abstractmethod
    def on_deactivate(self) -> None:
        """Called when this module's tab loses focus."""

    @abstractmethod
    def on_start(self, app: 'App') -> None:
        """Called at app startup. Use app.event_bus, app.config, app.search, etc.
        Store app reference: self.app = app"""

    @abstractmethod
    def on_stop(self) -> None:
        """Called at app shutdown."""

    def get_config_schema(self) -> dict:
        """Return JSON schema for this module's settings."""
        return {}

    def get_toolbar_actions(self) -> list:
        """Actions added to toolbar when this module is active."""
        return []

    def get_menu_actions(self) -> list:
        """Actions added to menu bar."""
        return []

    def get_status_info(self) -> str:
        """Text shown in status bar when this module is active."""
        return ""

    def get_search_provider(self) -> Optional['SearchProvider']:
        """Return a SearchProvider if this module supports global search.
        ModuleRegistry auto-registers it with the SearchEngine."""
        return None
```

### ModuleRegistry

- Imports modules from a known list in config
- Calls lifecycle hooks in order: register -> on_start -> (on_activate/on_deactivate) -> on_stop
- Checks `requires_admin` and gracefully disables modules that need elevation when running without it (grayed out tab with tooltip)
- Exposes a "Module Manager" settings panel where modules can be enabled/disabled
- If a module throws during `on_start()`, it gets disabled with an error badge; other modules keep running

### Rationale

No dynamic plugin discovery. Modules are registered explicitly in a `MODULES` list. This avoids the complexity of folder scanning, version conflicts, and security concerns of arbitrary code loading. Adding a module = adding one line to the registry.

---

## Section 3: Event Bus

A lightweight in-process pub/sub system so modules communicate without importing each other.

### API

```python
class EventBus:
    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register a callback for an event type."""

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Remove a callback registration."""

    def publish(self, event_type: str, data: dict) -> None:
        """Publish an event synchronously (same thread)."""

    def publish_async(self, event_type: str, data: dict) -> None:
        """Publish an event marshaled to the main thread via QMetaObject.invokeMethod."""
```

### Example Event Flow

1. Data Collection module parses Event Viewer -> publishes `"log.errors_found"` with error details
2. AI module subscribes to `"log.errors_found"` -> generates recommendations
3. AI module publishes `"ai.recommendation_ready"` -> notification tray shows alert
4. Learning system subscribes to `"ai.recommendation_applied"` -> tracks outcome

### Event Types

Event types are string constants defined in a shared `events.py` file, alongside dataclass definitions for each event's payload. This gives a single place to see all inter-module communication and provides type safety:

```python
# events.py
from dataclasses import dataclass
from datetime import datetime
from typing import List

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

Publishers construct the appropriate dataclass; subscribers receive it as the `data` parameter. This catches schema mismatches early and provides IDE autocomplete.

### Error Isolation

The EventBus catches exceptions per-subscriber, logs them via LoggingService, and continues notifying remaining subscribers. A buggy subscriber never breaks the event pipeline or prevents other subscribers from being notified.

### Threading

- `publish()` is synchronous (same thread), with per-subscriber try/except
- `publish_async()` uses `QMetaObject.invokeMethod` to safely marshal events to the main thread — critical since data collection and process monitoring run on background threads

---

## Section 4: Config Manager

### API

```python
class ConfigManager:
    def get(self, key: str, default=None) -> Any:
        """Get a value using dot-notation: 'modules.ai.ollama_url'"""

    def set(self, key: str, value: Any) -> None:
        """Set a value and emit a config change event."""

    def get_module_config(self, module_name: str) -> dict:
        """Get the full config dict for a module."""

    def save(self) -> None:
        """Persist config to disk."""

    def reset_to_defaults(self) -> None:
        """Reset all settings to defaults."""
```

### Storage

Single `config.json` file in `%APPDATA%/WindowsTweaker/`:

```json
{
  "version": 1,
  "app": {
    "theme": "dark",
    "window_size": [1400, 900],
    "start_minimized": false,
    "check_admin_on_start": true
  },
  "modules": {
    "enabled": ["data_collection", "process_explorer", "ai_learning"],
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

### Versioning & Migration

The config file includes a `"version"` field (starting at 1). On load, ConfigManager checks the version and runs migration functions sequentially if the file is outdated (e.g., v1->v2, v2->v3). Migrations are defined as a list of `(from_version, migration_fn)` tuples in `config_manager.py`.

### Persistence Safety

- **Atomic writes:** `save()` writes to a temporary file (`config.json.tmp`) in the same directory, then renames it over the original. This prevents corruption if the app crashes mid-write.
- **Auto-save:** Debounced save 2 seconds after the last `set()` call. Also saves on clean shutdown via `on_stop()`.
- **Corruption recovery:** On load, if `config.json` is invalid JSON, fall back to `config.json.bak` (the previous good version). If both are corrupt, reset to defaults and show a warning notification to the user.
- **Backup:** Before each save, copy the current `config.json` to `config.json.bak`.

### Rationale

JSON over YAML or TOML. IT pros can hand-edit it if needed, and Python's `json` module has no dependencies. Config changes emit events on the EventBus (using `ConfigChangedData`) so modules can react to live setting changes.

---

## Section 5: Project Structure

```
Windows_client_tool/
├── src/
│   ├── main.py                     # Entry point
│   ├── app.py                      # QApplication setup, singleton services
│   ├── core/
│   │   ├── __init__.py
│   │   ├── base_module.py          # BaseModule ABC
│   │   ├── module_registry.py      # Module lifecycle management
│   │   ├── event_bus.py            # Pub/sub system
│   │   ├── config_manager.py       # Settings management
│   │   ├── logging_service.py      # Internal app logging
│   │   ├── theme_manager.py        # Dark/light theme
│   │   ├── events.py               # Event type constants
│   │   ├── admin_utils.py          # UAC elevation checks
│   │   ├── search_engine.py        # SearchEngine, SearchQuery, SearchResult
│   │   ├── search_provider.py      # SearchProvider ABC, FilterField
│   │   ├── types.py                # Shared data models (LogEntry, ProcessInfo, etc.)
│   │   └── worker.py               # Worker, WorkerSignals base classes
│   ├── ui/
│   │   ├── __init__.py
│   │   ├── main_window.py          # Shell window with tabs
│   │   ├── toolbar.py              # Dynamic toolbar
│   │   ├── status_bar.py           # Status bar with module info
│   │   ├── notification_tray.py    # In-app notification area
│   │   ├── settings_dialog.py      # Global + per-module settings
│   │   ├── search_bar.py           # Global search bar widget
│   │   ├── filter_panel.py         # Expandable filter panel
│   │   ├── search_results.py       # Results table with grouping/sorting
│   │   └── styles/
│   │       ├── dark.qss            # Dark theme stylesheet
│   │       └── light.qss           # Light theme stylesheet
│   └── modules/
│       ├── __init__.py
│       ├── data_collection/        # Sub-project #2 (future)
│       ├── process_explorer/       # Sub-project #3 (future)
│       └── ai_learning/            # Sub-project #4 (future)
├── tests/
│   ├── test_event_bus.py
│   ├── test_config_manager.py
│   ├── test_module_registry.py
│   └── test_search_engine.py
├── docs/
│   └── superpowers/
│       └── specs/
├── config/
│   └── default_config.json         # Default settings shipped with app
├── requirements.txt
└── README.md
```

### Rationale

Flat `core/` for framework services, `ui/` for all shell UI components, `modules/` as the home for each sub-project. Each module gets its own directory so it can have internal structure without polluting the root. Tests mirror the source structure.

---

## Section 6: Threading Model

The app has heavy background work (log parsing, process enumeration, AI inference).

### Approach

- **QThreadPool + QRunnable** for short-lived tasks (parsing a log file, querying VirusTotal)
- **Dedicated QThread subclasses** for long-running monitors (process list refresh, PerfMon counter collection)
- **Signals/slots** for thread-to-UI communication (never touch widgets from background threads)
- **EventBus.publish_async()** marshals cross-module events to the main thread

### Worker Pattern

```python
class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    cancelled = pyqtSignal()

class Worker(QRunnable):
    """Wraps any callable for thread pool execution.
    Emits signals for result/error/progress/cancelled."""

    def cancel(self) -> None:
        """Request cancellation. The worker's callable must check is_cancelled()."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancelled
```

Each module that needs background work creates Workers and submits them to the shared thread pool (`app.thread_pool`). The core framework provides the Worker base class and the pool.

### Cancellation Contract

Workers must cooperate with cancellation by checking `self.is_cancelled()` at reasonable intervals inside their work loop. When cancelled:
1. The worker stops as soon as practical
2. Emits the `cancelled` signal (not `result` or `error`)
3. Cleans up any partial state

Modules can cancel all their workers via a `cancel_all()` helper, and the ModuleRegistry calls this automatically during `on_stop()`.

---

## Section 6b: Logging Service

Wraps Python's built-in `logging` module with app-specific configuration.

### API

Modules obtain a logger via Python's standard mechanism:

```python
import logging
logger = logging.getLogger("module.data_collection")
logger.info("Parsed 1,234 events from System log")
```

The `LoggingService` configures the root logger at startup — modules do not configure logging themselves.

### Configuration

- **Log file location:** `%APPDATA%/WindowsTweaker/logs/app.log`
- **Rotation:** `RotatingFileHandler` — 5 MB per file, 5 backup files (25 MB total max)
- **Console output:** Also logs to stderr at DEBUG level during development
- **Format:** `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- **Default level:** INFO (configurable via `config.json` at `"app.log_level"`)

### Log Levels by Convention

- **DEBUG** — Verbose internal state (event bus dispatches, config reads)
- **INFO** — Normal operations (module started, log file parsed, search executed)
- **WARNING** — Recoverable issues (module failed to start, config corrupted and fell back to backup)
- **ERROR** — Failures that affect functionality (unhandled exception in module, Ollama connection failed)
- **CRITICAL** — App-level failures (cannot create config directory, Qt initialization failed)

---

## Section 7: Error Handling & Admin Elevation

### UAC Check

- Detect if running as admin at startup
- If not, show a persistent banner: "Some features require administrator privileges. [Restart as Admin]"
- Modules with `requires_admin = True` are visible but grayed out with a tooltip explaining why
- "Restart as Admin" button uses `ShellExecuteW` with `runas` verb to relaunch elevated

### Global Exception Handler

- Catch unhandled exceptions via `sys.excepthook`
- Log the full traceback
- Show a non-fatal error dialog with "Copy to Clipboard" for bug reports
- The app should never silently crash

### Per-Module Isolation

- If a module throws during `on_start()`, it gets disabled with an error badge on its tab
- Other modules keep running
- Module errors are logged and shown in the notification tray

---

## Section 7b: Keyboard Shortcuts

IT professionals expect keyboard-driven workflows. The core framework defines these global shortcuts:

| Shortcut | Action |
|----------|--------|
| `Ctrl+F` | Focus the global search bar |
| `Ctrl+Shift+F` | Focus search bar and expand filter panel |
| `Escape` | Close filter panel / clear search / return focus to active module |
| `Ctrl+Tab` | Next module tab |
| `Ctrl+Shift+Tab` | Previous module tab |
| `Ctrl+1..9` | Switch directly to module tab 1-9 |
| `Ctrl+,` | Open Settings dialog |
| `F5` | Refresh active module's data |
| `Ctrl+E` | Export current view (context-dependent per module) |
| `Ctrl+Shift+C` | Copy selected rows/data to clipboard |

Modules can register additional shortcuts via `get_toolbar_actions()` and `get_menu_actions()`. Shortcuts are shown in tooltips and menu items. All shortcuts are configurable via the Settings dialog (stored in `config.json` under `"app.shortcuts"`).

---

## Section 8: Global Search & Filter System

A unified search bar that queries across all modules with powerful filtering.

### UI Layout

Persistent search bar in the toolbar area, always visible. Expanding it reveals the filter panel.

```
+------------------------------------------------------+
|  [Search all logs, events, recommendations...]       |
|  +------------------------------------------------+  |
|  | Filters:                                       |  |
|  |  Date: [From] -> [To]    Time: [From] -> [To] |  |
|  |  Type: [x]Error [x]Warning [ ]Info [ ]Debug    |  |
|  |  Source: [x]EventViewer [x]CBS [x]AI [x]PerfMon|  |
|  |  Severity: [Any]  Module: [All]                |  |
|  |  [Save Filter Preset] [Clear All]              |  |
|  +------------------------------------------------+  |
+------------------------------------------------------+
|  Results (grouped by source, sortable columns):      |
|  +------+-------+--------+-----------+-----------+  |
|  | Time | Source|  Type  |  Summary  |  Module   |  |
|  +------+-------+--------+-----------+-----------+  |
|  | ...  | ...   |  ...   |  ...      |  ...      |  |
|  +------+-------+--------+-----------+-----------+  |
+------------------------------------------------------+
```

### SearchProvider ABC

Each module implements this to make its data searchable:

```python
class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: SearchQuery) -> List[SearchResult]:
        """Return matching results for the given query."""

    @abstractmethod
    def get_filterable_fields(self) -> List[FilterField]:
        """Declare what filters this provider supports."""
```

### SearchQuery

```python
class SearchQuery:
    text: str                          # Free-text search string
    date_from: Optional[datetime]
    date_to: Optional[datetime]
    time_from: Optional[time]
    time_to: Optional[time]
    types: List[str]                   # Error, Warning, Info, etc.
    sources: List[str]                 # EventViewer, CBS, AI, etc.
    severity: Optional[str]
    module: Optional[str]
    regex_enabled: bool                # IT pros will want regex
```

### SearchResult

```python
class SearchResult:
    timestamp: datetime
    source: str                        # Which module/provider
    type: str                          # Error, Warning, Recommendation, etc.
    summary: str                       # One-line preview
    detail: Any                        # Full object for drill-down
    relevance: float                   # For ranking results
```

### SearchEngine

```python
class SearchEngine:
    providers: List[SearchProvider]

    def register_provider(self, provider: SearchProvider) -> None
    def execute(self, query: SearchQuery) -> List[SearchResult]
    def save_preset(self, name: str, query: SearchQuery) -> None
    def load_preset(self, name: str) -> SearchQuery
    def get_all_presets(self) -> List[str]
```

### Features

- **Regex support** — Toggle for regex search
- **Filter presets** — Save and recall common filter combinations (e.g., "Last 24h Errors Only", "BSOD events this week")
- **Live filtering** — Results update as you type / change filters (debounced at 300ms)
- **Cross-module results** — Results grouped by source in one unified table, sortable by any column
- **Drill-down** — Click a result to jump to it in its source module's tab, highlighted in context
- **Export** — Selected results can be exported to CSV/JSON for reporting

### Integration

- `SearchEngine` lives in `core/` as a core service
- Each module registers a `SearchProvider` during `on_start()`
- Search bar and filter panel live in `ui/`
- Filter presets stored in `config.json` under `"search": { "presets": {...} }`

---

## Testing Strategy

Unit tests for all core services:

- **EventBus** — Subscribe, publish, unsubscribe, async publish, multiple subscribers
- **ConfigManager** — Get/set with dot-notation, save/load, defaults, module config isolation
- **ModuleRegistry** — Lifecycle ordering, admin check disabling, error isolation
- **SearchEngine** — Multi-provider query, filtering, preset save/load, empty results

Integration test:

- **Full app startup** — Register mock modules, verify tabs appear, lifecycle hooks called in order, search bar functional

---

## Dependencies

Core framework dependencies only:

```
PyQt6>=6.6
psutil>=5.9
```

Sub-project dependencies (installed but used by their respective modules):
- `requests>=2.31` — Used by Process Explorer (VirusTotal) and AI & Learning (Ollama HTTP API)
- `python-llama` — Deferred to Sub-project #4 (AI & Learning System)

---

## Project Structure Addendum

### Shared Types

A `core/types.py` file provides shared data models used across module boundaries:

```python
# core/types.py — shared types for cross-module data
@dataclass
class LogEntry:
    timestamp: datetime
    source: str
    level: str          # Error, Warning, Info, Debug
    message: str
    raw: dict           # Original data from source

@dataclass
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_bytes: int
    # Extended in Sub-project #3

@dataclass
class Recommendation:
    id: str
    summary: str
    details: str
    confidence: float
    source_entries: List[LogEntry]
```

These are defined as minimal stubs in Sub-project #1 and extended by later sub-projects.

### System Tray

The app supports minimize-to-system-tray behavior via `QSystemTrayIcon`. The tray icon shows:
- A badge count for unread notifications/recommendations
- Right-click menu: Show/Hide, Settings, Exit
- Balloon notifications for high-priority events (e.g., critical errors found)

System tray behavior is configurable (can be disabled in settings).

### Migration from Existing Code

The existing `src/gui.py` and `src/log_reader.py` are placeholder files that will be replaced (not extended) by the new structure. `gui.py` is superseded by `ui/main_window.py`. `log_reader.py` is superseded by the Data Collection module in Sub-project #2.

### Packaging

Intended distribution is a single-folder PyInstaller build (not single-file, to allow QSS theme files and config templates to be accessible). An MSI wrapper can be added later for enterprise deployment. All file paths use relative references from the app root to support this model.

---

## What This Spec Does NOT Cover

The following are deferred to their respective sub-project specs:

- Windows log parsing implementation (Sub-project #2)
- PerfMon counter collection and graphing (Sub-project #2)
- Process enumeration, thread/DLL/handle inspection (Sub-project #3)
- Ollama integration and AI recommendation logic (Sub-project #4)
- Learning system database schema and sync protocol (Sub-project #4)
