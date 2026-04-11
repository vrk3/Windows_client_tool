# Design: Cleanup Expansion — New Categories, Advanced Panel, One-Click Actions

## Context

The existing cleanup system covers the basics (temp, browser, prefetch, crash dumps, app caches, dev tools, logs, Windows Update, large items, WinSxS). The user wants to significantly expand the cleanup capabilities with more categories, an "Advanced" expandable section in QuickCleanupTab, and one-click system maintenance actions.

**Option C approved**: Main pie chart keeps existing 10 categories. "Show Advanced" expands to reveal new categories. "Clean All Safe" button covers all `safe` items across both sections.

---

## What Changes

### 1. New Scan Functions (cleanup_scanner.py)

Add 8 new scan functions, all following the existing pattern: `scan_<name>(min_age_days=0) -> ScanResult`.

| ID | Function | Key Paths | Safety |
|----|----------|-----------|--------|
| `recent` | `scan_recent_files()` | `%APPDATA%\Microsoft\Windows\Recent\*.lnk`, `AutomaticDestinations\*.automaticDestinations-ms`, `CustomDestinations\*.customDestinations-ms` | `safe` |
| `games` | `scan_game_caches()` | Steam `htmlcache/shadercache/downloads`; Epic `RegistryCache/DataCache`; Xbox `LocalCache`; Battle.net `Cache`; EA app `Caches`; Ubisoft Connect `cache`; GOG Galaxy `cache`; Discord `Cache` | `safe` |
| `adobe` | `scan_adobe_cache()` | `%APPDATA%\Adobe\Common\Media Cache Files`, `Media Cache`, `Peak Files`, `Logs`; `%APPDATA%\Adobe\Adobe Reckon Media Cache Files` | `safe` |
| `office` | `scan_office_temp()` | `%LOCALAPPDATA%\Microsoft\Office\*\OfficeFileCache`; `%TEMP%\Excel*.tmp`, `Word*.tmp`; `%APPDATA%\Microsoft\Office\*\UnsavedFiles` | `safe` |
| `jets` | `scan_ide_caches()` | JetBrains `*IDE*caches`, `*IDE*index`, `*IDE*logs`; Visual Studio `.vs\*`, `ComponentModelCache`, `TEMP\~vs*`; Notepad++ `backup\*`; FileZilla `sitemanager.xml` cache | `safe` |
| `spooler` | `scan_print_spooler()` | `C:\Windows\System32\spool\PRINTERS\*` (skip if `spooler` service != Running); `C:\Windows\System32\spool\SERVERS\*` | `caution` |
| `winsat` | `scan_winsat_cache()` | `C:\Windows\Performance\WinSAT\*.xml`, `Media.ets`, `winsat.log` | `safe` |
| `etl` | `scan_etl_logs()` | `C:\Windows\Logs\WindowsUpdate\*etl`; `C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Logs\*`; `C:\Windows\Temp\ScriptArtifacts\*` | `caution` |

**Path resolution strategy** — use `os.path.expandvars()` for `%APPDATA%` etc., `pathlib.Path.home()` for `~`, enumerate known subdirectories rather than scanning full `%LOCALAPPDATA%` recursively.

---

### 2. Advanced Panel in QuickCleanupTab (UI)

Add an expandable "Advanced Cleanup" section below the existing 10-category scroll area. Hidden by default, revealed by a "Show Advanced" button.

**Structure** (`quick_cleanup_tab.py`):

```
AdvancedPanel (QWidget, collapsed by default)
  ├── Header: QLabel "Advanced Cleanup" + "Show/Hide" toggle button
  ├── Content (QWidget, hidden when collapsed)
  │   ├── Grid of _SliceCard for each advanced category
  │   ├── Brief description text per category
  │   └── One-Click Actions section (see below)
```

**Advanced categories list** — added to `CLEANUP_CATEGORIES` as a second constant `ADVANCED_CATEGORIES`. Each entry: `(id, label, color)`.

**Toggle behavior**: clicking "Show Advanced" expands the section, changes button text to "Hide Advanced". State does not persist across sessions.

**Clean All Safe behavior** unchanged — already iterates `self._results` and only includes items where `safety == "safe"`. The new `caution` items (`spooler`, `etl`) won't be auto-selected by "Clean All Safe".

---

### 3. One-Click Maintenance Actions Panel

A horizontal button strip below the advanced categories. Each action runs a subprocess command. Results shown in a toast/status label.

| Action | Label | Command | Safety |
|--------|-------|---------|--------|
| Flush DNS | "Flush DNS Cache" | `ipconfig /flushdns` | Low risk |
| Clear Event Logs | "Clear Event Logs" | `wevtutil cl System && wevtutil cl Application` | Medium — requires confirmation dialog first |
| Compact WinSxS | "Compact WinSxS" | `DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase` | Medium — long operation (10-30 min), runs in background Worker |
| Rebuild Icon Cache | "Rebuild Icons" | `taskkill /f /im explorer.exe && del /q "%LOCALAPPT%\Microsoft\Windows\Explorer\iconcache_*" && start explorer` | Low |
| Win Update Deep Clean | "WU Deep Clean" | `DISM /Online /Cleanup-Image /StartComponentCleanup /SuppressDefaultTasks` | Medium |
| Network Repair | "Network Repair" | `netsh winsock reset && netsh int ip reset` | **High** — requires extra "I understand" confirmation; brief network disconnection |

**Confirmation dialogs**: Clear Event Logs and Network Repair require a `QMessageBox.warning` with "This action cannot be undone. Continue?" + OK/Cancel.

**WinSxS/Deep Clean**: these are long-running. Run in a `Worker`, show a `QProgressDialog` with "This may take several minutes..." and a cancel button. Pass `worker.signals.progress` updates if DISM emits them.

**Status reporting**: each button shows a result label ("DNS flushed successfully", "Failed: access denied") via `self._status_lbl` on the panel.

---

### 4. _id_map Updates in QuickCleanupTab.build()

Update `_id_map` to include new scanner functions:

```python
_id_map = {
    "recent": (cs.scan_recent_files,     "safe"),
    "games":  (cs.scan_game_caches,      "safe"),
    "adobe":  (cs.scan_adobe_cache,      "safe"),
    "office": (cs.scan_office_temp,      "safe"),
    "jets":   (cs.scan_ide_caches,      "safe"),
    "spooler":(cs.scan_print_spooler,   "caution"),
    "winsat": (cs.scan_winsat_cache,    "safe"),
    "etl":    (cs.scan_etl_logs,       "caution"),
    # browser still handled specially via self._browser_scanner
}
```

Advanced categories are built into a second `CategoryGroup` section with `auto_refresh=False` and scanned as part of `_do_scan_all()`.

---

### 5. cleanup_module.py Updates

The existing 8-tab CleanupModule does not need changes. The new categories are only surfaced in QuickCleanupTab. Optionally, add a "System Maintenance" tab to the full CleanupModule with one-click action buttons, but this is out of scope for the initial release.

---

## Architecture

```
cleanup_scanner.py           — all scan functions
  scan_recent_files()
  scan_game_caches()
  scan_adobe_cache()
  scan_office_temp()
  scan_ide_caches()
  scan_print_spooler()
  scan_winsat_cache()
  scan_etl_logs()

quick_cleanup_tab.py        — dashboard UI
  CLEANUP_CATEGORIES        — existing 10
  ADVANCED_CATEGORIES       — new 8
  QuickCleanupTab.build()    — builds both sections
  _build_advanced_panel()    — creates advanced UI
  _do_one_click_action()     — runs maintenance commands

quick_cleanup_module.py     — BaseModule wrapper (unchanged)
```

---

## Edge Cases

- **Spooler active**: check `spooler` service status via `subprocess.run(["sc", "query", "spooler"])` before scanning. If Running, set `safety = "danger"` for that result so "Clean All Safe" excludes it.
- **Steam/Epic not installed**: scan silently returns empty `ScanResult` — normal, no error shown.
- **WinSxS DISM runs >30 min**: Worker timeout set to 3600s; show "This is taking longer than expected" after 60s.
- **Icon cache rebuild on locked files**: `del` may fail on `iconcache_*.db` if Explorer hasn't fully terminated. Run `taskkill /f /im explorer.exe` first, wait 2s, then delete, then `start explorer`.
- **Network repair disconnects**: warn user it may briefly drop network. Requires `self._status_lbl.setText("Network resetting...")` and app should show a "Network will reset in 5 seconds" dialog.

---

## Verification

1. Run `python src/main.py`, navigate to Quick Cleanup
2. Click "Show Advanced" — verify all 8 advanced categories appear with description text
3. Click "Scan All" — verify pie chart updates with all 18 categories (10 + 8)
4. Click "Clean All Safe" — verify `spooler` and `etl` (caution) items are NOT selected automatically
5. Expand `spooler` category — click Scan to see print spooler content (may be empty if no printer)
6. Test "Flush DNS" — should succeed, status shows "DNS cache flushed"
7. Test "Rebuild Icons" — Explorer should restart, icon cache rebuilt
8. Verify no crashes or tracebacks in console
