# Comprehensive Code Quality Fix — Spec

**Date:** 2026-04-11
**Scope:** Full codebase audit → fix all bugs, best practice violations, auto-refresh, architectural cleanup

---

## Workstream A — Critical Bugs

### A1: Race Condition — Direct `_cancelled` Assignment
**Files:**
- `src/modules/wifi_analyzer/wifi_module.py:258`
- `src/modules/duplicate_finder/duplicate_finder_module.py:242`

**Bug:** `self._scan_worker._cancelled = True` bypasses the thread-safe `Lock` in `Worker.cancel()`.
**Fix:** Replace with `self._scan_worker.cancel()` and `self._worker.cancel()`.

### A2: Memory Leak — Module-Level `_worker_cancellers` List
**File:** `src/modules/network_diagnostics/network_module.py:39`

**Bug:** `_worker_cancellers: list = []` accumulates lambdas forever with no cleanup.
**Fix:** Clear the list in `on_deactivate()`.

### A3: Timer Leak — Port Scanner Progress Timer
**File:** `src/modules/network_diagnostics/network_module.py:387-398`

**Bug:** `progress_timer = QTimer()` is a local variable with no cleanup path.
**Fix:** Store as `self._port_scan_progress_timer` and stop/delete it in card cancellation.

### A4: Workers Not Tracked — QuickFixModule
**File:** `src/modules/quick_fix/quick_fix_module.py:87-90`

**Bug:** `self._worker` is stored but not added to `self._workers`. `cancel_all_workers()` iterates `self._workers` so workers are never cancelled.
**Fix:** Add `self._workers.append(self._worker)` after starting worker.

### A5: Silent Exception Swallowing
**Files:**
- `src/modules/cleanup/cleanup_module.py:190-196`
- `src/modules/cleanup/browser_scanner.py:80-89`

**Bug:** `except Exception: pass` with no logging.
**Fix:** Replace with `except Exception as e: logger.warning(f"...: {e}")`.

### A6: Cross-Thread Widget Access — Network Diagnostics
**File:** `src/modules/network_diagnostics/network_module.py:401-426`

**Bug:** Callbacks access widgets (`progress_bar`, `table`) without `sip.isdeleted()` guard.
**Fix:** Add `sip.isdeleted()` guard at top of each callback, or use signal marshaling.

### A7: UpdatesModule Double auto_scan
**File:** `src/modules/updates/updates_module.py:437-448`

**Bug:** `on_activate()` calls `auto_scan()`, then `_on_tab_changed()` is also triggered, calling `auto_scan()` again.
**Fix:** Have `on_activate()` delegate to `_on_tab_changed(current_index)`.

### A8: Mutable Default Argument Anti-Pattern
**File:** `src/modules/driver_manager/driver_module.py:37`

**Bug:** `self._drivers_ref: list = [[]]` uses mutable default.
**Fix:** Use `None` and initialize in `__init__`.

---

## Workstream B — Auto-Refresh System

### Strategy
- Each module that has a refresh button and expensive data loading implements `get_refresh_interval()` returning milliseconds (per-module intervals).
- `MainWindow` already has the timer infrastructure — no changes needed there.
- Modules must also implement `refresh_data()` that does the same work as the initial load.

### Priority Modules for Auto-Refresh
| Module | Suggested Interval | Notes |
|--------|-----------------|-------|
| DashboardModule | 5,000ms | Already has internal timer — wire to global system |
| ServicesManagerModule | 30,000ms | Expensive WMI scan |
| SecurityDashboardModule | 30,000ms | Multiple WMI queries |
| NetworkDiagnosticsModule | 15,000ms | Connections tab |
| DiagnoseModule | 60,000ms | Each tab's `auto_scan()` |

### Per-module requirements
Each auto-refresh module must:
1. Implement `get_refresh_interval() → int`
2. Implement `refresh_data()` (same as initial load logic)
3. Have a "while-refreshing" guard flag to prevent concurrent refreshes
4. Call `_setup_ui()` only once (first-load guard)

---

## Workstream C — First-Load Guards

### C1: TweaksModule
**File:** `src/modules/tweaks/tweaks_module.py:296-298`
**Fix:** Add `_loaded: bool` flag, only call detection on first `on_activate()`.

### C2: DashboardModule
**File:** `src/modules/dashboard/dashboard_module.py:144-152`
**Fix:** Don't start timer in `__init__`. Start in `on_activate()`, stop in `on_deactivate()`.

### C3: SecurityDashboardModule
**File:** `src/modules/security_dashboard/security_module.py:117-156`
**Fix:** Add `_security_loaded` guard. Only run `do_refresh()` on first activation.

### C4: DiagnoseModule
**Fix:** Already has lazy loading via `_load_tab()`. Ensure no double-load on first activation.

---

## Workstream D — CleanupModule Split

### Goal
Split `cleanup_module.py` (~1200 lines, 8 tab classes) into one file per class.

### New File Structure
```
src/modules/cleanup/
  cleanup_module.py       ← Main module + shared utilities
  tabs/
    __init__.py
    _overview_tab.py      ← _OverviewTab
    _scan_tab.py          ← _ScanTab
    _browser_tab.py        ← _BrowserCleanupTab
    _large_items_tab.py    ← _LargeItemsTab
    _system_junk_tab.py    ← _SystemJunkTab
    _app_clutter_tab.py    ← _AppClutterTab
    _registry_tab.py       ← _RegistryTab
    _restore_points_tab.py ← _RestorePointsTab
```

### Bugs Fixed During Split
- `except Exception: pass` → `logger.warning()`
- `_scanning` flag already present — ensure consistent across all tabs
- `on_deactivate()` cancellation chains into internal widgets

---

## Workstream E — Consistency Pass

### E1: Widget Lifetime Guards
Add `sip.isdeleted()` guards to callbacks in:
- `updates_module.py` — `_on_updates()`, `_on_error()`
- `services_manager.py` — `_load_detail()` callbacks

### E2: Empty States
Add "No results" labels to tables that can show empty state:
- `services_manager.py` — filter returns 0 rows

### E3: Loading Indicators
- `quick_fix_module.py` — add "Running..." label before execution

### E4: ErrorBanner Usage
- `network_diagnostics.py` — use `ErrorBanner` for connection errors instead of just status label

### E5: PerfMonTimer Cleanup
**File:** `src/modules/perfmon/perfmon_module.py:153, 202-203`
**Fix:** `_live_timer` created without parent. Add `deleteLater()` in `on_deactivate()`.

### E6: Network Diagnostics Card Cleanup
**File:** `src/modules/network_diagnostics/network_module.py:484-501`
**Fix:** `_build_connections_card()` stores `auto_timer` on card. Add `card._auto_timer.stop()` in `_cancel_all_cards()`.

---

## Implementation Order

1. **A (Critical Bugs)** — 8 files, 8 distinct fixes
2. **C (First-Load Guards)** — 4 modules
3. **B (Auto-Refresh)** — wire up 5 priority modules
4. **E (Consistency)** — across all modules
5. **D (CleanupModule Split)** — last due to highest refactor risk
