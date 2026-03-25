# Optimization, Management & Tools Suite — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-projects:** #3 (Optimization & Management) + #4 (Tools & Utilities)
**Date:** 2026-03-25
**Status:** Approved (v2 — post spec-review)
**Target users:** IT professionals, sysadmins, field engineers

---

## 1. Overview

This spec covers all new modules beyond the existing Diagnose group (Event Viewer, PerfMon, CBS, DISM, Reliability, Crash Dumps). It also covers the Navigation Shell redesign required to support 25+ modules.

**New modules by group:**

| Group | Modules |
|---|---|
| **System** | Hardware Inventory, Network Diagnostics, Security Dashboard, Driver Manager |
| **Manage** | Startup Manager, Scheduled Tasks, Windows Features, Certificate Viewer, GPResult Viewer |
| **Optimize** | Tweaks/Debloater, Cleanup, TreeSize, Performance Tuner |
| **Tools** | Updates (App+System), Registry Explorer, Software Inventory, Quick Fix Toolkit, Power & Boot, Network Extras, Shared Resources, Environment Variables, Remote Tools Launcher |
| **Process** | Process Explorer *(placeholder — Sub-project 3)* |

**Existing Diagnose group:** Event Viewer, PerfMon, Reliability Monitor, CBS Log, DISM Log, Windows Update Log, Crash Dumps — already built, no changes.

---

## 2. Navigation Shell Redesign

### 2.1 Layout

Replace `QTabWidget` with a sidebar + stacked widget layout:

```
┌─────────────────────────────────────────────────────────┐
│  [Admin banner (if not admin)]                          │
│  [Toolbar: Search bar | Filters | Module actions]       │
├────────────────┬────────────────────────────────────────┤
│ ◀ [collapse]   │                                        │
│                │                                        │
│ DIAGNOSE       │   [Active module widget]               │
│  📋 Events     │                                        │
│  📊 PerfMon    │                                        │
│  🔍 Reliability│                                        │
│  📁 CBS Log    │                                        │
│  🔧 DISM Log   │                                        │
│  🔄 WU Log     │                                        │
│  💥 Crashes    │                                        │
│                │                                        │
│ SYSTEM         │                                        │
│  🖥 Hardware   │                                        │
│  🌐 Network    │                                        │
│  🔒 Security   │                                        │
│  📜 Drivers    │                                        │
│                │                                        │
│ MANAGE         │                                        │
│  🚀 Startup    │                                        │
│  📅 Tasks      │                                        │
│  🪟 Features   │                                        │
│  🔑 Certs      │                                        │
│  📋 GPResult   │                                        │
│                │                                        │
│ OPTIMIZE       │                                        │
│  🧹 Tweaks     │                                        │
│  🗑 Cleanup    │                                        │
│  📁 TreeSize   │                                        │
│  ⚡ Perf Tuner │                                        │
│                │                                        │
│ TOOLS          │                                        │
│  📦 Updates    │                                        │
│  ⚙ Registry   │                                        │
│  💿 Software   │                                        │
│  🔨 Quick Fix  │                                        │
│  ⚡ Power/Boot │                                        │
│  🌐 Net Extras │                                        │
│  📂 Shares     │                                        │
│  🔤 Env Vars   │                                        │
│  🚀 Remote     │                                        │
│  🔬 Processes  │                                        │
└────────────────┴────────────────────────────────────────┘
│ Status bar: [module info] [admin status] [theme toggle] │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Implementation

**`group` attribute on `BaseModule`** (B1 fix):
Add `group: str` as a class-level attribute to `BaseModule` alongside `name`, `icon`, `description`, `requires_admin`. Canonical group constants defined in `core/module_groups.py`:
```python
class ModuleGroup:
    DIAGNOSE = "DIAGNOSE"
    SYSTEM   = "SYSTEM"
    MANAGE   = "MANAGE"
    OPTIMIZE = "OPTIMIZE"
    TOOLS    = "TOOLS"
```
`ModuleRegistry.register(module)` is unchanged — the group is read from `module.group`. `main.py` passes `module.group` to `SidebarNav.add_module(module)`. Every existing module gets `group = ModuleGroup.DIAGNOSE` added to its class body.

**`SidebarNav` widget** (`src/ui/sidebar_nav.py`):
- Implemented as `QWidget` with `QVBoxLayout` containing alternating `QLabel` group headers and `QPushButton` module items — simpler and more paintable than `QListWidget` with separator hacks (M1 fix)
- Group headers: bold, uppercase, non-interactive `QLabel` with bottom border
- Module buttons: icon + display name, flat style, left-aligned; disabled+greyed for admin-required modules when not elevated
- Collapsed mode: icon-only (40px width) via toggle button at top; tooltips show full name
- Emits `module_selected = pyqtSignal(str)` (module name)
- Keyboard: Up/Down navigate between module buttons, Enter activates

**`MainWindow` changes:**
- Remove `QTabWidget`; layout becomes `QSplitter(sidebar, QStackedWidget)`
- `add_module_tab(module, enabled)` → `register_module(module)` — reads `module.group` internally
- Internal tracking: `_module_map: dict[str, BaseModule]` keyed by `module.name`; `_active_module: Optional[BaseModule] = None`
- `SidebarNav.module_selected` connected to `_on_module_selected(name: str)`:
  ```python
  def _on_module_selected(self, name: str):
      if self._active_module:
          self._active_module.on_deactivate()       # deactivate old (I2 fix)
      self._active_module = self._module_map[name]
      self._stack.setCurrentWidget(self._active_module.widget)
      self._active_module.on_activate()
      self._toolbar.set_module_actions(self._active_module.get_toolbar_actions())
      self._status_bar.set_module_info(self._active_module.get_status_info())
  ```
- Admin-disabled modules: sidebar button disabled + lock icon; clicking shows tooltip "Requires administrator"

---

## 3. Shared BackupService

### 3.1 Architecture

New core service `BackupService` added to `App` as `app.backup` (I1 fix).

**Wiring in `app.py`:**
```python
# In App.__init__(), after self.logger.setup():
self.backup = BackupService(data_dir=self._app_data_dir)

# In App.shutdown():
self.backup.close()
```
`BackupService.__init__` creates `backups/` dir and opens SQLite connection. `close()` commits and closes the connection.

**Storage layout:**
```
%APPDATA%/WindowsTweaker/
  backups/
    2026-03-25_14-32-10_tweaks-session/
      manifest.json          ← label, timestamp, module, list of step IDs
      registry/              ← .reg exports (one per key/hive area)
      services/              ← services_state.json
      appx/                  ← removed_apps.json
      files/                 ← any file-based backups
  tweaks.db                  ← SQLite: per-step granular history
```

**`tweaks.db` schema** (B3 fix — step-level records, not scalar before/after):
```sql
CREATE TABLE restore_points (
    id          TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    created_at  DATETIME NOT NULL,
    module      TEXT NOT NULL,
    status      TEXT DEFAULT 'active'   -- active | restored | partial
);

CREATE TABLE tweak_steps (
    id               TEXT PRIMARY KEY,
    tweak_id         TEXT NOT NULL,
    restore_point_id TEXT NOT NULL REFERENCES restore_points(id),
    applied_at       DATETIME NOT NULL,
    step_type        TEXT NOT NULL,     -- registry | service | appx | command | file
    target           TEXT NOT NULL,     -- key path, service name, package name, etc.
    before_value     TEXT,              -- JSON-serialised previous state
    after_value      TEXT,              -- JSON-serialised new state
    reverted_at      DATETIME,
    revert_error     TEXT               -- populated if revert failed
);
```

### 3.2 API

```python
from typing import Any, List, Optional
from dataclasses import dataclass

@dataclass
class StepRecord:
    step_type: str      # registry | service | appx | command | file
    target: str         # e.g. r"HKLM\SOFTWARE\...\AllowTelemetry"
    before_value: Any   # JSON-serialisable
    after_value: Any

@dataclass
class RestoreResult:
    success: bool
    partial: bool                    # True if some steps failed
    failed_steps: List[str]          # list of step IDs that failed
    errors: List[str]                # human-readable error per failure

class BackupService:
    def create_restore_point(self, label: str, module: str) -> str:
        """Create restore point folder + DB row. Returns restore_point_id (uuid4)."""

    def record_steps(self, tweak_id: str, steps: List[StepRecord],
                     restore_point_id: str) -> None:
        """Insert one tweak_steps row per StepRecord. Called after apply succeeds."""

    def backup_registry_key(self, key_path: str, restore_point_id: str) -> None:
        """Export registry key to .reg via `reg export`. Called before apply."""

    def backup_service_state(self, service_name: str, restore_point_id: str) -> None:
        """Save service start_type + state JSON. Called before apply."""

    def backup_appx_package(self, package_full_name: str,
                            restore_point_id: str) -> None:
        """Record removed AppX package name in removed_apps.json.
        NOTE: AppX removal is not fully reversible — restore attempts
        winget install or Store reinstall but cannot guarantee success.
        Callers must surface a permanent warning in UI for AppX tweaks."""

    def restore_point(self, restore_point_id: str) -> RestoreResult:
        """Restore all steps in a restore point independently.
        Each step is attempted regardless of prior failures.
        Updates restore_points.status to 'restored' or 'partial'.
        Never raises — all errors captured in RestoreResult."""

    def revert_step(self, step_id: str) -> bool:
        """Revert a single step. Dispatches by step_type:
          registry → reg import .reg file
          service  → win32service.SetServiceStart(before_value)
          appx     → winget install / Store (best-effort, warns user)
          command  → not revertible (logs warning)
          file     → copy backup file back to original path
        Returns True on success."""

    def list_restore_points(self) -> List[RestorePointInfo]:
        """All restore points newest-first with step count."""

    def close(self) -> None:
        """Commit and close SQLite connection."""
```

**Partial restore behaviour (B2 fix):** `restore_point()` iterates all steps, catches exceptions per step, never stops early. If any step fails: `RestoreResult(success=False, partial=True, failed_steps=[...])`. Caller (Restore Manager UI) shows a warning: "N of M steps restored successfully. Failed steps: [list]. Manual intervention may be required." DB `status` set to `'partial'` so the restore point is not shown as cleanly restored.

### 3.3 Restore Manager UI

Accessible via **Tools → Restore Manager** in the main menu bar:
- Table: label | date | module | step count | status
- Expand row → list of individual steps with step_type, target, before/after values
- "Restore All" per session → calls `restore_point()`, shows `RestoreResult` dialog
- "Revert" per step → calls `revert_step()`
- Delete restore point (with confirm)

---

## 4. Module Designs

### 4.1 Tweaks & Debloater

**File structure:**
```
modules/tweaks/
  __init__.py
  tweaks_module.py
  tweak_engine.py
  tweak_search_provider.py
  app_catalog.py             <- installable app catalog + detection
  preset_manager.py          <- export/import preset logic
  definitions/
    privacy.json
    performance.json
    telemetry.json
    ui_tweaks.json
    services.json
    app_catalog.json         <- curated installable app list
```

**Tweak definition format** (B3 fix — `undo_steps` removed; `BackupService` is the sole undo mechanism):
```json
{
  "id": "disable_telemetry",
  "name": "Disable Telemetry",
  "description": "Sets DiagTrack service to disabled and clears telemetry registry keys.",
  "category": "Privacy",
  "risk": "low",
  "requires_admin": true,
  "steps": [
    {
      "type": "registry",
      "key": "HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection",
      "value": "AllowTelemetry",
      "data": 0,
      "kind": "DWORD"
    },
    {
      "type": "service",
      "name": "DiagTrack",
      "start_type": "disabled"
    }
  ]
}
```
All AppX-removal tweaks must have `"risk": "high"` and a `"warning"` field:
```json
{
  "id": "remove_onedrive",
  "risk": "high",
  "warning": "Removal may not be fully reversible. OneDrive can be reinstalled via the Microsoft Store."
}
```

**TweakEngine apply flow:**
1. `app.backup.create_restore_point(label, "Tweaks")` → `rp_id`
2. For each step: call `backup_registry_key` / `backup_service_state` / `backup_appx_package` as appropriate
3. Apply each step via `winreg` / `win32service` / `subprocess`
4. Call `app.backup.record_steps(tweak_id, step_records, rp_id)` on success
5. On any failure: surface error, mark restore point partial

**UI tabs: Privacy | Performance | Apps | UI Tweaks | Services | Telemetry**

Each tweak tab (Privacy, Performance, UI Tweaks, Services, Telemetry):
- Scrollable list of `TweakRow` — checkbox, name, risk badge, current status (Applied / Not Applied / Unknown), description tooltip
- Bottom bar: "Apply Selected (N)" + progress bar + "Restore Manager" link
- Status detected on activate (reads live registry/service state vs tweak target)
- **Preset toolbar above all tabs**: `Preset: [Name v] [Load] [Save As...] [Export...] [Import...]`

**Telemetry tab** (dedicated, expanded):
- Disable DiagTrack, utcsvc, AllowTelemetry=0, AllowDeviceNameInTelemetry=0
- Disable Connected User Experiences, CEIP, Error Reporting (WerSvc), Inventory Collector
- Optional: block telemetry domains via HOSTS file entries (toggleable, backed up first)

`group = ModuleGroup.OPTIMIZE`

---

#### Apps Tab — Full App Manager

Replaces static Bloatware list with a live, interactive app manager.

**Layout (wireframe):**
```
Preset toolbar (shared, above all tabs)
--------------------------------------------------------------
Search: [___________]  Category: [All v]  Show: [All v]

INSTALLED (detected on this machine)
  [x] 3D Viewer       Microsoft    Installed     risk:high
  [x] Cortana         Microsoft    Installed     risk:high
  [ ] OneDrive        Microsoft    Installed     PROTECTED
  [x] Xbox Game Bar   Microsoft    Installed     risk:high

AVAILABLE TO INSTALL (winget catalog)
  [ ] 7-Zip           7-Zip        Not installed
  [x] VLC             VideoLAN     Not installed
  [ ] VS Code         Microsoft    INSTALLED
  [x] Notepad++       Notepad++    Not installed

[Apply Changes: remove 3, install 2]  [Reset All]
```

**Installed apps section:**
- Sources: `Get-AppxPackage` (AppX) + registry Uninstall keys (Win32)
- Checked = queued for removal; unchecked = leave alone
- 🔒 Protected apps: checkbox disabled, cannot be queued
- Right-click → "Protect from removal" / "Remove protection"
- Protection stored in config: `tweaks.protected_apps: ["Microsoft.OneDriveSync", ...]`

**Installable catalog (`app_catalog.json`):**
```json
{"id":"vlc","name":"VLC Media Player","publisher":"VideoLAN",
 "category":"Media","winget_id":"VideoLAN.VLC",
 "description":"Free open-source multimedia player."}
```
Detection on activate: `winget list` → already-installed catalog apps show ✅, checkbox disabled.

Categories: Browsers | Development | Media | Productivity | System Tools | Security | Utilities | Communication

**Initial catalog:**
- Browsers: Firefox, Brave, Chrome
- Development: VS Code, Git, Windows Terminal, Python, Node.js, Docker Desktop
- Media: VLC, Spotify, Audacity, HandBrake
- Productivity: LibreOffice, Obsidian, Notion
- System Tools: 7-Zip, CPU-Z, HWMonitor, CrystalDiskInfo, TreeSize Free
- Security: Malwarebytes, Bitwarden, KeePassXC
- Utilities: Notepad++, Everything, Greenshot, ShareX, WinSCP, PuTTY

**Apply Changes flow:**
1. Backup all AppX packages being removed via `backup_appx_package()`
2. Each removal: `winget uninstall <id>` or `Remove-AppxPackage` — streamed to log panel
3. Each install: `winget install <id> --silent --accept-package-agreements` — streamed
4. Progress bar: N/M operations complete

---

#### Preset System

**Preset toolbar** sits above all tabs, always visible. Scope covers all tabs simultaneously.

**Preset format:**
```json
{
  "name": "Corporate Standard", "version": 1, "created": "2026-03-25T14:32:00",
  "tweaks": {
    "privacy":     ["disable_location", "disable_ad_id"],
    "performance": ["disable_superfetch", "high_perf_power_plan"],
    "telemetry":   ["disable_diagtrack", "disable_utcsvc", "telemetry_zero"],
    "ui_tweaks":   ["show_file_extensions", "show_hidden_files"],
    "services":    ["disable_remote_registry"]
  },
  "apps": {
    "remove":    ["Microsoft.3DViewer", "Microsoft.XboxGameBar"],
    "install":   ["VideoLAN.VLC", "7zip.7zip"],
    "protected": ["Microsoft.OneDriveSync", "Microsoft.Office.OneNote"]
  }
}
```

**Actions:**
- **Load**: populates all checkboxes from preset — does NOT apply, user reviews then clicks Apply
- **Save As**: saves current state across all tabs as named preset
- **Export**: scope dialog — "This tab only" | "All tabs" | "Full (tweaks + apps)" → `.json` or `.zip`
- **Import**: imports `.json` or `.zip`; appears in dropdown immediately
- **Delete**: removes user preset (built-ins protected)

**Built-in read-only presets:**
- `Minimal` — telemetry off only, no app changes
- `Privacy Focused` — all privacy + telemetry tweaks, no app changes
- `Developer Machine` — VS Code, Git, Windows Terminal, 7-Zip installed; telemetry off; WSL enabled
- `Corporate Hardened` — telemetry off, remote registry off, delivery optimization off, no consumer apps

**Protected apps in presets:** Any `remove` entry matching the user's protected list is skipped with a notification: "OneDrive is protected on this machine and was excluded from the removal queue."

**Storage:**
```
%APPDATA%/WindowsTweaker/presets/       <- user presets
src/modules/tweaks/definitions/builtins/ <- built-in read-only presets
```

---

**Full tweak library:**
- Privacy: Activity history, location, advertising ID, app diagnostics, suggested content, tips/tricks, app launch tracking, Cortana web search, Bing in Start Menu, background app access
- Performance: Superfetch/SysMain, high perf power plan, Search indexing, visual effects, transparency, adjust for best performance
- Telemetry: DiagTrack, utcsvc, AllowTelemetry=0, CEIP, Error Reporting, Inventory Collector, Application Compatibility, optional HOSTS block
- UI Tweaks: Dark mode, file extensions, hidden files, taskbar News/Weather, classic right-click (Win11), Snap suggestions, Chat/Meet Now icons, search highlights
- Services: Delivery optimization, Remote Registry, Print Spooler (optional), Fax, Bluetooth (optional), Xbox services (XboxGipSvc, XblAuthManager, XblGameSave, XboxNetApiSvc)

### 4.2 Cleanup

**Tabs:** Temp Files | Browser Caches | Windows Update Cache | Prefetch | Recycle Bin | Event Log Cleanup

**Each tab pattern:**
1. "Scan" → worker thread scans, populates tree with item + size
2. Checkboxes for selection (all selected by default)
3. "Clean Selected" → deletes, shows before/after size summary
4. Right-click folder → "Open in TreeSize"

**Windows Update Cache tab** (I8 fix): stopping and restarting `wuauserv` uses a context manager:
```python
class _ServiceStopped:
    def __init__(self, name): self.name = name
    def __enter__(self): win32serviceutil.StopService(self.name)
    def __exit__(self, *_): win32serviceutil.StartService(self.name)  # always runs

with _ServiceStopped("wuauserv"):
    # delete SoftwareDistribution\Download contents
```
This guarantees the service is restarted even if deletion raises an exception.

**Scan targets:**
- Temp Files: `%TEMP%`, `C:\Windows\Temp`
- Browser Caches: Chrome, Edge, Firefox cache directories (detected by well-known paths)
- Windows Update Cache: `C:\Windows\SoftwareDistribution\Download`
- Prefetch: `C:\Windows\Prefetch\*.pf`
- Recycle Bin: per-drive `$Recycle.Bin`
- Event Log Cleanup: `.evtx` files in `C:\Windows\System32\winevt\Logs\`, clear selected logs

`group = ModuleGroup.OPTIMIZE`

### 4.3 TreeSize (Standalone Tab)

**Widget:** `QTreeView` with `DiskTreeModel(QAbstractItemModel)`

**Columns:** Name | Size | % of Parent (inline bar) | Files | Last Modified

**Scan engine + threading** (I3 fix):
- `DiskScanner` runs on a `Worker` thread via `QThreadPool`
- `WorkerSignals` gains a `batch_ready = pyqtSignal(list)` signal alongside existing `progress`/`result`/`error`
- Scanner emits `batch_ready` every 500 nodes with a list of `DiskNode` objects
- `DiskTreeModel` receives batches on the main thread via Qt signal dispatch, calls `beginInsertRows()`/`endInsertRows()` per batch — never mutated from the worker thread
- Sort updates call `layoutAboutToBeChanged()`/`layoutChanged()`, not a full model reset
- Batch size: 500 nodes balances UI responsiveness vs signal overhead

**Size column:** custom `QStyledItemDelegate` renders inline bar — blue for folders, grey for files, orange >1 GB, red >10 GB

**Features:**
- Drive selector dropdown (all drives) + "Scan" / "Stop" button + progress bar
- Double-click drills into folder; breadcrumb bar for navigation
- Context menu: Open in Explorer | Add to Cleanup Queue | Delete (with confirm) | Properties
- Filter bar: show only items > N MB
- Export to CSV
- `group = ModuleGroup.TOOLS` (standalone, not nested under Cleanup)

### 4.4 Performance Tuner

Checklist of best-practice items, categories: Visual Effects | Power | Memory & Paging | Storage | Network | Background Services

Each item: name, description, current state (✅ Optimal / ⚠ Suboptimal / ❓ Unknown), recommended action, Apply/Revert per item. "Apply All Recommended" at bottom.

Backed by `TweakEngine` + `BackupService`. `group = ModuleGroup.OPTIMIZE`

---

### 4.5 Hardware & System Inventory

**Tabs:** Overview | CPU | Memory | Storage | GPU | Network Adapters | Displays | USB | BIOS/Firmware

**Data sources:**
- `psutil`: CPU, RAM, disk, network
- WMI `root\cimv2`: `Win32_ComputerSystem`, `Win32_Processor`, `Win32_PhysicalMemory`, `Win32_VideoController`, `Win32_DiskDrive`, `Win32_BIOS`
- S.M.A.R.T.: `MSStorageDriver_FailurePredictData` — **must use `wmi.WMI(namespace=r"root\wmi")`** not `root\cimv2` (M3 fix)

**Overview:** Hostname, OS + Build, Uptime, Domain/Workgroup, Activation Status (`slmgr.vbs /dli`), CPU model, RAM total, storage total/free.

**Export:** "Export Report" → HTML file. `group = ModuleGroup.SYSTEM`

### 4.6 Network Diagnostics

Single-page collapsible tool cards:

- **Ping:** hostname/IP, count, results table (TTL, latency, loss%)
- **Traceroute:** `subprocess tracert`, hop table
- **DNS Lookup:** `socket` + `subprocess nslookup`, record type selector
- **Port Scanner** (I4 fix): uses `concurrent.futures.ThreadPoolExecutor(max_workers=100)`, each thread calls `socket.connect_ex` with `socket.settimeout(0.5)`. Worker checks `is_cancelled()` between batches. UI caps range to 10,000 ports. Progress emitted per batch of 100 ports.
- **Active Connections:** `psutil.net_connections()`, auto-refresh every 5s
- **WiFi Profiles:** `subprocess netsh wlan show profiles`
- **Adapter Info:** `psutil.net_if_addrs()` + WMI

`group = ModuleGroup.SYSTEM`

### 4.7 Windows Security Dashboard

Read-only diagnostic. Four status cards:

1. **Windows Defender:** via WMI `MSFT_MpComputerStatus` in `root\Microsoft\Windows\Defender` namespace
2. **Firewall:** via `win32com.client` `HNetCfg.FwMgr`
3. **BitLocker:** via WMI **`wmi.WMI(namespace=r"root\cimv2\Security\MicrosoftVolumeEncryption")`** — `Win32_EncryptableVolume` (M4 fix). Requires admin.
4. **Secure Boot & TPM:**
   - Secure Boot: PowerShell `Confirm-SecureBootUEFI`. **If process exits non-zero or stderr contains "Cmdlet not supported", display "N/A (BIOS/Legacy system)"** rather than a health indicator (M5 fix)
   - TPM: WMI `Win32_Tpm` in `root\cimv2\Security\MicrosoftTpm`

Each card green/amber/red. Summary health banner at top. `group = ModuleGroup.SYSTEM`

### 4.8 Driver Manager

Table: Device Name | Class | Version | Date | Publisher | Signed | Status

Data: WMI `Win32_PnPSignedDriver` (`root\cimv2`). Flags: 🔴 unsigned, 🟠 date > 2 years, 🔴 `ConfigManagerErrorCode != 0`.

Actions: Export CSV | Open Device Manager (`devmgmt.msc`). `group = ModuleGroup.SYSTEM`

### 4.9 Startup Manager

Five tabs: Registry | Scheduled Tasks | Startup Folder | Services | Browser Extensions (read-only)

**Enable/Disable mechanisms:**
- Registry: `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run` — set `03 00 00 00...` (disabled) / `02 00 00 00...` (enabled). Same mechanism used by Task Manager. (M6 fix — do NOT move files)
- Startup Folder: `HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder` — same byte pattern
- Scheduled Tasks: `win32com Schedule.Service` to enable/disable (locale-safe)
- Services: `win32service` start type change

All changes backed up via `BackupService` before apply. `group = ModuleGroup.MANAGE`

### 4.10 Scheduled Tasks Viewer

Tree (left: task folder hierarchy) + detail panel (right).

**Data source:** `win32com.client.Dispatch("Schedule.Service")` — locale-independent, structured (M11 fix). `schtasks` CLI is a fallback only and must not be used as primary source due to locale-dependent output.

Table: Name | Status | Last Run | Last Result | Next Run | Author | Triggers

Actions: Enable | Disable | Run Now | Delete | Export XML | Open Task Scheduler (`taskschd.msc`)

Double-click → full XML in read-only code view. `group = ModuleGroup.MANAGE`

### 4.11 Windows Features Manager

Feature tree (left, from `dism /online /get-features /format:table`) + description + state (right).

Common features pinned: Hyper-V, WSL, Windows Sandbox, IIS, Telnet, TFTP, NFS, DirectPlay.

Enable/Disable via `dism` on worker thread, streams output. Requires admin.

**Reboot check** uses shared `is_reboot_pending()` from `core/windows_utils.py` (see section 9). `group = ModuleGroup.MANAGE`

### 4.12 Certificate Viewer

Tabs: Personal | Computer | Trusted Root | Intermediate CAs

Table: Subject CN | Issuer | Expiry | Thumbprint | Key Usage | Has Private Key. Flags: 🔴 Expired | 🟠 Expiring ≤30 days.

Actions: Export `.cer` | View detail via `cryptui.dll`. Data via `ssl` + `wincertstore`. `group = ModuleGroup.MANAGE`

### 4.13 GPResult Viewer

Runs `gpresult /x` on worker thread. (I6 fix):
- Temp file path: `os.path.join(tempfile.gettempdir(), f"wt_gpresult_{uuid.uuid4().hex}.xml")`
- File deleted in `finally` block after parse
- Per-module `threading.Lock` prevents concurrent runs; second click while running is a no-op with a status message

Two sections: Computer Config | User Config. Each: list of applied GPOs + expandable settings tree. Last refresh time, DC name, site.

Export HTML: `gpresult /h <path>` + open in browser. `group = ModuleGroup.MANAGE`

### 4.14 Updates Module

**COM threading requirement (B4 fix):** Any worker that uses `win32com.client` COM objects (`Microsoft.Update.Session`, `Schedule.Service`) **must** call:
```python
import pythoncom
pythoncom.CoInitialize()        # at top of worker thread function
try:
    # ... COM calls ...
finally:
    pythoncom.CoUninitialize()  # always runs
```
A `COMWorker` subclass of `Worker` in `core/worker.py` wraps `run()` with this pattern so callers don't need to repeat it. Both `windows_updater.py` and `tasks_reader.py` use `COMWorker`.

**Tab 1 — Application Updates:**
- `winget upgrade --include-unknown` → parse output
- Grid: Name | ID | Installed Ver | Available Ver | Publisher | Source
- Badges: 🟢 Up to date | 🟠 Update available | ⚪ Unknown
- "Update Selected" / "Update All" → streams `winget upgrade <id>` output

**Tab 2 — Windows Updates:**
- `Microsoft.Update.Session` COM (via `COMWorker`)
- Pending updates: KB, Title, Classification, Severity, Size, Release Date
- Recently installed (last 30 days) in collapsible section
- "Install Selected" → download + install via COM, progress per update
- **Reboot banner** checks all three keys via `is_reboot_pending()` (M7 fix — see section 9)

**Tab 3 — Schedule:**
- Task Scheduler job config for auto app + system update checks
- Time, frequency, scope, notify vs auto-install

`group = ModuleGroup.TOOLS`

### 4.15 Quick Fix Toolkit

One-click fix grid. Each fix: description, reboot-required indicator, streaming output panel.

**System Repairs:** SFC scan, DISM restore health, CHKDSK (schedule)
**Cache & UI:** Rebuild icon cache, clear thumbnail cache, restart Explorer, re-register DLLs
**Network:** Flush DNS, reset Winsock (reboot needed), reset TCP/IP (reboot needed), IP release/renew
**Windows Update:** Stop WU services → clear cache → restart services; re-register WU DLLs
**Print:** Clear print queue (stop Spooler → delete spool files → start Spooler)

All `is_reboot_pending()` checks use the shared util. `group = ModuleGroup.TOOLS`

### 4.16 Power & Boot Manager

**Power tab:** power plan selector + set active; toggles: Fast Startup, Hibernate, Sleep, USB Selective Suspend; sleep timeouts. Via `powercfg.exe`.
**Boot tab:** `bcdedit /enum` read-only table; boot timeout; safe mode entry toggle; open Advanced Startup. All boot changes: export `bcdedit /export <backup_path>` first.

Uses `is_reboot_pending()` for banner. `group = ModuleGroup.TOOLS`

### 4.17 Network Extras

Four tools:

- **HOSTS File Editor:** `C:\Windows\System32\drivers\etc\hosts` as editable IP|Hostname|Comment table. Backup before save. Requires admin.
- **DNS Server Switcher:** per-adapter presets (Google, Cloudflare, Quad9, OpenDNS, custom) via `netsh interface ip set dns`. Backup previous DNS before change.
- **Proxy Settings:** view/set via `winreg` HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings.
- **Quick Network Actions:** Flush DNS, Reset Winsock, IP Release/Renew, Disable/Enable adapter.

`group = ModuleGroup.TOOLS`

### 4.18 Shared Resources

Three tabs: Network Shares (`win32net.NetShareEnum`) | Connected Sessions (`win32net.NetSessionEnum`) | Mapped Drives (`win32wnet.WNetEnumResource`). `group = ModuleGroup.TOOLS`

### 4.19 Environment Variables

Two panels: System | User. Table: Name | Value | Scope.

Actions: Add | Edit | Delete | Duplicate to other scope.

Written via `winreg`. After save, broadcasts environment change (I7 fix — exact call):
```python
import ctypes
# lParam must be the string "Environment" — required for Explorer + apps to refresh
ctypes.windll.user32.SendMessageTimeoutW(
    0xFFFF,       # HWND_BROADCAST
    0x001A,       # WM_SETTINGCHANGE
    0,
    "Environment",
    0x0002,       # SMTO_ABORTIFHUNG
    5000,
    None
)
```
Backup exports both env var registry keys before any modification. `group = ModuleGroup.TOOLS`

### 4.20 Registry Explorer

`QTreeView` + `QAbstractItemModel` for hives: HKLM | HKCU | HKCR | HKU | HKCC.

Click key → values in right panel (Name | Type | Data).

**Search** (M8 fix): worker thread catches `PermissionError` per key, logs skipped path, continues. Search result summary shows "N keys skipped due to access restrictions."

Features: favourites, quick-nav to common keys, export `.reg`, copy path. Read-only in this version. `group = ModuleGroup.TOOLS`

### 4.21 Software Inventory

Sources: `HKLM\SOFTWARE\...\Uninstall` (64-bit), `HKLM\SOFTWARE\WOW6432Node\...\Uninstall` (32-bit), `winget list`. Merged + deduplicated.

Table: Name | Version | Publisher | Install Date | Size | Type | Source. Uninstall button + export CSV. `group = ModuleGroup.TOOLS`

### 4.22 Remote Tools Launcher

- RDP → `mstsc /v:hostname`
- WinRS → `winrs -r:hostname command` streamed
- PSExec → streamed (if installed)
- Ping Sweep → `concurrent.futures` + `subprocess ping`, results table
- **Wake-on-LAN** (M10 fix): MAC input + **Broadcast IP input** (default `255.255.255.255`; directed broadcast like `192.168.1.255` required for cross-VLAN WOL) → UDP magic packet on port 9
- Hostname history saved in config

`group = ModuleGroup.TOOLS`

---

## 5. File Structure

```
src/
  core/
    backup_service.py          ← new: BackupService + RestoreResult + StepRecord
    module_groups.py           ← new: ModuleGroup constants
    windows_utils.py           ← new: is_reboot_pending(), shared helpers
    worker.py                  ← updated: add COMWorker subclass
    base_module.py             ← updated: add group: str class attribute
  ui/
    sidebar_nav.py             ← new: replaces QTabWidget
  modules/
    tweaks/
      __init__.py
      tweaks_module.py
      tweak_engine.py
      tweak_search_provider.py
      app_catalog.py
      preset_manager.py
      definitions/
        privacy.json
        performance.json
        telemetry.json
        ui_tweaks.json
        services.json
        app_catalog.json
        builtins/
          minimal.json
          privacy_focused.json
          developer_machine.json
          corporate_hardened.json
    cleanup/
      __init__.py
      cleanup_module.py
      cleanup_scanner.py
      cleanup_search_provider.py
    treesize/
      __init__.py
      treesize_module.py
      disk_tree_model.py
      disk_scanner.py
    performance_tuner/
      __init__.py
      perf_tuner_module.py
      perf_checks.py
    hardware_inventory/
      __init__.py
      hardware_module.py
      hardware_reader.py
    network_diagnostics/
      __init__.py
      network_module.py
      network_tools.py
    security_dashboard/
      __init__.py
      security_module.py
      security_reader.py
    driver_manager/
      __init__.py
      driver_module.py
      driver_reader.py
    startup_manager/
      __init__.py
      startup_module.py
      startup_reader.py
    scheduled_tasks/
      __init__.py
      tasks_module.py
      tasks_reader.py
    windows_features/
      __init__.py
      features_module.py
    certificate_viewer/
      __init__.py
      cert_module.py
      cert_reader.py
    gpresult/
      __init__.py
      gpresult_module.py
    updates/
      __init__.py
      updates_module.py
      winget_updater.py
      windows_updater.py       ← uses COMWorker
    quick_fix/
      __init__.py
      quick_fix_module.py
      fix_actions.py
    power_boot/
      __init__.py
      power_module.py
    network_extras/
      __init__.py
      net_extras_module.py
    shared_resources/
      __init__.py
      shares_module.py
    env_vars/
      __init__.py
      env_vars_module.py
    registry_explorer/
      __init__.py
      registry_module.py
      registry_model.py
    software_inventory/
      __init__.py
      software_module.py
    remote_tools/
      __init__.py
      remote_module.py
    process_explorer/
      __init__.py              ← placeholder tab only
```

---

## 6. Technology Choices

| Need | Library |
|---|---|
| Registry read/write | `winreg` (stdlib) |
| Services | `win32service`, `win32serviceutil` (pywin32) |
| WMI queries | `wmi` — namespace varies per query (see section 4) |
| Process info | `psutil` |
| Network tools | `socket`, `psutil.net_*`, `subprocess`, `concurrent.futures` |
| Windows Update COM | `win32com.client` (`Microsoft.Update.Session`) via `COMWorker` |
| Winget integration | `subprocess` (stream stdout) |
| Task Scheduler | `win32com.client` (`Schedule.Service`) via `COMWorker` |
| Firewall | `win32com.client` (`HNetCfg.FwMgr`) |
| Certificates | `ssl`, `wincertstore` |
| Disk scanning | `os.scandir` |
| SQLite (backup DB) | `sqlite3` (stdlib) |
| Temp files | `tempfile` (stdlib) |
| Threading utils | `threading.Lock` (per-module mutex where needed) |
| COM threading | `pythoncom.CoInitialize/CoUninitialize` via `COMWorker` |

---

## 7. Implementation Batches

**Batch A — Foundation + High Value:**
`core/module_groups.py`, `core/windows_utils.py`, `core/backup_service.py`, `COMWorker` in `worker.py`, `SidebarNav` + `MainWindow` shell redesign, Tweaks/Debloater, Cleanup, TreeSize, Quick Fix Toolkit, Updates module

**Batch B — System & Manage:**
Hardware Inventory, Network Diagnostics, Security Dashboard, Driver Manager, Startup Manager, Scheduled Tasks, Windows Features, GPResult, Certificate Viewer

**Batch C — Tools:**
Performance Tuner, Power & Boot, Network Extras, Shared Resources, Environment Variables, Registry Explorer, Software Inventory, Remote Tools Launcher, Process Explorer (full — Sub-project 3)

---

## 8. Constraints & Non-Goals

- **No cloud sync** in this sub-project (AI/Learning sub-project)
- **No remote management** beyond launchers
- **Registry Explorer is read-only** in this version
- **Process Explorer** is a placeholder — full implementation is Sub-project 3
- All `requires_admin = True` modules shown greyed in sidebar when not elevated

---

## 9. Shared Utilities (`core/windows_utils.py`)

```python
import winreg

def is_reboot_pending() -> bool:
    """Check all three Windows reboot-pending indicators."""
    keys = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SYSTEM\CurrentControlSet\Control\Session Manager",
         "PendingFileRenameOperations"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing",
         "RebootPending"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update",
         "RebootRequired"),
    ]
    for hive, path, value in keys:
        try:
            with winreg.OpenKey(hive, path) as k:
                winreg.QueryValueEx(k, value)
                return True
        except OSError:
            continue
    return False
```

Used by: Windows Features (4.11), Updates (4.14), Quick Fix (4.15), Power & Boot (4.16).
