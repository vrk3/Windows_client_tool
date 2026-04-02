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

Two resource-path helpers handle PyInstaller's `_MEIPASS` layout:
- `_get_resource_dir()` — base directory for bundled config/ and data files; returns `sys._MEIPASS` in a onefile build, or the project root in source mode
- `_get_app_data_dir()` — `%APPDATA%/WindowsTweaker` for user-persisted config and logs

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
self._workers.append(w)
self.app.thread_pool.start(w)
```

`worker.is_cancelled` is a `@property` (no parentheses), NOT a method. Always track workers in `self._workers`.

**Cancellation**: Use `worker.cancel()` — do NOT directly assign `worker._cancelled = True`. The `cancel()` method uses a `Lock` to safely set the flag; bypassing it risks race conditions. This applies in `_cancel_all()` methods too:

```python
def _cancel_all(self) -> None:
    for w in self._workers:
        w.cancel()       # safe — uses Lock
        # NOT: w._cancelled = True
    self._workers.clear()
```

For WMI/COM operations use `COMWorker` (calls `pythoncom.CoInitialize()` automatically) instead of plain `Worker`.

**First-load guard pattern** — trigger data load on first `on_activate()`, not in `create_widget()`:

```python
def __init__(self):
    super().__init__()
    self._loaded = False

def on_activate(self):
    if not self._loaded:
        self._loaded = True
        self._load_data()
```

**Cross-thread widget access — CRITICAL**: Never call Qt widget methods directly from a worker thread. The SFC scan crash was caused by `self._output.appendPlainText(line)` inside a closure passed to a background action function. The fix: use a `pyqtSignal` on the widget class to marshal output to the main thread:

```python
class _FixCard(QFrame):
    _line = pyqtSignal(str)   # class-level signal

    def _setup_ui(self):
        ...
        self._line.connect(self._output.appendPlainText)

    def _run(self):
        def append(line: str):
            self._line.emit(line)   # safe from any thread
        ...
```

### Widget Lifetime Guards

When a worker fires after its host widget has been deleted (e.g., user switched tabs), Qt objects accessed in the result callback may be invalid. Guard with `sip.isdeleted()`:

```python
try:
    import sip
    _widget_is_valid = lambda w: not sip.isdeleted(w)
except ImportError:
    _widget_is_valid = lambda w: True  # fallback

def set_entries(self, entries):
    if not _widget_is_valid(self._status):
        return
    # ... normal work ...
```

This applies to `LogTableWidget.set_entries()`, `append_entries()`, and `clear()`.

### DiagnoseModule — Hub Pattern (`src/modules/diagnose/diagnose_module.py`)

The `DiagnoseModule` embeds 6 diagnostic viewers as sub-tabs (Event Viewer, CBS Log, DISM Log, Windows Update, Reliability, Crash Dumps) with a unified search bar. These 6 modules are NOT registered as standalone sidebar entries — they exist only within the hub. Their standalone files (`event_viewer_module.py`, `cbs_module.py`, etc.) exist but are not imported in `main.py`.

- Tabs are lazy-loaded on first switch via `_load_tab()`; the `loaded` flag in `_tab_state` prevents re-parsing
- `_build_tab_widget()` is a module-level factory that constructs each tab's UI — new diagnostic tabs should follow this pattern
- Unified search runs as a separate `_active_search: Worker` tracked independently from `self._workers`; `on_stop()` must cancel it explicitly
- Crash Dumps tab requires admin — `_load_tab()` checks `is_admin()` before loading and shows an error banner if not elevated

### TreeSize Module (`src/modules/treesize/`)

Three key files:
- `disk_scanner.py` — `DiskScanner` runs in a background thread, emits batches of `DiskNode` via `signals.batch_ready` every 500 nodes; `signals.progress` emits the running node count
- `disk_tree_model.py` — `DiskTreeModel` (a `QAbstractItemModel`) receives batches via `add_batch()` on the main thread; it must override `sort()` for interactive column sorting in `QTreeView`
- `treesize_module.py` — wires scanner signals to model mutations; uses `threading.Thread(daemon=True)` for the scanner

`DiskTreeModel.sort()` is required because `QAbstractItemModel` does not implement sorting by default — it must be overridden to sort `self._roots` and each node's `children` list:

```python
def sort(self, column: int, order: Qt.SortOrder = ...) -> None:
    self.layoutAboutToBeChanged.emit()
    # sort self._roots and recursively sort children
    self.layoutChanged.emit()
```

Also call `hdr.setSortIndicatorShown(True)` and `self._tree.setSortingEnabled(True)` on the view.

### Cleanup Module (`src/modules/cleanup/`)

**Scanner** (`cleanup_scanner.py`): functions take `min_age_days: int = 0` and return `ScanResult`. `ScanItem` fields: `path`, `size`, `is_dir`, `selected`, `safety` ("safe"/"caution"/"danger") — **no `name` field** (passing `name=` raises `TypeError`).

**8-tab structure** in `cleanup_module.py`:
- `_ScanTab(QWidget)` — reusable tab wrapping a `{fn: label}` scanners dict; exposes `freed_bytes = pyqtSignal(int)` and `auto_scan()` (no-op if already scanned). Tracks **all** workers (scan + clean) in a single `self._workers: list` to avoid losing the scan worker when a clean starts. Workers are appended in both `_do_scan()` and `_do_clean()`.
- `_BrowserCleanupTab(QWidget)` — uses `EnhancedBrowserScanner` from `browser_scanner.py`; same `freed_bytes` signal; same `_workers` list pattern.
- `_LargeItemsTab(QWidget)` — wraps `_ScanTab` + DISM "Component Cleanup" button (runs `dism /Online /Cleanup-Image /StartComponentCleanup` in background). Its `_cancel_all()` calls `self._scan_tab._cancel_all()` then `self._dism_worker.cancel()`.
- `_OverviewTab(QWidget)` — table of all groups; "Scan All" parallelises workers; "Clean All Safe" deletes safe items. `_cancel_all()` iterates `self._scan_workers` list calling `w.cancel()` on each, then cancels `self._worker`.
- `CleanupModule.on_activate()` triggers `_overview.auto_scan()`; `QTabWidget.currentChanged` wires each tab's `auto_scan()` for lazy first-load
- Session freed counter aggregates all `freed_bytes` signals via `_on_freed(nbytes)`

### Auto-Refresh System (`MainWindow`)

`MainWindow._start_module_refresh_timer()` starts a `QTimer` for modules that return a non-None interval from `get_refresh_interval()`. The timer calls `refresh_data()` if available, otherwise `on_activate()`. All timers are stopped in `closeEvent()`. The toolbar has a "Pause/Resume Refresh" toggle that sets `self._auto_refresh_paused` and stops/restarts the current module's timer.

### Search System (`src/core/search_engine.py`, `src/core/search_provider.py`)

Modules return a `SearchProvider` subclass from `get_search_provider()`. The engine aggregates results from all providers and sorts by relevance. Query filter: set `query.sources` to limit to specific modules. The DiagnoseModule has its own unified search that iterates per-tab providers — it does NOT use `app.search`.

### Event Bus (`src/core/event_bus.py`)

Pub/sub for loose coupling between modules. Use `app.event_bus.publish("topic", data)` and `subscribe("topic", handler)`. Available topics include module selection, theme changes, cleanup completions.

### Tweak System (`src/modules/tweaks/`)

JSON definition files in `src/modules/tweaks/definitions/` define registry/script tweaks. Each entry has `steps[]` with `type: "registry"` (key, data, kind) or `type: "powershell"`. `tweak_engine.py` applies and reverts them. App catalog (`app_catalog.json`) detects installed apps. Restore points created automatically before applying tweaks.

### Command Palette

`MainWindow._open_command_palette()` opens a fuzzy-searchable command palette (`ui/command_palette.py`) bound to `Ctrl+P`. It lists all modules and navigates to the selected one.

### Admin Restart

`restart_as_admin()` (from `core.admin_utils`) relaunches the application with elevation via `shell.execute(runas)`. Shown in the admin banner at the top of the main window and in the File menu.

### Triage / System Tray

`SystemTrayManager` (`ui/notification_tray.py`) shows a tray icon with context menu. `MainWindow.closeEvent()` checks `app.config.get("app.minimize_to_tray")` — if true, hiding instead of closing shows a balloon notification.

## UI Patterns

**Dark theme** — all modules use `#2d2d2d` backgrounds, `#3c3c3c` cards, `#e0e0e0` text. QSS styles are in `src/ui/styles/dark.qss`.

**Error handling** — show errors in-module via `ErrorBanner` widget (`src/ui/error_banner.py`) or `QMessageBox`, not just logs.

**Loading/empty states** — wrap content in `QStackedWidget`; page 0 = content, page 1 = centered "No data — click Refresh" label.

**Confirmation dialogs** — always confirm destructive actions (delete, stop service, disable startup item, toggle Windows features).

**Admin-gated modules** — `requires_admin = True` on the module class. `ModuleRegistry.start_all()` checks `is_admin()` and disables the module if not elevated.

## Adding New Modules

In `main.py`, import and register:
```python
from modules.<name>.<module_name>_module import MyModule
app.module_registry.register(MyModule())
```

Note: EventViewer, CBS, DISM, WU, Reliability, and CrashDumps are embedded in DiagnoseModule — do NOT register them as standalone modules.

## PyInstaller Build Notes

Two spec files:
- `WinClientTool.spec` — onedir/folder build
- `WinClientTool-portable.spec` — onefile/portable build

Data files bundled: `config/` (at project root), `src/ui/styles/` (→ `ui/styles`), `src/modules/tweaks/definitions/` (→ `modules/tweaks/definitions`). Hidden imports cover PyQt6, pywin32, PIL, requests.

## Important Gotchas

- `sys.stdout` is `None` in onefile windowed mode — always guard `sys.stdout.isatty()` with `hasattr(sys.stdout, 'isatty')`
- `tempfile` module must be explicitly imported — PyInstaller may miss it
- The walrus operator `:=` inside PyQt `addRow()` calls causes Python 3.12 parser failures — avoid it, use separate assignment lines
- `win32serviceutil` (pywin32) requires `pythoncom.CoInitialize()` before use in worker threads; use `COMWorker` instead of `Worker` for WMI/COM operations
- Do NOT call UI-creating methods (`_load_data()`, `_setup_table()`) from `on_start` — use `on_activate` instead since `on_start` runs before `create_widget`
- **Silent exception swallowing is forbidden** — `except Exception: pass` and bare `except: pass` silently hide errors from users who see only empty results. Always log exceptions with `logger.warning()` or `logger.error()`.
- `QTableWidget.sortOrder()` does not exist in PyQt6 — use `self._table.horizontalHeader().sortIndicatorOrder()` to get the current sort direction.
- CBS.log and DISM.log use a regex pattern that matches a specific format — if logs are empty, the log files may use a different format or be UTF-16 encoded (the base parser handles this but the per-line regex may not match all lines)
- **Windows 11 quirks**: CBS.log may not exist as a text file — Windows 11 stores CBS data in `CbsPersist_*.cab` files under `C:\Windows\Logs\CBS\`. The DiagnoseModule's CBS tab uses 7z to extract the log from the most recent cab if the text file is absent. DISM.log similarly may not exist; the DISM tab falls back to `Get-HotFix` (no admin required) to show installed updates.
- **Widget subclasses** (`_ScanTab`, `_RefreshTab`, `_ToolCard`, `_DiskCard`, `_FixCard`) are `QWidget`, NOT `BaseModule`. They need their own worker tracking (`self._workers: list`, `self._thread_pool`) and must expose a `cancel()` or `_cancel_all()` method that `on_deactivate()` can call.
- **DiagnoseModule worker tracking**: `self._workers` covers per-tab loader workers; `_active_search` (a standalone `Worker`) must be cancelled separately in `on_stop()`.
- **Timers in module-level helper functions** — if a `_ToolCard` or card helper creates a `QTimer` (e.g., auto-refresh in network diagnostics), store it on the card (`card._auto_timer = timer`) so `_cancel_all_cards()` can stop it on deactivation.

### Network Diagnostics `_ToolCard` Pattern (`src/modules/network_diagnostics/`)

`_ToolCard` is a module-level `QFrame` subclass (not a `BaseModule`). Each card builder function must assign the return value to a local `card` variable BEFORE any closures that capture `nonlocal card` run. Always do:

```python
def _build_foo_card() -> _ToolCard:
    card: Optional[_ToolCard] = None  # pre-declare so closures capture it
    # ... build UI ...
    def _run_foo():
        nonlocal card
        # ... uses card._worker ...
    btn.clicked.connect(_run_foo)
    card = _ToolCard("Title", content)  # MUST be assigned before return
    return card
```

Also add `card is not None` guard in `_cancel_all_cards()` to handle any stray `None` entries.

### PerfMon Custom Charts (`src/modules/perfmon/perfmon_charts.py`)

Charts are drawn with pure `QPainter` — no pyqtgraph or matplotlib. `_QtLineChart` is the core widget. **PyQt6 coordinate types are strict**: `drawText`, `drawLine`, `fillRect`, and `drawEllipse` all require `int` coordinates. Use `int()` casts on all computed positions — `QPointF.x()` returns float, which will raise `TypeError` in PyQt6.

### Cleanup Browser Scanner (`src/modules/cleanup/browser_scanner.py`)

`pathlib.Path.is_file()` does NOT accept `follow_symlinks` keyword argument on all Python versions. Use `entry.is_file()` without arguments — symlink follow is the default.

## PyInstaller Build Notes

Two spec files:
- `WinClientTool.spec` — onedir/folder build
- `WinClientTool-portable.spec` — onefile/portable build

Data files bundled: `config/` (at project root), `src/ui/styles/` (→ `ui/styles`), `src/modules/tweaks/definitions/` (→ `modules/tweaks/definitions`). Hidden imports cover PyQt6, pywin32, PIL, requests.

## Important Gotchas
