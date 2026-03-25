# Core Framework & GUI Shell — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** #1 — Core Framework & GUI Shell
**Date:** 2026-03-25
**Status:** Approved

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
    def on_start(self) -> None:
        """Called at app startup after all modules are registered."""

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

Event types are string constants defined in a shared `events.py` file. This gives a single place to see all inter-module communication.

### Threading

- `publish()` is synchronous (same thread)
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

### Rationale

JSON over YAML or TOML. IT pros can hand-edit it if needed, and Python's `json` module has no dependencies. Config changes emit events on the EventBus so modules can react to live setting changes.

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
│   │   └── search_provider.py      # SearchProvider ABC, FilterField
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

class Worker(QRunnable):
    """Wraps any callable for thread pool execution.
    Emits signals for result/error/progress."""
```

Each module that needs background work creates Workers and submits them to the shared thread pool. The core framework provides the Worker base class and the pool.

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

```
PyQt6>=6.6
psutil>=5.9
requests>=2.31
```

`python-llama` from the original requirements.txt is deferred to Sub-project #4 (AI & Learning System).

---

## What This Spec Does NOT Cover

The following are deferred to their respective sub-project specs:

- Windows log parsing implementation (Sub-project #2)
- PerfMon counter collection and graphing (Sub-project #2)
- Process enumeration, thread/DLL/handle inspection (Sub-project #3)
- Ollama integration and AI recommendation logic (Sub-project #4)
- Learning system database schema and sync protocol (Sub-project #4)
