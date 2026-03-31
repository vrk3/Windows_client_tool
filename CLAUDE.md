# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Windows desktop optimization and diagnostics utility — a PyQt6 GUI application with 40+ plugin modules. Targets Windows 10/11 (64-bit), Python 3.12+.

## Development Commands

**Activate environment** (always needed before running or building):
```
.venv\Scripts\activate
```

**Run from source** (from project root):
```
python src/main.py
```

**Install dependencies**:
```
pip install -r requirements.txt
```

**Build — folder/onedir version** (output: `dist/WinClientTool/`):
```
pyinstaller WinClientTool.spec -y --distpath dist
```

**Build — portable onefile version** (output: `dist/WinClientTool-Portable.exe`):
```
pyinstaller WinClientTool-portable.spec -y --distpath dist
```

For a clean rebuild of the portable, delete the cached PKG first:
```
rm -f build/WinClientTool-portable/PYZ-00.toc build/WinClientTool-portable/PKG-00.toc
pyinstaller WinClientTool-portable.spec -y --distpath dist
```
The portable spec must include `a.binaries` and `a.datas` in the EXE constructor — without these, the output is a ~3MB bootloader stub.

**Syntax check** (without running):
```
python -c "import sys; sys.path.insert(0, 'src'); import main"
```

## Architecture

### App Singleton (`src/app.py`)
The `App` class owns all core services as a singleton: `event_bus`, `config`, `logger`, `backup`, `theme`, `search`, `module_registry`, `thread_pool`. Created once in `main.py`, accessed elsewhere via `App.get()`.

**Resource paths**: Two separate resource trees exist:
- `config/` — at project root (accessed via `_get_resource_dir() + "config"`)
- `ui/styles/` and `modules/tweaks/definitions/` — under `src/` (styles uses an explicit `os.path.join(os.path.dirname(__file__), "ui", "styles")` path)

### Module Plugin System (`src/core/base_module.py`)
Every UI feature is a `BaseModule` subclass. Key lifecycle order:
1. `__init__()` — module instance created during registration
2. `module_registry.start_all()` → `on_start(app)` — called before `create_widget`; store `app` reference here only
3. `window.register_module()` → `create_widget()` — creates the QWidget; called once
4. User selects module → `on_activate()` — called every time the user navigates to the module
5. User leaves module → `on_deactivate()` — stop timers, release resources here
6. App shutdown → `on_stop()` — `cancel_all_workers()` is called automatically

**Critical**: `on_start` runs BEFORE `create_widget`. Do NOT access `_widget`, `_table`, or any UI elements in `on_start`. Only store the `app` reference.

Each module declares:
- `name`, `icon`, `description` — displayed in sidebar
- `group` — one of `ModuleGroup.OVERVIEW/DIAGNOSE/SYSTEM/MANAGE/OPTIMIZE/TOOLS/PROCESS`
- `requires_admin` — if True, module is disabled when not running elevated
- `get_search_provider()` — returns a `SearchProvider` for cross-module search
- `get_refresh_interval()` — return milliseconds for auto-refresh (or None to disable)

### DiagnoseModule — Hub Pattern (`src/modules/diagnose/diagnose_module.py`)
The `DiagnoseModule` is a special "hub" that embeds multiple diagnostic viewers as sub-tabs inside itself:
- Event Viewer, CBS Log, DISM Log, Windows Update, Reliability, Crash Dumps
- These 6 modules are NOT registered as standalone sidebar entries — they exist only within the hub
- The hub uses its own `QTabWidget`, lazy-loads each tab on first switch, and provides a unified search bar across all providers
- The standalone module files (`event_viewer_module.py`, `cbs_module.py`, etc.) exist but are not registered in `main.py`

### Sidebar Navigation (`src/ui/main_window.py`)
`SidebarNav.select(name)` only highlights the sidebar button — it does NOT emit `module_selected` or load the module. Always use `MainWindow._navigate_to_module(name)` which calls both `sidebar.select()` AND `_on_module_selected()`.

```python
# Correct — navigates and loads the module:
window._navigate_to_module("Services")

# Wrong — only highlights the button:
self._sidebar.select("Services")
```

### Background Workers (`src/core/worker.py`)
Use the `Worker` class for all background tasks. The worker function receives a `worker` parameter and emits results via signals:

```python
def do_work(worker):
    for item in items:
        if worker.is_cancelled:  # property, NOT a method
            return
        # ... work ...
        worker.signals.progress.emit(int(progress_pct))
    return result  # returned value goes to signals.result

w = Worker(do_work)
w.signals.result.connect(self._on_done)
w.signals.error.connect(self._on_error)
self._workers.append(w)        # track for cancel_all_workers()
self.app.thread_pool.start(w)
```

Always track workers in `self._workers` and call `worker.signals.progress.emit()` from within the worker function (not from outside).

### Widget Lifetime Guards
When a worker fires after its host widget has been deleted (e.g., user switched tabs), Qt objects accessed in the result callback may be invalid. Guard with `sip.isdeleted()`:

```python
try:
    import sip as sip
    _widget_is_valid = lambda w: not sip.isdeleted(w)
except ImportError:
    _widget_is_valid = lambda w: True  # fallback

def set_entries(self, entries):
    if not _widget_is_valid(self._status):
        return
    # ... normal work ...
```

This applies to `LogTableWidget.set_entries()`, `append_entries()`, and `clear()`.

### Search System (`src/core/search_engine.py`, `src/core/search_provider.py`)
Modules return a `SearchProvider` subclass from `get_search_provider()`. The engine aggregates results from all providers and sorts by relevance. Query filter: set `query.sources` to limit to specific modules.

### Event Bus (`src/core/event_bus.py`)
Pub/sub for loose coupling between modules. Use `app.event_bus.publish("topic", data)` and `subscribe("topic", handler)`. Available topics include module selection, theme changes, cleanup completions.

### Tweak System (`src/modules/tweaks/`)
JSON definition files in `src/modules/tweaks/definitions/` define registry/script tweaks. Each entry has `steps[]` with `type: "registry"` (key, data, kind) or `type: "powershell"`. `tweak_engine.py` applies and reverts them. App catalog (`app_catalog.json`) detects installed apps. Restore points created automatically before applying tweaks.

### Cleanup Scanner Pattern (`src/modules/cleanup/cleanup_scanner.py`)
Scanner functions return `List[ScanItem]` with `path`, `name`, `size`, `safety` ("safe"/"caution"/"danger"). `ScanResult` holds the list. The cleanup module wraps scanners in `_ScanTab` with grouped tree view and age filtering.

### UI Patterns

**Dark theme** — all modules use `#2d2d2d` backgrounds, `#3c3c3c` cards, `#e0e0e0` text. QSS styles are in `src/ui/styles/dark.qss`.

**Error handling** — show errors in-module via `ErrorBanner` widget (`src/ui/error_banner.py`) or `QMessageBox`, not just logs.

**Loading/empty states** — wrap content in `QStackedWidget`; page 0 = content, page 1 = centered "No data — click Refresh" label.

**Confirmation dialogs** — always confirm destructive actions (delete, stop service, disable startup item, toggle Windows features).

**Admin-gated modules** — `requires_admin = True` on the module class. `ModuleRegistry.start_all()` checks `is_admin()` and disables the module if not elevated.

## PyInstaller Build Notes

Two spec files:
- `WinClientTool.spec` — onedir/folder build
- `WinClientTool-portable.spec` — onefile/portable build

Data files bundled: `config/` (at project root), `src/ui/styles/` (→ `ui/styles`), `src/modules/tweaks/definitions/` (→ `modules/tweaks/definitions`). Hidden imports cover PyQt6, pywin32, PIL, requests.

When adding new modules, import and register in `src/main.py`:
```python
from modules.<name>.<module_name>_module import MyModule
app.module_registry.register(MyModule())
```
Note: EventViewer, CBS, DISM, WU, Reliability, and CrashDumps are embedded in DiagnoseModule — do NOT register them as standalone modules.

## Important Gotchas

- `sys.stdout` is `None` in onefile windowed mode — always guard `sys.stdout.isatty()` with `hasattr(sys.stdout, 'isatty')`
- `tempfile` module must be explicitly imported — PyInstaller may miss it
- The walrus operator `:=` inside PyQt `addRow()` calls causes Python 3.12 parser failures — avoid it, use separate assignment lines
- `win32serviceutil` (pywin32) requires `pythoncom.CoInitialize()` before use in worker threads; use `COMWorker` instead of `Worker` for WMI/COM operations
- Do NOT call UI-creating methods (`_load_data()`, `_setup_table()`) from `on_start` — use `on_activate` instead since `on_start` runs before `create_widget`
- CBS.log and DISM.log use a regex pattern that matches a specific format — if logs are empty, the log files may use a different format or be UTF-16 encoded (the base parser handles this but the per-line regex may not match all lines)
