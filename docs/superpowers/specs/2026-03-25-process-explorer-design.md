# Process Explorer — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** #3 — Process Explorer
**Date:** 2026-03-25
**Status:** Approved
**Target users:** IT professionals, sysadmins, field engineers

---

## 1. Overview

A native PyQt6 process explorer providing Sysinternals-level depth: real-time process tree with metrics, six lower-pane detail views, a full multi-tab properties dialog, VirusTotal hash-check with optional file submission, full process manipulation actions, and a Sysinternals Live launcher tab for direct access to the broader Sysinternals suite.

Implemented as a standard `BaseModule` with `group = ModuleGroup.PROCESS` — a new group constant added to `core/module_groups.py`, rendered last in the sidebar nav.

---

## 2. Layout

Two-pane layout — upper process tree, lower detail pane, splitter-resizable:

```
┌─────────────────────────────────────────────────────────────────┐
│ [Kill] [Suspend] [Priority▼] [Affinity] │ [🔍 Search___] [⚙▼]  │
├──────────────────┬──────┬──────┬──────┬──────┬──────┬──────────┤
│ Process Name     │ PID  │ CPU% │ RAM  │ Disk │ Net  │ GPU  │ … │
├──────────────────┼──────┼──────┼──────┼──────┼──────┼──────────┤
│ ▼ System              0.0    0.1MB                              │
│   smss.exe       480   0.0    0.5MB              SYSTEM         │
│ ▼ Services            1.2    45MB                               │
│   svchost.exe   1200   0.5    8MB               NETWORK SVC     │
│ ▼ My Processes        5.2   120MB                               │
│  ▼ explorer.exe 2048   0.2    15MB              iorda            │
│    chrome.exe   3200   3.0    80MB              iorda            │
├──────────────────────────────────────────────────────────────────┤
│ [DLLs] [Handles] [Threads] [Network] [Strings] [Memory Map]     │
│  Name           │ Path                   │ Base Addr │ Size │ VT│
│  ntdll.dll      │ C:\Windows\System32\…  │ 0x77A0000 │ 1.4M │ ✓ │
└──────────────────────────────────────────────────────────────────┘
```

**Toolbar:** Kill | Suspend | Priority▼ | Affinity | Search bar | Options▼ (refresh interval, tree/flat toggle, column visibility).

**Tree vs Flat toggle:** Tree mode (default) shows parent/child hierarchy. Flat mode shows all processes sorted by any column. Toggle in toolbar.

**Module-level tabs:** The Process Explorer module has two top-level views, selected via a tab bar at the top of the module widget:
- **Processes** (default) — the two-pane process tree + lower detail pane layout shown above
- **Sysinternals** — the Sysinternals Live launcher (Section 8)

---

## 3. Process Tree Model & Data Collection

### 3.1 ProcessNode

```python
@dataclass
class ProcessNode:
    pid: int
    name: str
    exe: str               # full image path — shown as default-visible column
    cmdline: str
    user: str
    status: str            # running | sleeping | stopped | zombie
    parent_pid: int
    children: list['ProcessNode']
    # Metrics
    cpu_percent: float
    memory_rss: int        # bytes
    memory_vms: int
    disk_read_bps: float
    disk_write_bps: float
    net_send_bps: float
    net_recv_bps: float
    gpu_percent: float     # 0.0 if unavailable
    # Classification
    is_system: bool
    is_service: bool
    is_dotnet: bool
    is_suspended: bool
    integrity_level: str   # Low | Medium | High | System
    # VirusTotal (populated on demand)
    sha256: str | None
    vt_score: str | None   # e.g. "3/72" | "0/72" | None
```

### 3.2 ProcessCollector (Worker Thread)

Runs on a `Worker` thread. Each tick (default 1s, configurable 0.5s–5s):

1. `psutil.process_iter([...])` — single call with all required attrs, uses psutil attribute cache
2. Build parent→children tree from `ppid`; orphaned processes attach to PID 0 (root)
3. GPU %: WMI `Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine` polled every 3s (expensive — separate slower ticker), merged into nodes by PID
4. Classify:
   - `is_system`: user in `{'SYSTEM','LOCAL SERVICE','NETWORK SERVICE'}` or PID ≤ 8
   - `is_service`: name in SCM service list fetched once at startup via `win32service.EnumServicesStatus`
   - `is_dotnet`: CLR DLL present in module list (sampled, not per-tick)
5. Diff against previous snapshot → emit `process_added(ProcessNode)`, `process_removed(int)`, `processes_updated(list[ProcessNode])`

### 3.3 ProcessTreeModel

`QAbstractItemModel` backed by `ProcessNode` tree:

- `index()`, `parent()`, `rowCount()`, `columnCount()`, `data()` — standard implementation
- Receives diff signals on main thread: `beginInsertRows`/`endInsertRows`, `beginRemoveRows`/`endRemoveRows`, `dataChanged` — no full redraws
- Selection and scroll position preserved across refreshes
- `sort()` works in tree mode (sorts children within each parent) and flat mode (global)

**Default-visible columns:** Name | PID | CPU% | RAM | Disk R/W | Net In/Out | GPU% | User | Path

**Additional columns (toggle via column menu):** Virtual Memory | Integrity | Description | Company | Session ID | Handles | Threads

### 3.4 Color Coding

| Color | Meaning |
|---|---|
| Dark blue | System processes (SYSTEM user or PID ≤ 8) |
| Pink | Windows Services |
| Yellow | .NET managed processes |
| Light purple | GPU-active processes |
| Grey | Suspended |
| Green flash → normal | Newly appeared process |
| Default | Own user processes |

---

## 4. Lower Pane

Six lazy-loaded tabs — data fetched only when the tab is active and a process is selected.

### 4.1 DLLs Tab

`psapi.EnumProcessModules` via ctypes.

**Columns:** Name | Full Path | Base Address | Size | Company | Version | VT Score

VT Score column empty until user right-clicks a DLL → "Check VirusTotal" (same hash-check + optional submission flow as processes).

### 4.2 Handles Tab

`NtQuerySystemInformation(SystemHandleInformation)` filtered to selected PID.

**Columns:** Type | Name | Handle Value | Object Address | Access Mask

Handle name resolution uses a 200ms per-handle timeout on a separate thread. Timed-out handles display `<resolving…>` then `<timeout>`. Handle types shown: File | Registry Key | Event | Mutex | Semaphore | Thread | Process | Section | Token | Port | Desktop | WindowStation.

### 4.3 Threads Tab

`psutil.Process.threads()` + Win32 `OpenThread` for extended info.

**Columns:** TID | CPU% | State | Priority | Start Address | Symbol | Wait Reason | Context Switches

Symbol resolved via `DbgHelp.dll` if available (e.g. `ntdll!NtWaitForSingleObject`). Double-click thread → mini stack trace dialog (requires debug privilege — greyed if not admin).

### 4.4 Network Tab

`psutil.net_connections()` filtered by PID. Auto-refreshes with main ticker.

**Columns:** Protocol | Local Address | Local Port | Remote Address | Remote Port | State

### 4.5 Strings Tab

Reads PE binary from `ProcessNode.exe` on a worker thread. Extracts printable sequences ≥ 4 chars. Two sub-tabs: **ASCII** and **Unicode**. Filter bar for in-results search. "Save to file" button. Cancellable — binaries >100MB show a warning before scanning.

**Memory strings toggle:** Scans live process memory via `ReadProcessMemory`. Requires admin. Off by default. Finds strings not present in the on-disk binary (packed/obfuscated content).

### 4.6 Memory Map Tab

`psutil.memory_maps(grouped=False)`.

**Columns:** Base Address | Size | Permissions (rwx) | Type (Image/Mapped/Private) | Path | RSS | Private Bytes

Row colors: green = executable, yellow = writable+executable (W^X flag), grey = private.

---

## 5. Process Properties Dialog

Double-click any process or right-click → Properties. Resizable `QDialog` with eight tabs.

| Tab | Content |
|---|---|
| **Image** | Full exe path (clickable → open folder), command line, working dir, parent PID (clickable → selects in tree), start time, user, session ID, integrity level, DEP/ASLR status |
| **Performance** | Scrolling CPU% + RAM charts (last 60s, same QChart approach as PerfMon), I/O bytes/sec, GPU% if applicable |
| **Threads** | Same as lower-pane Threads tab |
| **TCP/IP** | Same as lower-pane Network tab |
| **Security** | Token user, token groups (SID + name + attributes), privileges (name + enabled/disabled), integrity level, token type |
| **Environment** | Inherited env vars as Name \| Value table, searchable |
| **Strings** | Same as lower-pane Strings tab (ASCII + Unicode, memory strings toggle) |
| **Job** | If in a Job Object: job name, CPU/memory limits, active processes list. Hidden if process not in a job. |

---

## 6. VirusTotal Integration

### 6.1 Flow

1. Right-click process or DLL → "Check VirusTotal"
2. SHA256 hash computed from image file on worker thread (non-blocking)
3. `GET https://www.virustotal.com/api/v3/files/{hash}` with user's API key
4. **Found:** score shown as `3/72` with colour coding. Expandable vendor breakdown panel below.
5. **Not found (404):** prompt: *"This file is unknown to VirusTotal. Submit for analysis?"* with warning: *"This will upload the file binary to VirusTotal. Do not submit files containing sensitive data."* Confirm → `POST /files` multipart upload → poll every 10s up to 2 minutes.

### 6.2 Score Colours

| Score | Indicator |
|---|---|
| 0 detections | 🟢 0/N |
| 1–3 detections | 🟠 N/N |
| >3 detections | 🔴 N/N |

### 6.3 Config & Caching

- API key stored under `virustotal.api_key` in `ConfigManager`
- No key set → clicking "Check VirusTotal" opens settings to the VT key field with a note linking to the free API key signup page
- Results cached in memory for the session
- VT column in main tree: hidden by default, enabled automatically once any VT check is performed

---

## 7. Process Actions

Available via toolbar (enabled/disabled per selection) and right-click context menu:

| Action | Mechanism | Notes |
|---|---|---|
| Kill Process | `psutil.Process.kill()` | Confirm for system/service processes |
| Kill Process Tree | Kill process + all descendants | Confirm lists all PIDs |
| Suspend | `NtSuspendProcess` via ctypes | Row turns grey |
| Resume | `NtResumeProcess` via ctypes | |
| Set Priority | `psutil.Process.nice()` | 6 levels: Idle → Realtime. Realtime requires confirm |
| Set Affinity | `psutil.Process.cpu_affinity()` | Checkbox grid per logical core |
| Restart as Admin | `ShellExecute(runas, exe, cmdline)` | |
| Open File Location | `subprocess explorer /select,<exe>` | |
| Search Online | Opens browser: `"{name} process"` | |
| Copy | Name / PID / Path / Command Line | Submenu |

---

## 8. Sysinternals Live Tab

A dedicated tab within the Process Explorer module for browsing and launching tools from `\\live.sysinternals.com\tools\`.

### 8.1 Layout

```
[Search: ___________]  Category: [All ▼]  [Refresh Cache]

PROCESS TOOLS
  Process Explorer   Detailed process/thread viewer    [Launch] [Cache]  ✅ cached
  Process Monitor    File/registry/network activity    [Launch] [Cache]  ☁ live
  Autoruns           All autostart locations           [Launch] [Cache]  ☁ live
  PsExec             Remote process launcher           [Launch] [Cache]  ☁ live

NETWORK
  TCPView            Active TCP/UDP endpoints          [Launch] [Cache]  ✅ cached
  PsPing             Network latency/bandwidth         [Launch] [Cache]  ☁ live

SECURITY
  Sigcheck           File signature + VT check         [Launch] [Cache]  ✅ cached
  AccessChk          Object permissions viewer         [Launch] [Cache]  ☁ live
```

### 8.2 Launch Behaviour

- **Launch (☁ live):** `subprocess.Popen(r"\\live.sysinternals.com\tools\<tool>.exe")` — Windows WebDAV cache runs the binary transparently
- **Launch (✅ cached):** `subprocess.Popen(<local_cache_path>)`
- **Cache:** Copies binary from UNC path to `%APPDATA%\WindowsTweaker\sysinternals\<tool>.exe` for offline use

### 8.3 Status Indicators

| Indicator | Meaning |
|---|---|
| ✅ cached | Locally cached, available offline |
| ☁ live | Available via UNC (requires internet + WebClient service) |
| 🔴 unavailable | No internet and not cached |

### 8.4 WebDAV Prerequisite Check

On tab activate, check `WebClient` service status via `win32serviceutil.QueryServiceStatus`. If stopped → show banner: *"Sysinternals Live requires the WebClient service to be running."* with an inline "Start WebClient Service" button (requires admin).

### 8.5 Curated Tool List

| Category | Tools |
|---|---|
| Process | Process Explorer, Process Monitor, PsExec, PsKill, PsList, PsService, PsSuspend |
| Network | TCPView, PsPing, Whois |
| Security | Sigcheck, Autoruns, AccessChk, SDelete |
| File/Disk | Handle, Streams, Junction, DiskMon, DiskView, PendMoves |
| System Info | Coreinfo, RAMMap, VMMap, WinObj, BgInfo, ZoomIt |

---

## 9. File Structure

```
src/
  core/
    module_groups.py       ← add: ModuleGroup.PROCESS = "PROCESS"
  modules/
    process_explorer/
      __init__.py
      process_explorer_module.py   ← BaseModule, group = ModuleGroup.PROCESS
      process_tree_model.py        ← QAbstractItemModel (tree + flat mode)
      process_node.py              ← ProcessNode dataclass
      process_collector.py         ← Worker: psutil snapshot + diff + GPU poll
      process_actions.py           ← kill, suspend, priority, affinity
      virustotal_client.py         ← hash check + file submission + session cache
      color_scheme.py              ← process classification + row color logic
      lower_pane/
        __init__.py
        dll_view.py                ← EnumProcessModules via ctypes
        handle_view.py             ← NtQuerySystemInformation + timeout resolver
        thread_view.py             ← psutil.threads() + Win32 OpenThread
        network_view.py            ← psutil.net_connections() by PID
        strings_view.py            ← PE binary strings + memory strings toggle
        memory_map_view.py         ← psutil.memory_maps()
      properties_dialog.py         ← 8-tab QDialog
      sysinternals_tab.py          ← Sysinternals Live launcher + cache manager
```

---

## 10. Technology Choices

| Need | Library |
|---|---|
| Process list + metrics | `psutil` |
| DLL enumeration | `ctypes` → `psapi.EnumProcessModules` |
| Handle enumeration | `ctypes` → `NtQuerySystemInformation` |
| Thread details | `psutil` + `ctypes` → Win32 `OpenThread` |
| Suspend / Resume | `ctypes` → `NtSuspendProcess` / `NtResumeProcess` |
| Process affinity | `psutil.Process.cpu_affinity()` |
| GPU metrics | WMI `Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine` |
| Symbol resolution | `DbgHelp.dll` via ctypes (optional — graceful fallback) |
| Memory read (strings) | `ctypes` → `ReadProcessMemory` |
| SCM service list | `win32service.EnumServicesStatus` |
| WebClient service check | `win32serviceutil.QueryServiceStatus` |
| VirusTotal API | `requests` (already in project) |
| SHA256 hashing | `hashlib` (stdlib) |
| Sysinternals Live | `subprocess.Popen(UNC path)` |

---

## 11. Constraints & Non-Goals

- Registry Explorer remains read-only
- `.NET` assembly detail (AppDomains, loaded assemblies) requires debug API — deferred to a future enhancement, shown as "N/A" if unavailable
- Sysinternals Live tool list is hardcoded — no web scraping of live.sysinternals.com directory
- No remote process management (covered by Remote Tools Launcher module)
- No kernel driver — all data collection via documented Win32/NT APIs and psutil
