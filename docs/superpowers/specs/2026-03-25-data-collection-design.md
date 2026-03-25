# Data Collection & Analysis — Design Spec

**Project:** Windows 11 Tweaker/Optimizer
**Sub-project:** #2 — Data Collection & Analysis
**Date:** 2026-03-25
**Status:** Approved

---

## Overview

Seven data modules that plug into the existing framework via `BaseModule` ABC. Each reads a specific Windows data source, displays results in a searchable table, and integrates with the global search/filter system.

**Dependencies:** pywin32 (win32evtlog), wmi, psutil, pyqtgraph (for PerfMon graphs)

---

## Module 1: Event Viewer

**Data source:** Windows Event Logs via `win32evtlog` API

**Logs read:** System, Application, Security (Security requires admin)

**Features:**
- Table view: Time, Source, Event ID, Level (Error/Warning/Info), Message
- Auto-load last 24h of events on module activation
- Toolbar actions: Refresh, Export CSV, Clear Filters
- Color-coded rows: red for Error, orange for Warning
- Double-click row to see full event detail in a side panel
- Implements `SearchProvider` for global search integration
- Background loading via `Worker` to avoid UI freeze

**Log reading approach:** Use `win32evtlog.EvtQuery` (modern XML-based API) with XPath filter for time range. Falls back to `win32evtlog.ReadEventLog` (legacy) if needed. Read in batches of 500 to keep UI responsive.

---

## Module 2: CBS Log Parser

**Data source:** `C:\Windows\Logs\CBS\CBS.log`

**Format:** `YYYY-MM-DD HH:MM:SS, Level    CBS    Message`

**Features:**
- Parse CBS.log line by line with regex
- Table view: Time, Level (Info/Warning/Error), Component, Message
- Filter by level, highlight errors
- Large file handling: read in chunks, parse on worker thread
- Implements `SearchProvider`

---

## Module 3: DISM Log Parser

**Data source:** `C:\Windows\Logs\DISM\dism.log`

**Format:** Similar timestamped lines with level indicators

**Features:**
- Parse dism.log with regex
- Table view: Time, Level, Component, Message
- Highlight errors/warnings
- Worker thread for parsing
- Implements `SearchProvider`

---

## Module 4: Windows Update Log

**Data source:** `C:\Windows\SoftwareDistribution\ReportingEvents.log`

**Format:** Tab-separated fields: timestamp, type, source, status, details

**Features:**
- Parse ReportingEvents.log
- Table view: Time, Update Name, Status (Success/Fail/Pending), KB Number, Details
- Color: green for success, red for failure
- Implements `SearchProvider`

---

## Module 5: Reliability Monitor

**Data source:** WMI `Win32_ReliabilityRecords` in `root\cimv2`

**Features:**
- Query WMI for reliability records
- Table view: Time, Source, Event Type, Message
- Categories: Application failures, Hardware failures, Windows failures, Misc failures
- Summary widget at top showing reliability score trend (simple bar chart)
- Worker thread for WMI query
- Implements `SearchProvider`

---

## Module 6: Crash Dump Analyzer

**Data source:** `C:\Windows\Minidump\*.dmp` files (requires admin)

**Features:**
- List minidump files with metadata (date, size)
- Parse basic headers from .dmp files (signature, timestamp, exception code)
- Table view: Dump File, Date, Size, Bug Check Code
- Double-click shows hex preview of first 512 bytes
- `requires_admin = True`
- Implements `SearchProvider`

---

## Module 7: PerfMon (Performance Monitor)

**Data source:** psutil real-time counters

**Counters tracked:**
- CPU usage (per-core + total)
- Memory (used/available/percent)
- Disk I/O (read/write bytes/sec)
- Network I/O (sent/received bytes/sec)
- Disk usage (percent full)

**Features:**
- Real-time dashboard with pyqtgraph line charts (rolling 5-min window)
- Update interval: 1 second via QTimer
- Historical data: store readings in a SQLite DB (`perfmon.db` in app data dir) with 1-minute granularity, keep 7 days
- Historical graph view: select counter + time range, renders from SQLite
- Alerting: configurable thresholds (e.g., CPU > 90% for 5 min), fires EventBus event, shows notification
- Implements `SearchProvider` (search alerts history)

---

## Shared Architecture

### Log Table Widget

All log-based modules (1-6) share the same table pattern. Extract a reusable `LogTableWidget`:
- `QTableView` with `QStandardItemModel`
- Sortable columns, alternating row colors
- Row coloring based on level (Error=red, Warning=orange, Info=default)
- Double-click opens detail panel
- Export to CSV action
- Copy row to clipboard
- Status bar showing row count and filter status

### Detail Panel

A `QTextEdit`-based side panel that shows full details of a selected log entry. Shared across all log modules.

### Log Parser Base

Abstract base for file-based log parsers (CBS, DISM, WU):
- `parse_file(path) -> List[LogEntry]`
- Runs on worker thread
- Progress reporting via `WorkerSignals.progress`
- Handles file encoding issues (UTF-8 with fallback to latin-1)

### Module Search Providers

Each module implements `SearchProvider`:
- `search(query)` filters in-memory log entries by query text, date range, types, regex
- `get_filterable_fields()` returns module-specific filter options

---

## File Structure

```
src/modules/
    __init__.py
    event_viewer/
        __init__.py
        event_viewer_module.py      # BaseModule implementation
        event_reader.py             # win32evtlog wrapper
        event_search_provider.py    # SearchProvider impl
    cbs_log/
        __init__.py
        cbs_module.py
        cbs_parser.py
        cbs_search_provider.py
    dism_log/
        __init__.py
        dism_module.py
        dism_parser.py
        dism_search_provider.py
    windows_update/
        __init__.py
        wu_module.py
        wu_parser.py
        wu_search_provider.py
    reliability/
        __init__.py
        reliability_module.py
        reliability_reader.py
        reliability_search_provider.py
    crash_dumps/
        __init__.py
        crash_dump_module.py
        crash_dump_reader.py
        crash_dump_search_provider.py
    perfmon/
        __init__.py
        perfmon_module.py
        perfmon_collector.py        # psutil polling + SQLite storage
        perfmon_charts.py           # pyqtgraph chart widgets
        perfmon_alerts.py           # threshold alerting
        perfmon_search_provider.py
src/ui/
    log_table_widget.py             # Shared reusable table
    detail_panel.py                 # Shared detail viewer
src/core/
    log_parser_base.py              # ABC for file log parsers
```

---

## Module Registration

In `src/main.py`, after creating the App singleton, register all modules:

```python
from modules.event_viewer.event_viewer_module import EventViewerModule
from modules.cbs_log.cbs_module import CBSLogModule
from modules.dism_log.dism_module import DISMLogModule
from modules.windows_update.wu_module import WindowsUpdateModule
from modules.reliability.reliability_module import ReliabilityModule
from modules.crash_dumps.crash_dump_module import CrashDumpModule
from modules.perfmon.perfmon_module import PerfMonModule

app.module_registry.register(EventViewerModule())
app.module_registry.register(CBSLogModule())
app.module_registry.register(DISMLogModule())
app.module_registry.register(WindowsUpdateModule())
app.module_registry.register(ReliabilityModule())
app.module_registry.register(CrashDumpModule())
app.module_registry.register(PerfMonModule())
```

---

## Alerting

PerfMon alerts are stored in config:
```json
{
  "modules": {
    "perfmon": {
      "alerts": [
        {"counter": "cpu_total", "operator": ">", "threshold": 90, "duration_sec": 300, "enabled": true},
        {"counter": "memory_percent", "operator": ">", "threshold": 85, "duration_sec": 60, "enabled": true}
      ],
      "history_days": 7,
      "update_interval_ms": 1000
    }
  }
}
```

When an alert fires, it publishes to EventBus and shows a notification in the NotificationTray.
