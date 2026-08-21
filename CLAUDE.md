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

For a clean rebuild of the portable (e.g. after code changes), delete the cached PKG first:
```
rm -f build/WinClientTool-portable/PYZ-00.toc build/WinClientTool-portable/PKG-00.toc
pyinstaller WinClientTool-portable.spec -y --distpath dist
```
The portable spec must include `a.binaries` and `a.datas` in the EXE constructor — without these, the output is a ~3MB bootloader stub.

**After every portable build, deploy it** — this is a hard requirement, not optional cleanup:
```
cp "dist/WinClientTool-Portable.exe" "C:/Users/iorda/OneDrive/1 Personal/Aplicații/WinClientTool-Portable.exe"
```
The user runs the app day-to-day from `Aplicații/`, not from this repo's own (gitignored) `dist/`. Skipping this step leaves a stale copy running there indefinitely — do it every time, overwriting whatever's already there. Same deal for an onedir build: `cp -r "dist/WinClientTool" "C:/Users/iorda/OneDrive/1 Personal/Aplicații/WinClientTool"`. See the `build-portable` skill (`.claude/skills/build-portable/SKILL.md`), which bakes this step in.

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
- `get_refresh_interval()` — return `Optional[int]` milliseconds (e.g. `60_000`) or `None` to disable auto-refresh

**The registry calls `get_search_providers()` (plural), not `get_search_provider()`.**
The default returns the single provider; a module speaking for several sources
overrides it. `SearchEngine.execute` filters *per provider* on
`provider.module_name`, so one provider standing in for several would have to
re-implement that filtering — hence the list.

### Composite Modules (`src/core/composite_module.py`)

A `CompositeModule` hosts other `BaseModule`s as tabs. `Diagnose`, `Debloat`,
`Startup & Boot` and `Network Diagnostics` are the four; a child stays an
ordinary module that knows nothing about being hosted, so it can be tested
alone and moved between hosts unchanged. A subclass only sets `self.children`
in `__init__` (import the children *inside* `__init__`, and add them to
`HIDDEN_IMPORTS` in `pyinstaller_common.py` — the frozen build otherwise runs
fine with the tab silently absent).

Four things about it that are easy to get wrong:

- **`on_activate`/`on_deactivate` go to the visible child only**, and a tab
  change deactivates the outgoing child before activating the incoming one.
  Children stop their refresh timers in `on_deactivate`; without this a host
  with three children polls WMI three times over for the life of the app.
- **`on_stop` reaches every started child, including ones whose tab was never
  opened** — so their widgets do not exist. A teardown path that touches UI
  must guard for that. `wifi_module._stop_scan` did not, and crashed.
- **Never `removeTab`/`insertTab` to swap in a lazily built widget.** Doing it
  on the current index fires `currentChanged` and re-enters the handler that
  asked for the build. Each tab owns a permanent page whose layout the child
  widget is added into.
- **Override `wrap(tabs)` to put chrome around the tabs.** `DiagnoseModule`
  does, to keep its unified search bar and results tree above them.
- **Auto-refresh is the host's, throttled per child.** `MainWindow` reads
  `get_refresh_interval()` off the *selected* module, so the composite answers
  with the fastest rate any child wants, and `refresh_data()` ticks the visible
  child only when that child's own interval has elapsed. A composite that does
  not answer leaves every child it hosts with no timer at all — that is how six
  modules lost auto-refresh in the first pass. It also means `refresh_data()`
  can fire for a child whose widget has never been built: guard teardown and
  refresh paths that touch UI.

A child that fails `on_start`, or needs elevation it does not have, becomes a
disabled tab carrying the reason — and those are different reasons; do not
show the admin message for a crash.

### Log Reader Modules (`src/core/log_reader_module.py`)

The six diagnostic readers (Event Viewer, CBS, DISM, Windows Update,
Reliability, Crash Dumps) are `LogReaderModule` subclasses: they set
`provider_class` and implement `load_entries(worker)`, and optionally
`build_controls(toolbar, extra)`. The UI is `ui/log_pane.py`'s `LogPane` —
table, detail panel, error banner, progress, Refresh — and there is exactly
one of it. Do not hand-roll another log pane.

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

**Cross-thread widget access — CRITICAL**: Never call Qt widget methods directly from a worker thread. Marshal via a `pyqtSignal`:

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

When a worker fires after its host widget has been deleted (e.g. user switched tabs), guard with `sip.isdeleted()`:

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

### DiagnoseModule — Hub Pattern (`src/modules/diagnose/diagnose_module.py`)

`DiagnoseModule` is a `CompositeModule` over the six diagnostic readers (Event
Viewer, CBS Log, DISM Log, Windows Update, Reliability, Crash Dumps). Those six
are real `LogReaderModule`s again — they are not registered as sidebar entries,
but they are imported, started, and their search providers are registered.

- Tabs are built lazily by `CompositeModule`; `LogPane.loaded` prevents re-parsing
- Diagnose adds no pane of its own. To add a diagnostic source, write a
  `LogReaderModule` and put it in `self.children` — do not build another pane
- The unified search bar lives in `wrap()`. It runs as a separate
  `_active_search: Worker`, tracked apart from `self._workers`, and `on_stop()`
  cancels it explicitly before delegating to the composite
- Crash Dumps requires admin, so unelevated it is a disabled tab (the composite
  gates it) rather than a tab that loads and shows an error banner

### TreeSize Module (`src/modules/treesize/`)

A full TreeSize Professional clone, not a simple folder-size viewer. Built from
`docs/superpowers/specs/2026-08-18-treesize-pro-design.md`, which was derived from the
installed product's bundled help and screenshots — where that spec or this code names a
ribbon tab, view, or column, the name is the product's own.

Three layers, and the boundary between them is load-bearing:

- **`scan/`** — the engine. `volume_info.py` (raw volume geometry), `ntfs_structs.py`
  (byte-level NTFS parsing), `mft_reader.py` (streams `$MFT` directly, the fast path),
  `walk_scanner.py` (`FindFirstFileExW` fallback), `filters.py`, `prune.py`,
  `scanner.py` (engine selection + orchestration).
- **`store/`** — `node_store.py` (columnar arrays; a node is an `int` index, not an
  object), `rollup.py`, `aggregates.py` (per-view sums).
- **`ui/`** — `shell.py` assembles the ribbon, tree, drive list, view tabs and status
  bar; `treemap.py` is Qt-free layout; `views/` holds Chart, Details, and the aggregate
  tables.

**No PyQt6 imports in `scan/` or `store/`.** That is what lets ~450 engine tests run
with no display and no elevation, and it is why every NTFS function takes `bytes` rather
than a handle.

**Two engines.** Elevated + whole NTFS drive → MFT reader (a full `C:` in ~20s).
Anything else → walk scanner. `get_volume_info()` returning `None` is the normal signal
to pick the walk engine, not an error.

**`size` and `alloc` are independent columns**, never derived from one another. A real
`C:` here reports 380.9 GB size against 139.9 GB allocated; the gap is sparse and
compressed files.

Gotchas that cost real debugging time, all recorded in
`.superpowers/sdd/2026-08-18-treesize-phase1-engine-store/progress.md`:

- **`$MFT` is fragmented on real volumes.** Reading `mft_offset .. +mft_valid_length` as
  one span silently loses every record past the first extent — it cost 62% of the
  volume here. Record 0's own `$DATA` run list gives the true extent map.
- **Record numbers are LOGICAL positions in the MFT data stream**, not physical offsets.
  Parent references use them, and physical offsets jump at every extent boundary.
- **Sparse and compressed attributes report their real cost in `TotalAllocated` (0x40)**,
  not `alloc_size` — NTFS emits that field for sparse too, not just compressed.
- **A torn record must skip, not raise.** The volume is read live with no snapshot, so
  records genuinely change mid-read.
- **`QModelIndex.internalId()` cannot distinguish 0 from unset**, and the scan root is
  node 0 — ids are stored as `node + 1`.
- **Sorting must never reset the model** (it collapses the tree), and the sort key lives
  on the model so folders expanded *after* a sort are ordered too.
- **Size columns sort on the number, not the formatted text**, or "9 B" lands above
  "10 GB".

`tools/treesize_scan.py` is a console harness for the engine — it prints engine, totals,
rate, bytes/node and a flag census, and **exits 2 when the scan was incomplete**.

### Log Viewer (`src/modules/log_viewer/`)

A CMTrace-style viewer for ConfigMgr and plain-text logs. Its own sidebar
module rather than a Diagnose tab: CBS and DISM point at FIXED system paths,
this opens whatever it is handed.

- **`cmtrace_parser.py`** — `<![LOG[msg]LOG]!><time= date= component= type= …>`
  records into the app's `LogEntry`. `type` 1/2/3 → Info/Warning/Error, which
  is what the colouring hangs off. Auto-detects by sniffing the head of the
  file and falls back to a best-effort plain-text parse.
- **`log_reader.py`** — byte-offset incremental reads.
- **`log_model.py`** — `QAbstractTableModel` over a capped `deque`.
- **`log_search_provider.py`** — joins the global search bar.

**No Qt in the parser or the reader**, the same split `scan/` and `store/`
keep in TreeSize, so both are testable without a display.

Gotchas, every one of which cost real debugging:

- **Every log under `C:\Windows\Logs` is UTF-8 WITH a BOM.** Decoded that is
  a leading `\ufeff`, which is invisible and is NOT matched by `\s`, so the
  leading-timestamp regex missed and the first line of every real Windows log
  came through undated. Generated test data never has a BOM; only real files
  do. `LogReader` strips it once, at the very start of the stream only.
- **A rollover is detected by the file's IDENTITY, not its size.** SCCM rolls
  the log and starts a new one under the same name; a rollover to the same
  length is invisible to a size check, and keeping the old offset means
  reading past the end forever — the view goes silent and looks like a quiet
  machine.
- **A half-written final line is held back** until its newline lands. A
  CMTrace record cut down the middle parses as nothing.
- **Undecodable trailing bytes are carried forward.** A multi-byte character
  split across two reads decodes to a replacement character that never
  repairs itself.
- **`LogModel.append` INSERTS, it does not reset.** A reset clears the view's
  selection, and while following that runs once a second — click a row to
  read it and it deselects under you. A reset is right only when the cap
  starts dropping from the front and every index shifts.
- **The 32 MB read cap is measured, not guessed.** Parsing runs ~26 MB/s, so
  that is ~1.2s for an Open where 64 MB is 2.7s; it also yields ~170k records
  against the model's 200k cap, so the two limits are matched. An 8 MB cap
  silently loaded 47,831 of a 21 MB log's 120,000 records.
- **Truncation is always stated in the status bar.** Silently showing the last
  N lines of a longer log is how someone concludes the log is clean.
- The search provider holds the model's live deque rather than copying it per
  tick, and snapshots inside `search()` instead — the global bar runs on the
  UI thread today, but `DiagnoseModule` already searches on a Worker.

`tools/logviewer_check.py` drives it against the REAL CBS/DISM/Panther logs
plus a generated ConfigMgr one, including a rollover. **The CMTrace path has
never read a genuine SCCM or Intune log** — no ConfigMgr client on the dev
machine — so that check is still owed.

### Cleanup Module (`src/modules/cleanup/`)

**Scanner** (`cleanup_scanner.py`): functions take `min_age_days: int = 0` and return `ScanResult`. `ScanItem` fields: `path`, `size`, `is_dir`, `selected`, `safety` ("safe"/"caution"/"danger") — **no `name` field** (passing `name=` raises `TypeError`).

**8-tab structure** in `cleanup_module.py`:
- `_ScanTab(QWidget)` — reusable tab wrapping a `{fn: label}` scanners dict; exposes `freed_bytes = pyqtSignal(int)` and `auto_scan()` (no-op if already scanned). Tracks **all** workers (scan + clean) in a single `self._workers: list`.
- `_BrowserCleanupTab(QWidget)` — uses `EnhancedBrowserScanner` from `browser_scanner.py`; same signal and worker pattern.
- `_LargeItemsTab(QWidget)` — wraps `_ScanTab` + DISM "Component Cleanup" button in background. Its `_cancel_all()` calls `self._scan_tab._cancel_all()` then `self._dism_worker.cancel()`.
- `_OverviewTab(QWidget)` — table of all groups; "Scan All" parallelises workers; "Clean All Safe" deletes safe items. `_cancel_all()` iterates `self._scan_workers` list calling `w.cancel()` on each.
- `CleanupModule.on_activate()` triggers `_overview.auto_scan()`; `QTabWidget.currentChanged` wires each tab's `auto_scan()` for lazy first-load

### QuickCleanupModule (`src/modules/cleanup/quick_cleanup_module.py`)

Single-page dashboard with pie chart and auto-refresh. Uses `QuickCleanupTab` from `modules/ui/components/quick_cleanup_tab.py`.

- `_id_map` — maps category IDs to `(scanner_fn, safety)` tuples
- `_adv_scanner_map` — maps advanced category IDs
- `_do_scan_all()` — runs both main and advanced scanners in parallel via Workers
- `_toggle_advanced()` — reveals/hides the advanced panel
- `_build_one_click_panel()` — one-click maintenance actions (Flush DNS, Clear Event Logs, Compact WinSxS, Rebuild Icons, WU Deep Clean, Network Repair)
- `get_refresh_interval()` returns `60_000` (60s auto-refresh)
- `on_deactivate()` calls `stop_auto_refresh()` and `cancel()` to stop timers and workers

### DebloatModule (`src/modules/debloat/debloat_module.py`)

`DebloatModule` is a `CompositeModule` with two children: `DebloatToolsModule`
(the three tabs below, `requires_admin = True`) and Store Apps.

`DebloatToolsModule` is a 3-tab module in `ModuleGroup.OPTIMIZE`:
- **Apps tab** — scans installed UWP apps via `Get-AppxPackage` (using `debloat_scanner.py`), shows table with checkboxes, Apply Selected / Apply All Safe. Protected apps (Store, Terminal, Get Help, Calculator, Notepad, Alarms) highlighted orange and require confirmation before removal.
- **Privacy & Telemetry tab** — loads tweak definitions from `privacy.json`, `telemetry.json`, `services.json`, `network.json`; shows status (Applied/Not Applied) per tweak; preset filters (Light, Full, Privacy-Focused, Custom)
- **AI & Navigation tab** — loads `ai_features.json` and `navigation.json`; same UI pattern

Restore points created via `BackupService` before any apply operation. TweakEngine detects status for registry, service, appx, and scheduled_task step types.

### PerfTunerModule UI Pattern (`src/modules/performance_tuner/perf_tuner_module.py`)

Checklist-style table with 5 columns: ☑ Select | Name | Category | Risk | Status. Per-row Apply button. Preset buttons (Light, Aggressive, Custom) at top. This is the reference UI pattern for modules that present a list of togglable items.

### QuickFixModule (`src/modules/quick_fix/quick_fix_module.py`)

Uses `_FixCard` widget subclasses for each fix. Cards run in background Workers. `QuickFixModule._workers` (plural, on the module) tracks all workers. Individual cards track `self._worker` (singular) for cancellation. `_FixCard` does NOT have a `_workers` list.

### Tweak System (`src/modules/tweaks/`)

JSON definition files in `src/modules/tweaks/definitions/` define registry/script tweaks. Each entry has `steps[]` with one of these types:

| Step type | Fields | What it does |
|-----------|--------|--------------|
| `registry` | `key`, `value`, `data`, `kind` | Sets a registry value via `winreg` |
| `service` | `name`, `start_type` | Changes service startup type via win32service |
| `command` | `cmd` | Runs a shell command via `subprocess.run` with `CREATE_NO_WINDOW` |
| `appx` | `package` | Removes a UWP app via `Get-AppxPackage \| Remove-AppxPackage` |
| `scheduled_task` | `task_name` | Disables a scheduled task via `schtasks /change /tn ... /disable` |

`tweak_engine.py` applies tweaks via `TweakEngine.apply_tweak()` and detects state via `TweakEngine.detect_status()` (returns `"applied"`, `"not_applied"`, or `"unknown"`). BackupService creates restore points automatically before applying.

Key definition files:
- `privacy.json` — privacy policy tweaks (47 entries)
- `telemetry.json` — telemetry and diagnostics tweaks (19 entries)
- `services.json` — service disable/enable tweaks (34 entries)
- `debloat.json` — 90+ UWP app removal entries with `appx` step type
- `ai_features.json` — Win11 24H2 AI feature tweaks (Click-to-Do, AI Hub, WSAIFabricSvc)
- `navigation.json` — File Explorer navigation pane tweaks (Gallery, 3D Objects, Home, duplicate drives)
- `definitions/builtins/*.json` — preset profiles (8 existing + 4 debloat presets)

### UpdatesModule (`src/modules/updates/`)

5-tab module in `ModuleGroup.TOOLS`, `requires_admin = True`. This installs updates — it is a different thing from `DiagnoseModule`'s embedded Windows Update *log* viewer.

- **App Updates tab** (`_AppUpdatesTab` in `updates_module.py`) — winget-based via `winget_updater.py`. Live filter box, "Package Details" (`winget show`), "Add to Blocklist", post-update verification. "Update All" is routed through the same per-item loop as "Update Selected" rather than one opaque `winget upgrade --all` call, so progress/pass-fail is per-package.
- **Windows Updates tab** (`_WinUpdatesTab`) — WUA COM via `windows_updater.py`'s `fetch_pending_updates()` / `install_updates_iter()` (per-item downloader/installer calls, real progress). Hide/show-hidden support, an opt-in restore point before install (`core/system_restore.py` — a real `Checkpoint-Computer`, NOT `BackupService.create_restore_point`, which is this app's own separate revert-log mechanism), post-install verification, WU HRESULT decoding (`core/wu_error_codes.py`).
- **Microsoft Store tab** (`_StoreUpdatesTab`, `store_updates_tab.py`) — renders the `source == "msstore"` subset of the *same* winget scan the App Updates tab already ran, dispatched via `UpdatesModule._on_app_updates()` → `_store_tab.set_updates()`. Does **not** run its own winget scan. "Verify Store Updates" triggers `core/mdm_store_trigger.py` (MDM CIM class — needs `COMWorker`).
- **Run All tab** (`_RunAllTab`, `run_all_tab.py`) — runs checked stages (wu/winget/store/cleanup/dism) sequentially in one worker, then writes run history and an HTML report.
- **Settings tab** (`_UpdateSettingsTab`) — blocklist editor, verify/restore-point/driver toggles, and the Task Scheduler wiring for `--unattended` mode.

**Shared stage logic** (`stage_runners.py`): `run_wu_stage` / `run_winget_stage` / `run_store_stage` / `run_cleanup_safe_stage` / `run_dism_stage`, each `(app, log_fn, is_cancelled_fn) -> dict`. Used by *both* `_RunAllTab` (threaded, `is_cancelled=lambda: worker.is_cancelled`) and `unattended_runner.py` (headless, `is_cancelled=lambda: False`) — extend this file rather than duplicating stage logic in either caller. `normalize_stage_data()` flattens the per-stage result dicts into the shape `report_generator.py` / `history_writer.py` expect.

**Blocklist** (`core/blocklist.py`): `is_blocked(name, id, patterns)` is fnmatch-based — a pattern with no `*` is auto-wrapped as `*pattern*`. Stored at config key `updates.blocklist_patterns` (`list[str]`), not a separate file. `add_pattern(app, pattern)` backs the "Add to Blocklist" button on both the winget and WU tabs.

**Unattended mode**: `python src/main.py --unattended --stages wu,winget,cleanup` — headless, no `QApplication`/`MainWindow`; calls `pythoncom.CoInitialize()` explicitly since there's no `COMWorker`/Qt event loop available. Requires admin — exits 1 immediately if not elevated. The Settings tab's "Create/Update Task" button wires this into Task Scheduler as `WinClientTool_UnattendedMaintenance` (`/rl HIGHEST`, `/sc DAILY /mo <N>`). The older winget-only `WinClientTool_UpdateCheck` task (`_save_legacy`) is kept as-is for existing users — don't merge it into the new one.

**Worker tracking**: every tab here is a `QWidget` (not `BaseModule`) with its own `self._workers: list` and `_cancel_all()`, per the general widget-subclass rule below. `UpdatesModule.on_deactivate()` / `on_stop()` call `_cancel_all()` on all four stateful tabs explicitly — `BaseModule.cancel_all_workers()` only covers workers created directly on the module itself, not on child tab widgets.

## UI Patterns

**Dark theme** — all modules use `#2d2d2d` backgrounds, `#3c3c3c` cards, `#e0e0e0` text. QSS styles in `src/ui/styles/dark.qss`.

**Error handling** — show errors in-module via `ErrorBanner` widget (`src/ui/error_banner.py`) or `QMessageBox`, not just logs.

**Loading/empty states** — wrap content in `QStackedWidget`; page 0 = content, page 1 = centered "No data — click Refresh" label.

**Confirmation dialogs** — always confirm destructive actions (delete, stop service, disable startup item, toggle Windows features).

**Admin-gated modules** — `requires_admin = True` on the module class. `ModuleRegistry.start_all()` checks `is_admin()` and disables the module if not elevated.

## Auto-Refresh System (`MainWindow`)

`MainWindow._start_module_refresh_timer()` starts a `QTimer` for modules that return a non-None interval from `get_refresh_interval()`. The timer calls `refresh_data()` if available, otherwise `on_activate()`. All timers are stopped in `closeEvent()`. The toolbar has a "Pause/Resume Refresh" toggle.

## Search System (`src/core/search_engine.py`, `src/core/search_provider.py`)

Modules return a `SearchProvider` subclass from `get_search_provider()`. The engine aggregates results from all providers and sorts by relevance. `SearchProvider` is an ABC — subclasses must implement `search(query: SearchQuery) -> List[SearchResult]` and `get_filterable_fields() -> List[FilterField]`. DiagnoseModule additionally has its own unified search bar that iterates its children's providers directly — that one does NOT use `app.search`. Its children's providers ARE registered with `app.search` as well, via `get_search_providers()`; they answer only after a tab has been opened once, because a provider is fed by `LogPane`'s `entries_loaded`.

## Event Bus (`src/core/event_bus.py`)

Pub/sub for loose coupling between modules. Use `app.event_bus.publish("topic", data)` and `subscribe("topic", handler)`. Available topics include module selection, theme changes, cleanup completions.

## Adding New Modules

In `main.py`, import and register:
```python
from modules.<name>.<module_name>_module import MyModule
app.module_registry.register(MyModule())
```

Note: EventViewer, CBS, DISM, WU, Reliability, and CrashDumps are embedded in DiagnoseModule — do NOT register them as standalone modules.

## Important Gotchas

- `sys.stdout` is `None` in onefile windowed mode — guard with `hasattr(sys.stdout, 'isatty')`
- `tempfile` module must be explicitly imported — PyInstaller may miss it
- The walrus operator `:=` inside PyQt `addRow()` calls causes Python 3.12 parser failures — use separate assignment lines
- `win32serviceutil` (pywin32) requires `pythoncom.CoInitialize()` before use in worker threads; use `COMWorker` instead of `Worker` for WMI/COM operations
- Do NOT call UI-creating methods (`_load_data()`, `_setup_table()`) from `on_start` — use `on_activate` instead since `on_start` runs before `create_widget`
- **Silent exception swallowing is forbidden** — `except Exception: pass` and bare `except: pass` silently hide errors from users who see only empty results. Always log with `logger.warning()` or `logger.error()`.
- `QTableWidget.sortOrder()` does not exist in PyQt6 — use `self._table.horizontalHeader().sortIndicatorOrder()` to get the current sort direction
- **Windows 11 quirks**: CBS.log may not exist as a text file — Windows 11 stores CBS data in `CbsPersist_*.cab` files. The CBS tab uses 7z to extract from the most recent cab if the text file is absent. DISM.log similarly may not exist; DISM tab falls back to `Get-HotFix`.
- **`get_refresh_interval()` return type** must be `Optional[int]` — some modules incorrectly declare `-> int:` which breaks type checking
- **Widget subclasses** (`_ScanTab`, `_FixCard`, `_ToolCard`, `_DiskCard`) are `QWidget`, NOT `BaseModule`. They need their own `self._workers: list` and must expose a `cancel()` or `_cancel_all()` method for `on_deactivate()` to call.
- **DiagnoseModule worker tracking**: `self._workers` covers per-tab loader workers; `_active_search` (a standalone `Worker`) must be cancelled separately in `on_stop()`.
- **Timers in card helpers** — if a `_ToolCard` or card helper creates a `QTimer`, store it on the card (`card._auto_timer = timer`) so `_cancel_all_cards()` can stop it on deactivation.
- **`subprocess` with `shell=True` discipline** — every `shell=True` call in this codebase (`tweak_engine.py`'s `command`/`script` steps, `backup_service.py`'s revert commands, `software_module.py`'s uninstall strings, `quick_cleanup_tab.py`'s one-click actions) runs a command string that traces back to a trusted, app-owned source: a bundled JSON tweak definition, a hardcoded string, or a registry-derived value the app doesn't let the user free-type into — never raw user input interpolated into the string. Keep it that way; if a new `shell=True` call needs to include user-typed text, don't string-format it in — pass args as a list with `shell=False`, or shell-quote properly (see `core/system_restore.py`'s `description.replace("'", "''")` for the one existing case that takes user text, going through PowerShell single-quote escaping rather than `shell=True`).
- **Destructive-action confirmations** — `core/confirm.py`'s `confirm_destructive()` is scaffolding for *new* destructive actions (Yes/No, defaults to No, standard wording). Existing modules mostly hand-roll their own `QMessageBox.question()`/`.warning()` calls for this and have NOT been retrofitted — that's intentional, not an oversight; don't "clean up" the existing call sites to use the helper as a drive-by change.
- **`QTabWidget.addTab()` fires `currentChanged` synchronously for the first tab added** — if a hub-style module (see DiagnoseModule) connects `currentChanged` before populating tabs, adding the first tab immediately triggers a real (potentially slow) data load during `create_widget()`, defeating the documented lazy-load-on-`on_activate` pattern. Connect `currentChanged` *after* the `addTab()` loop.
- **Building a real `App()` at pytest collection time can return a `None` `QThreadPool`** — `QThreadPool.globalInstance()` called from module-level test code (executed during collection, before fixtures run) has been observed to come back `None` in this codebase's import graph, while the identical call inside a fixture or test function body (execution time) does not. Collection-time code should only do cheap, non-Qt-threading work (e.g. building a module class list); construct the real `App` in a fixture — see `tests/test_module_smoke.py`.

### Network Diagnostics `_ToolCard` Pattern (`src/modules/network_diagnostics/`)

Each card builder function must assign the return value to a local `card` variable BEFORE any closures that capture `nonlocal card` run:

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

Also add `card is not None` guard in `_cancel_all_cards()`.

### PerfMon Custom Charts (`src/modules/perfmon/perfmon_charts.py`)

Charts are drawn with pure `QPainter` — no pyqtgraph or matplotlib. **PyQt6 coordinate types are strict**: `drawText`, `drawLine`, `fillRect`, and `drawEllipse` require `int` coordinates. Use `int()` casts on all computed positions.

### Cleanup Browser Scanner (`src/modules/cleanup/browser_scanner.py`)

`pathlib.Path.is_file()` does NOT accept `follow_symlinks` keyword argument. Use `entry.is_file()` without arguments.
