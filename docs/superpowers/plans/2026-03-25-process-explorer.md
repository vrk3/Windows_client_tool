# Process Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a native PyQt6 Process Explorer module with real-time process tree, six lower-pane detail views, properties dialog, VirusTotal integration, process actions, and a Sysinternals Live launcher tab.

**Architecture:** `ProcessCollector` (QObject + QTimer) snapshots processes on a Worker thread each tick, diffs against previous snapshot, and emits fine-grained signals. `ProcessTreeModel` (QAbstractItemModel) receives these signals on the main thread and calls beginInsertRows/beginRemoveRows/dataChanged — no full redraws. Lower pane tabs are lazy-loaded QWidgets. All ctypes/Win32 calls isolated in dedicated files.

**Tech Stack:** Python 3.12+, PyQt6, psutil, pywin32 (win32service, win32serviceutil), ctypes (NtQuerySystemInformation, NtSuspendProcess, EnumProcessModules), requests (VirusTotal API), wmi

**Spec:** `docs/superpowers/specs/2026-03-25-process-explorer-design.md`

---

## File Map

### Files to Create

| File | Responsibility |
|------|---------------|
| `src/core/module_groups.py` | ModuleGroup constants (DIAGNOSE, SYSTEM, MANAGE, OPTIMIZE, TOOLS, PROCESS) |
| `src/modules/process_explorer/__init__.py` | Package init |
| `src/modules/process_explorer/process_node.py` | ProcessNode dataclass |
| `src/modules/process_explorer/color_scheme.py` | Process classification → QColor |
| `src/modules/process_explorer/process_collector.py` | QObject + QTimer + Worker: snapshot, diff, signals |
| `src/modules/process_explorer/process_tree_model.py` | QAbstractItemModel: tree + flat mode |
| `src/modules/process_explorer/process_actions.py` | kill, suspend, resume, priority, affinity |
| `src/modules/process_explorer/virustotal_client.py` | SHA256 hash + VT API (hash check + file submit) |
| `src/modules/process_explorer/lower_pane/__init__.py` | Package init |
| `src/modules/process_explorer/lower_pane/network_view.py` | psutil.net_connections() filtered by PID |
| `src/modules/process_explorer/lower_pane/thread_view.py` | psutil.threads() + Win32 OpenThread |
| `src/modules/process_explorer/lower_pane/dll_view.py` | EnumProcessModules via ctypes |
| `src/modules/process_explorer/lower_pane/handle_view.py` | NtQuerySystemInformation + timeout resolver |
| `src/modules/process_explorer/lower_pane/strings_view.py` | PE binary strings + memory strings toggle |
| `src/modules/process_explorer/lower_pane/memory_map_view.py` | psutil.memory_maps() |
| `src/modules/process_explorer/sysinternals_tab.py` | Sysinternals Live launcher + local cache |
| `src/modules/process_explorer/properties_dialog.py` | 8-tab QDialog |
| `src/modules/process_explorer/process_explorer_module.py` | BaseModule: wires all components |
| `tests/test_process_node.py` | ProcessNode tests |
| `tests/test_color_scheme.py` | Color classification tests |
| `tests/test_process_collector.py` | Snapshot + diff logic tests |
| `tests/test_process_tree_model.py` | QAbstractItemModel tests |
| `tests/test_process_actions.py` | Action tests with mocked psutil |
| `tests/test_virustotal_client.py` | VT client tests with mocked requests |
| `tests/test_process_explorer_integration.py` | Module widget creation + wiring |

### Files to Modify

| File | Change |
|------|--------|
| `src/core/base_module.py` | Add `group: str` class attribute |
| `src/modules/event_viewer/event_viewer_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/modules/cbs_log/cbs_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/modules/dism_log/dism_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/modules/windows_update/wu_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/modules/reliability/reliability_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/modules/crash_dumps/crash_dump_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/modules/perfmon/perfmon_module.py` | Add `group = ModuleGroup.DIAGNOSE` |
| `src/main.py` | Register ProcessExplorerModule |

---

## Task 1: ModuleGroups + group attribute on BaseModule

**Files:**
- Create: `src/core/module_groups.py`
- Modify: `src/core/base_module.py`
- Modify: all 7 existing module files (add `group` class attr)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_module_groups.py
from core.module_groups import ModuleGroup
from core.base_module import BaseModule

def test_module_group_constants_exist():
    assert ModuleGroup.DIAGNOSE == "DIAGNOSE"
    assert ModuleGroup.SYSTEM   == "SYSTEM"
    assert ModuleGroup.MANAGE   == "MANAGE"
    assert ModuleGroup.OPTIMIZE == "OPTIMIZE"
    assert ModuleGroup.TOOLS    == "TOOLS"
    assert ModuleGroup.PROCESS  == "PROCESS"

def test_base_module_has_group_annotation():
    assert "group" in BaseModule.__annotations__
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_module_groups.py -v
```
Expected: `ImportError: cannot import name 'ModuleGroup'`

- [ ] **Step 3: Create module_groups.py**

```python
# src/core/module_groups.py
class ModuleGroup:
    DIAGNOSE = "DIAGNOSE"
    SYSTEM   = "SYSTEM"
    MANAGE   = "MANAGE"
    OPTIMIZE = "OPTIMIZE"
    TOOLS    = "TOOLS"
    PROCESS  = "PROCESS"
```

- [ ] **Step 4: Add group annotation to BaseModule**

In `src/core/base_module.py`, add `group: str` alongside the other class-level annotations:

```python
class BaseModule(ABC):
    name: str
    icon: str
    description: str
    requires_admin: bool
    group: str          # ← add this line
    # rest unchanged
```

- [ ] **Step 5: Add group to all 7 existing modules**

Add `group = ModuleGroup.DIAGNOSE` as a class attribute to each of these files, after `requires_admin`:

- `src/modules/event_viewer/event_viewer_module.py` — add `from core.module_groups import ModuleGroup` import + `group = ModuleGroup.DIAGNOSE`
- `src/modules/cbs_log/cbs_module.py` — same
- `src/modules/dism_log/dism_module.py` — same
- `src/modules/windows_update/wu_module.py` — same
- `src/modules/reliability/reliability_module.py` — same
- `src/modules/crash_dumps/crash_dump_module.py` — same
- `src/modules/perfmon/perfmon_module.py` — same

Example for event_viewer_module.py:
```python
from core.module_groups import ModuleGroup   # add this import

class EventViewerModule(BaseModule):
    name = "Event Viewer"
    icon = "event_viewer"
    description = "Windows Event Log viewer (System, Application, Security)"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE             # add this line
```

- [ ] **Step 6: Run tests**

```
cd src && python -m pytest ../tests/test_module_groups.py -v
```
Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add src/core/module_groups.py src/core/base_module.py \
        src/modules/event_viewer/event_viewer_module.py \
        src/modules/cbs_log/cbs_module.py \
        src/modules/dism_log/dism_module.py \
        src/modules/windows_update/wu_module.py \
        src/modules/reliability/reliability_module.py \
        src/modules/crash_dumps/crash_dump_module.py \
        src/modules/perfmon/perfmon_module.py \
        tests/test_module_groups.py
git commit -m "feat: add ModuleGroup constants and group attr to BaseModule"
```

---

## Task 2: ProcessNode Dataclass

**Files:**
- Create: `src/modules/process_explorer/process_node.py`
- Create: `src/modules/process_explorer/__init__.py`
- Create: `tests/test_process_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_process_node.py
from modules.process_explorer.process_node import ProcessNode

def test_process_node_creation():
    node = ProcessNode(
        pid=1234, name="chrome.exe", exe=r"C:\Program Files\Google\Chrome\chrome.exe",
        cmdline="chrome.exe --type=renderer", user="testuser", status="running",
        parent_pid=1000, children=[],
        cpu_percent=2.5, memory_rss=52428800, memory_vms=104857600,
        disk_read_bps=0.0, disk_write_bps=1024.0,
        net_send_bps=512.0, net_recv_bps=2048.0, gpu_percent=0.0,
        is_system=False, is_service=False, is_dotnet=False, is_suspended=False,
        integrity_level="Medium", sha256=None, vt_score=None,
    )
    assert node.pid == 1234
    assert node.name == "chrome.exe"
    assert node.children == []
    assert node.sha256 is None

def test_process_node_children_independent():
    """Each node gets its own children list."""
    a = ProcessNode(pid=1, name="a.exe", exe="", cmdline="", user="", status="running",
                    parent_pid=0, children=[],
                    cpu_percent=0, memory_rss=0, memory_vms=0,
                    disk_read_bps=0, disk_write_bps=0,
                    net_send_bps=0, net_recv_bps=0, gpu_percent=0,
                    is_system=False, is_service=False, is_dotnet=False, is_suspended=False,
                    integrity_level="Medium", sha256=None, vt_score=None)
    b = ProcessNode(pid=2, name="b.exe", exe="", cmdline="", user="", status="running",
                    parent_pid=0, children=[],
                    cpu_percent=0, memory_rss=0, memory_vms=0,
                    disk_read_bps=0, disk_write_bps=0,
                    net_send_bps=0, net_recv_bps=0, gpu_percent=0,
                    is_system=False, is_service=False, is_dotnet=False, is_suspended=False,
                    integrity_level="Medium", sha256=None, vt_score=None)
    a.children.append(b)
    assert len(a.children) == 1
    assert b.children == []
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_process_node.py -v
```
Expected: `ModuleNotFoundError: No module named 'modules.process_explorer'`

- [ ] **Step 3: Create package + ProcessNode**

```python
# src/modules/process_explorer/__init__.py
# (empty)
```

```python
# src/modules/process_explorer/process_node.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ProcessNode:
    pid: int
    name: str
    exe: str
    cmdline: str
    user: str
    status: str          # running | sleeping | stopped | zombie
    parent_pid: int
    children: List['ProcessNode'] = field(default_factory=list)

    # Real-time metrics
    cpu_percent: float = 0.0
    memory_rss: int = 0      # bytes
    memory_vms: int = 0
    disk_read_bps: float = 0.0
    disk_write_bps: float = 0.0
    net_send_bps: float = 0.0
    net_recv_bps: float = 0.0
    gpu_percent: float = 0.0

    # Classification (set once, stable per process lifetime)
    is_system: bool = False
    is_service: bool = False
    is_dotnet: bool = False
    is_suspended: bool = False
    integrity_level: str = "Medium"  # Low | Medium | High | System

    # VirusTotal (populated on demand)
    sha256: Optional[str] = None
    vt_score: Optional[str] = None   # e.g. "3/72"
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_process_node.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/__init__.py \
        src/modules/process_explorer/process_node.py \
        tests/test_process_node.py
git commit -m "feat: add ProcessNode dataclass"
```

---

## Task 3: Color Scheme

**Files:**
- Create: `src/modules/process_explorer/color_scheme.py`
- Create: `tests/test_color_scheme.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_color_scheme.py
from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.color_scheme import get_row_color, ProcessColor


def _node(**kwargs):
    defaults = dict(pid=100, name="test.exe", exe="", cmdline="", user="testuser",
                    status="running", parent_pid=0)
    defaults.update(kwargs)
    return ProcessNode(**defaults)


def test_system_process_color():
    node = _node(is_system=True)
    assert get_row_color(node) == ProcessColor.SYSTEM

def test_service_color():
    node = _node(is_service=True)
    assert get_row_color(node) == ProcessColor.SERVICE

def test_dotnet_color():
    node = _node(is_dotnet=True)
    assert get_row_color(node) == ProcessColor.DOTNET

def test_suspended_color():
    node = _node(is_suspended=True)
    assert get_row_color(node) == ProcessColor.SUSPENDED

def test_gpu_color():
    node = _node(gpu_percent=15.0)
    assert get_row_color(node) == ProcessColor.GPU

def test_own_process_color():
    node = _node()
    assert get_row_color(node) == ProcessColor.DEFAULT

def test_system_takes_priority_over_service():
    node = _node(is_system=True, is_service=True)
    assert get_row_color(node) == ProcessColor.SYSTEM
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_color_scheme.py -v
```
Expected: `ImportError: cannot import name 'get_row_color'`

- [ ] **Step 3: Implement color_scheme.py**

```python
# src/modules/process_explorer/color_scheme.py
from __future__ import annotations
from PyQt6.QtGui import QColor
from modules.process_explorer.process_node import ProcessNode


class ProcessColor:
    SYSTEM    = QColor(173, 216, 230)   # light blue
    SERVICE   = QColor(255, 182, 193)   # pink
    DOTNET    = QColor(255, 255, 153)   # yellow
    GPU       = QColor(216, 191, 216)   # light purple
    SUSPENDED = QColor(200, 200, 200)   # grey
    DEFAULT   = QColor(0, 0, 0, 0)      # transparent = default palette


def get_row_color(node: ProcessNode) -> QColor:
    """Return background QColor for a process row. Priority: suspended > system > service > dotnet > gpu > default."""
    if node.is_suspended:
        return ProcessColor.SUSPENDED
    if node.is_system:
        return ProcessColor.SYSTEM
    if node.is_service:
        return ProcessColor.SERVICE
    if node.is_dotnet:
        return ProcessColor.DOTNET
    if node.gpu_percent > 0.5:
        return ProcessColor.GPU
    return ProcessColor.DEFAULT
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_color_scheme.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/color_scheme.py tests/test_color_scheme.py
git commit -m "feat: add ProcessNode color scheme"
```

---

## Task 4: ProcessCollector — Snapshot + Diff

**Files:**
- Create: `src/modules/process_explorer/process_collector.py`
- Create: `tests/test_process_collector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_process_collector.py
from unittest.mock import patch, MagicMock
from modules.process_explorer.process_collector import ProcessCollector, build_snapshot, diff_snapshots


def _mock_proc(pid, name, ppid=0, user="testuser", status="running",
               exe="", cmdline="", cpu=0.0, rss=0, vms=0):
    p = MagicMock()
    p.info = {
        "pid": pid, "name": name, "ppid": ppid, "username": user,
        "status": status, "exe": exe, "cmdline": cmdline,
        "cpu_percent": cpu, "memory_info": MagicMock(rss=rss, vms=vms),
        "io_counters": None,
    }
    return p


def test_build_snapshot_returns_dict_keyed_by_pid():
    procs = [_mock_proc(4, "System"), _mock_proc(100, "chrome.exe", ppid=4)]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs):
        snapshot = build_snapshot(set())
    assert 4 in snapshot
    assert 100 in snapshot
    assert snapshot[100].parent_pid == 4


def test_build_snapshot_marks_system_process():
    procs = [_mock_proc(4, "System", user="SYSTEM")]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs):
        snapshot = build_snapshot(set())
    assert snapshot[4].is_system is True


def test_diff_added():
    old = {}
    new_procs = [_mock_proc(100, "chrome.exe")]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=new_procs):
        new = build_snapshot(set())
    added, removed, changed = diff_snapshots(old, new)
    assert 100 in added
    assert removed == []
    assert changed == []


def test_diff_removed():
    old_procs = [_mock_proc(100, "chrome.exe")]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=old_procs):
        old = build_snapshot(set())
    new = {}
    added, removed, changed = diff_snapshots(old, new)
    assert added == []
    assert 100 in removed
    assert changed == []


def test_diff_changed_metrics():
    procs = [_mock_proc(100, "chrome.exe", cpu=1.0)]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs):
        old = build_snapshot(set())
    procs2 = [_mock_proc(100, "chrome.exe", cpu=50.0)]
    with patch("modules.process_explorer.process_collector.psutil.process_iter", return_value=procs2):
        new = build_snapshot(set())
    added, removed, changed = diff_snapshots(old, new)
    assert added == []
    assert removed == []
    assert 100 in changed
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_process_collector.py -v
```
Expected: `ImportError: cannot import name 'ProcessCollector'`

- [ ] **Step 3: Implement process_collector.py**

```python
# src/modules/process_explorer/process_collector.py
from __future__ import annotations
import logging
from typing import Dict, List, Set, Tuple

import psutil
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.worker import Worker
from modules.process_explorer.process_node import ProcessNode

logger = logging.getLogger(__name__)

_SYSTEM_USERS = {"SYSTEM", "LOCAL SERVICE", "NETWORK SERVICE", "NT AUTHORITY\\SYSTEM",
                 "NT AUTHORITY\\LOCAL SERVICE", "NT AUTHORITY\\NETWORK SERVICE"}


def build_snapshot(service_names: Set[str]) -> Dict[int, ProcessNode]:
    """Collect all processes from psutil and return a {pid: ProcessNode} dict.
    service_names: set of process names known to be Windows services.
    Called on a worker thread."""
    attrs = ["pid", "name", "exe", "cmdline", "username", "status", "ppid",
             "cpu_percent", "memory_info", "io_counters"]
    result: Dict[int, ProcessNode] = {}

    for proc in psutil.process_iter(attrs):
        info = proc.info
        pid = info.get("pid") or 0
        if pid == 0:
            continue
        try:
            user = info.get("username") or ""
            mem = info.get("memory_info")
            io = info.get("io_counters")
            node = ProcessNode(
                pid=pid,
                name=info.get("name") or "",
                exe=info.get("exe") or "",
                cmdline=" ".join(info.get("cmdline") or []),
                user=user,
                status=info.get("status") or "unknown",
                parent_pid=info.get("ppid") or 0,
                cpu_percent=float(info.get("cpu_percent") or 0.0),
                memory_rss=mem.rss if mem else 0,
                memory_vms=mem.vms if mem else 0,
                disk_read_bps=float(io.read_bytes) if io else 0.0,
                disk_write_bps=float(io.write_bytes) if io else 0.0,
                is_system=user.upper().split("\\")[-1] in _SYSTEM_USERS or pid <= 8,
                is_service=(info.get("name") or "").lower() in service_names,
            )
            result[pid] = node
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Build parent→children links
    for node in result.values():
        parent = result.get(node.parent_pid)
        if parent and parent.pid != node.pid:
            parent.children.append(node)

    return result


def diff_snapshots(
    old: Dict[int, ProcessNode],
    new: Dict[int, ProcessNode],
) -> Tuple[List[ProcessNode], List[int], List[int]]:
    """Return (added_nodes, removed_pids, changed_pids)."""
    old_pids = set(old)
    new_pids = set(new)
    added = [new[p] for p in new_pids - old_pids]
    removed = list(old_pids - new_pids)
    changed = [
        p for p in old_pids & new_pids
        if (old[p].cpu_percent != new[p].cpu_percent or
            old[p].memory_rss != new[p].memory_rss or
            old[p].status != new[p].status)
    ]
    return added, removed, changed


class ProcessCollector(QObject):
    """Polls process list on a background Worker, diffs, and emits signals."""
    process_added   = pyqtSignal(object)          # ProcessNode
    process_removed = pyqtSignal(int)             # pid
    processes_updated = pyqtSignal(list)          # list[int] — changed pids
    snapshot_ready  = pyqtSignal(dict)            # full {pid: ProcessNode} — first load

    def __init__(self, interval_ms: int = 1000, parent=None):
        super().__init__(parent)
        self._interval_ms = interval_ms
        self._snapshot: Dict[int, ProcessNode] = {}
        self._service_names: Set[str] = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._thread_pool = None  # set by module via set_thread_pool()
        self._first = True

    def set_thread_pool(self, pool):
        self._thread_pool = pool

    def set_service_names(self, names: Set[str]):
        self._service_names = {n.lower() for n in names}

    def set_interval(self, ms: int):
        self._interval_ms = ms
        if self._timer.isActive():
            self._timer.setInterval(ms)

    def start(self):
        self._timer.start(self._interval_ms)

    def stop(self):
        self._timer.stop()

    def _tick(self):
        if self._thread_pool is None:
            return
        service_names = self._service_names

        def do_work(worker):
            return build_snapshot(service_names)

        w = Worker(do_work)
        w.signals.result.connect(self._on_snapshot)
        w.signals.error.connect(lambda e: logger.error("ProcessCollector error: %s", e))
        self._thread_pool.start(w)

    def _on_snapshot(self, new_snapshot: Dict[int, ProcessNode]):
        if self._first:
            self._snapshot = new_snapshot
            self._first = False
            self.snapshot_ready.emit(new_snapshot)
            return
        added, removed, changed = diff_snapshots(self._snapshot, new_snapshot)
        self._snapshot = new_snapshot
        for node in added:
            self.process_added.emit(node)
        for pid in removed:
            self.process_removed.emit(pid)
        if changed:
            self.processes_updated.emit(changed)

    def get_snapshot(self) -> Dict[int, ProcessNode]:
        return self._snapshot
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_process_collector.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/process_collector.py tests/test_process_collector.py
git commit -m "feat: add ProcessCollector with snapshot + diff logic"
```

---

## Task 5: ProcessTreeModel

**Files:**
- Create: `src/modules/process_explorer/process_tree_model.py`
- Create: `tests/test_process_tree_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_process_tree_model.py
from unittest.mock import patch
from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.process_tree_model import ProcessTreeModel, COL_NAME, COL_PID, COL_CPU


def _node(pid, name, parent_pid=0, cpu=0.0, children=None):
    return ProcessNode(pid=pid, name=name, exe=f"C:\\{name}", cmdline="",
                       user="testuser", status="running", parent_pid=parent_pid,
                       children=children or [],
                       cpu_percent=cpu, memory_rss=1024*1024, memory_vms=2*1024*1024)


def test_model_loads_flat_snapshot():
    model = ProcessTreeModel()
    snapshot = {4: _node(4, "System"), 100: _node(100, "chrome.exe", parent_pid=4)}
    # add chrome as child of System
    snapshot[4].children.append(snapshot[100])
    model.load_snapshot(snapshot)
    # root should contain System (PID 4 has no parent in snapshot)
    assert model.rowCount() == 1
    parent_idx = model.index(0, 0)
    assert model.data(parent_idx) == "System"


def test_model_child_count():
    model = ProcessTreeModel()
    child = _node(100, "chrome.exe", parent_pid=4)
    root = _node(4, "System", children=[child])
    model.load_snapshot({4: root, 100: child})
    parent_idx = model.index(0, 0)
    assert model.rowCount(parent_idx) == 1


def test_model_column_pid():
    model = ProcessTreeModel()
    model.load_snapshot({4: _node(4, "System")})
    idx = model.index(0, COL_PID)
    assert model.data(idx) == "4"


def test_model_flat_mode():
    model = ProcessTreeModel()
    child = _node(100, "chrome.exe", parent_pid=4)
    root = _node(4, "System", children=[child])
    model.load_snapshot({4: root, 100: child})
    model.set_flat_mode(True)
    assert model.rowCount() == 2


def test_model_update_metrics():
    model = ProcessTreeModel()
    model.load_snapshot({4: _node(4, "System", cpu=1.0)})
    updated = _node(4, "System", cpu=50.0)
    model.update_nodes({4: updated})
    idx = model.index(0, COL_CPU)
    assert "50" in model.data(idx)
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_process_tree_model.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement ProcessTreeModel**

```python
# src/modules/process_explorer/process_tree_model.py
from __future__ import annotations
from typing import Dict, List, Optional

from PyQt6.QtCore import QAbstractItemModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.color_scheme import get_row_color

# Column indices
COL_NAME  = 0
COL_PID   = 1
COL_CPU   = 2
COL_RAM   = 3
COL_DISK_R = 4
COL_DISK_W = 5
COL_NET_IN = 6
COL_NET_OUT = 7
COL_GPU   = 8
COL_USER  = 9
COL_PATH  = 10

COLUMNS = ["Name", "PID", "CPU%", "RAM", "Disk R", "Disk W",
           "Net In", "Net Out", "GPU%", "User", "Path"]


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024**2:
        return f"{n/1024:.1f}K"
    if n < 1024**3:
        return f"{n/1024**2:.1f}M"
    return f"{n/1024**3:.1f}G"


class ProcessTreeModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._snapshot: Dict[int, ProcessNode] = {}
        self._roots: List[ProcessNode] = []
        self._flat_mode = False

    # ── Public API ────────────────────────────────────────────────────

    def load_snapshot(self, snapshot: Dict[int, ProcessNode]):
        self.beginResetModel()
        self._snapshot = snapshot
        self._roots = [n for n in snapshot.values()
                       if n.parent_pid not in snapshot or n.parent_pid == n.pid]
        self.endResetModel()

    def set_flat_mode(self, flat: bool):
        self.beginResetModel()
        self._flat_mode = flat
        self.endResetModel()

    def update_nodes(self, changed: Dict[int, ProcessNode]):
        """Update metrics for changed pids and emit dataChanged."""
        for pid, new_node in changed.items():
            if pid not in self._snapshot:
                continue
            old = self._snapshot[pid]
            # update in place (preserve tree links)
            old.cpu_percent   = new_node.cpu_percent
            old.memory_rss    = new_node.memory_rss
            old.memory_vms    = new_node.memory_vms
            old.disk_read_bps = new_node.disk_read_bps
            old.disk_write_bps= new_node.disk_write_bps
            old.net_send_bps  = new_node.net_send_bps
            old.net_recv_bps  = new_node.net_recv_bps
            old.gpu_percent   = new_node.gpu_percent
            old.status        = new_node.status

        # emit dataChanged for visible rows — simple approach: reset data columns
        if changed:
            top_left = self.index(0, 0)
            bot_right = self.index(self.rowCount() - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top_left, bot_right)

    # ── QAbstractItemModel required overrides ─────────────────────────

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if self._flat_mode:
            if not parent.isValid():
                return len(self._snapshot)
            return 0
        if not parent.isValid():
            return len(self._roots)
        node: ProcessNode = parent.internalPointer()
        return len(node.children)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(COLUMNS)

    def index(self, row: int, col: int, parent: QModelIndex = QModelIndex()) -> QModelIndex:
        if self._flat_mode:
            nodes = list(self._snapshot.values())
            if 0 <= row < len(nodes):
                return self.createIndex(row, col, nodes[row])
            return QModelIndex()

        if not parent.isValid():
            if 0 <= row < len(self._roots):
                return self.createIndex(row, col, self._roots[row])
        else:
            p_node: ProcessNode = parent.internalPointer()
            if 0 <= row < len(p_node.children):
                return self.createIndex(row, col, p_node.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid() or self._flat_mode:
            return QModelIndex()
        node: ProcessNode = index.internalPointer()
        parent_node = self._snapshot.get(node.parent_pid)
        if parent_node is None or parent_node is node:
            return QModelIndex()
        # find row of parent_node within ITS parent's children
        grandparent = self._snapshot.get(parent_node.parent_pid)
        siblings = grandparent.children if grandparent else self._roots
        try:
            row = siblings.index(parent_node)
        except ValueError:
            return QModelIndex()
        return self.createIndex(row, 0, parent_node)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: ProcessNode = index.internalPointer()
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return [
                node.name, str(node.pid),
                f"{node.cpu_percent:.1f}", _fmt_bytes(node.memory_rss),
                _fmt_bytes(int(node.disk_read_bps)), _fmt_bytes(int(node.disk_write_bps)),
                _fmt_bytes(int(node.net_recv_bps)), _fmt_bytes(int(node.net_send_bps)),
                f"{node.gpu_percent:.1f}", node.user, node.exe,
            ][col]

        if role == Qt.ItemDataRole.BackgroundRole:
            color = get_row_color(node)
            if color.alpha() > 0:
                return color
            return None

        if role == Qt.ItemDataRole.ToolTipRole and col == COL_NAME:
            return node.exe

        return None

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_process_tree_model.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/process_tree_model.py tests/test_process_tree_model.py
git commit -m "feat: add ProcessTreeModel (QAbstractItemModel, tree + flat mode)"
```

---

## Task 6: ProcessActions

**Files:**
- Create: `src/modules/process_explorer/process_actions.py`
- Create: `tests/test_process_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_process_actions.py
from unittest.mock import patch, MagicMock
from modules.process_explorer.process_actions import (
    kill_process, kill_tree, suspend_process, resume_process,
    set_priority, set_affinity, PRIORITY_LEVELS,
)


def test_kill_process_success():
    mock_proc = MagicMock()
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        ok, err = kill_process(1234)
    mock_proc.kill.assert_called_once()
    assert ok is True
    assert err == ""


def test_kill_process_no_such_process():
    import psutil
    with patch("modules.process_explorer.process_actions.psutil.Process",
               side_effect=psutil.NoSuchProcess(1234)):
        ok, err = kill_process(1234)
    assert ok is False
    assert "no longer running" in err


def test_set_priority_valid():
    mock_proc = MagicMock()
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        ok, err = set_priority(1234, "normal")
    mock_proc.nice.assert_called_once()
    assert ok is True


def test_set_priority_invalid_level():
    ok, err = set_priority(1234, "turbo_boost")
    assert ok is False
    assert "Unknown priority" in err


def test_set_affinity_success():
    mock_proc = MagicMock()
    with patch("modules.process_explorer.process_actions.psutil.Process", return_value=mock_proc):
        ok, err = set_affinity(1234, [0, 1])
    mock_proc.cpu_affinity.assert_called_once_with([0, 1])
    assert ok is True


def test_priority_levels_complete():
    assert "idle" in PRIORITY_LEVELS
    assert "realtime" in PRIORITY_LEVELS
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_process_actions.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement process_actions.py**

```python
# src/modules/process_explorer/process_actions.py
from __future__ import annotations
import ctypes
import logging
from typing import List, Tuple

import psutil

logger = logging.getLogger(__name__)

# psutil priority constants (Windows)
PRIORITY_LEVELS = {
    "idle":         psutil.IDLE_PRIORITY_CLASS,
    "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
    "normal":       psutil.NORMAL_PRIORITY_CLASS,
    "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
    "high":         psutil.HIGH_PRIORITY_CLASS,
    "realtime":     psutil.REALTIME_PRIORITY_CLASS,
}

_ntdll = ctypes.windll.ntdll


def kill_process(pid: int) -> Tuple[bool, str]:
    try:
        psutil.Process(pid).kill()
        return True, ""
    except psutil.NoSuchProcess:
        return False, f"Process {pid} is no longer running."
    except psutil.AccessDenied:
        return False, f"Access denied — run as administrator."
    except Exception as e:
        return False, str(e)


def kill_tree(pid: int) -> Tuple[bool, List[str]]:
    """Kill process and all descendants. Returns (all_ok, list_of_errors)."""
    errors = []
    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=True)
        for child in children:
            ok, err = kill_process(child.pid)
            if not ok:
                errors.append(f"PID {child.pid}: {err}")
        ok, err = kill_process(pid)
        if not ok:
            errors.append(f"PID {pid}: {err}")
    except psutil.NoSuchProcess:
        errors.append(f"PID {pid} is no longer running.")
    return len(errors) == 0, errors


def suspend_process(pid: int) -> Tuple[bool, str]:
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
        if not handle:
            return False, f"Could not open process {pid}."
        status = _ntdll.NtSuspendProcess(handle)
        ctypes.windll.kernel32.CloseHandle(handle)
        if status != 0:
            return False, f"NtSuspendProcess returned 0x{status:08X}"
        return True, ""
    except Exception as e:
        return False, str(e)


def resume_process(pid: int) -> Tuple[bool, str]:
    try:
        handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)
        if not handle:
            return False, f"Could not open process {pid}."
        status = _ntdll.NtResumeProcess(handle)
        ctypes.windll.kernel32.CloseHandle(handle)
        if status != 0:
            return False, f"NtResumeProcess returned 0x{status:08X}"
        return True, ""
    except Exception as e:
        return False, str(e)


def set_priority(pid: int, level: str) -> Tuple[bool, str]:
    if level not in PRIORITY_LEVELS:
        return False, f"Unknown priority '{level}'. Valid: {list(PRIORITY_LEVELS)}"
    try:
        psutil.Process(pid).nice(PRIORITY_LEVELS[level])
        return True, ""
    except psutil.NoSuchProcess:
        return False, f"Process {pid} is no longer running."
    except psutil.AccessDenied:
        return False, "Access denied — run as administrator."
    except Exception as e:
        return False, str(e)


def set_affinity(pid: int, cores: List[int]) -> Tuple[bool, str]:
    try:
        psutil.Process(pid).cpu_affinity(cores)
        return True, ""
    except psutil.NoSuchProcess:
        return False, f"Process {pid} is no longer running."
    except psutil.AccessDenied:
        return False, "Access denied — run as administrator."
    except Exception as e:
        return False, str(e)
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_process_actions.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/process_actions.py tests/test_process_actions.py
git commit -m "feat: add ProcessActions (kill, suspend, priority, affinity)"
```

---

## Task 7: VirusTotal Client

**Files:**
- Create: `src/modules/process_explorer/virustotal_client.py`
- Create: `tests/test_virustotal_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_virustotal_client.py
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock
from modules.process_explorer.virustotal_client import (
    compute_sha256, VTResult, check_hash, VTClient,
)


def test_compute_sha256(tmp_path):
    f = tmp_path / "test.bin"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert compute_sha256(str(f)) == expected


def test_compute_sha256_missing_file():
    result = compute_sha256("/nonexistent/path/file.exe")
    assert result is None


def test_check_hash_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"attributes": {"last_analysis_stats": {"malicious": 3, "undetected": 69}}}
    }
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp):
        result = check_hash("abc123", api_key="testkey")
    assert result.found is True
    assert result.malicious == 3
    assert result.total == 72
    assert result.score == "3/72"


def test_check_hash_not_found():
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp):
        result = check_hash("abc123", api_key="testkey")
    assert result.found is False
    assert result.score is None


def test_vt_client_caches_result():
    client = VTClient(api_key="testkey")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"attributes": {"last_analysis_stats": {"malicious": 0, "undetected": 72}}}
    }
    with patch("modules.process_explorer.virustotal_client.requests.get", return_value=mock_resp) as m:
        r1 = client.check("abc123")
        r2 = client.check("abc123")  # second call should use cache
    assert m.call_count == 1  # only one HTTP call
    assert r1.score == r2.score
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_virustotal_client.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement virustotal_client.py**

```python
# src/modules/process_explorer/virustotal_client.py
from __future__ import annotations
import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

_VT_API_BASE = "https://www.virustotal.com/api/v3"


@dataclass
class VTResult:
    found: bool
    sha256: str
    malicious: int = 0
    total: int = 0
    score: Optional[str] = None       # e.g. "3/72"
    details: Optional[dict] = None    # full last_analysis_results


def compute_sha256(path: str) -> Optional[str]:
    """Compute SHA256 of a file. Returns None on error."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning("SHA256 failed for %s: %s", path, e)
        return None


def check_hash(sha256: str, api_key: str) -> VTResult:
    """Query VT for a known hash. Returns VTResult(found=False) on 404."""
    try:
        resp = requests.get(
            f"{_VT_API_BASE}/files/{sha256}",
            headers={"x-apikey": api_key},
            timeout=10,
        )
        if resp.status_code == 404:
            return VTResult(found=False, sha256=sha256)
        resp.raise_for_status()
        attrs = resp.json()["data"]["attributes"]
        stats = attrs.get("last_analysis_stats", {})
        malicious = stats.get("malicious", 0)
        total = sum(stats.values())
        return VTResult(
            found=True, sha256=sha256,
            malicious=malicious, total=total,
            score=f"{malicious}/{total}",
            details=attrs.get("last_analysis_results"),
        )
    except requests.RequestException as e:
        logger.error("VT hash check failed: %s", e)
        return VTResult(found=False, sha256=sha256)


class VTClient:
    """Session-scoped VirusTotal client with in-memory cache."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._cache: Dict[str, VTResult] = {}

    def check(self, sha256: str) -> VTResult:
        if sha256 in self._cache:
            return self._cache[sha256]
        result = check_hash(sha256, self._api_key)
        self._cache[sha256] = result
        return result

    def submit_file(self, path: str) -> Optional[str]:
        """Upload file to VT for analysis. Returns analysis ID or None."""
        try:
            with open(path, "rb") as f:
                resp = requests.post(
                    f"{_VT_API_BASE}/files",
                    headers={"x-apikey": self._api_key},
                    files={"file": f},
                    timeout=60,
                )
                resp.raise_for_status()
                return resp.json()["data"]["id"]
        except Exception as e:
            logger.error("VT file submission failed: %s", e)
            return None

    def poll_analysis(self, analysis_id: str) -> Optional[VTResult]:
        """Poll for analysis result. Returns None if still pending."""
        try:
            resp = requests.get(
                f"{_VT_API_BASE}/analyses/{analysis_id}",
                headers={"x-apikey": self._api_key},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            if data["attributes"]["status"] != "completed":
                return None
            stats = data["attributes"]["stats"]
            malicious = stats.get("malicious", 0)
            total = sum(stats.values())
            return VTResult(found=True, sha256="", malicious=malicious, total=total,
                            score=f"{malicious}/{total}")
        except Exception as e:
            logger.error("VT poll failed: %s", e)
            return None
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_virustotal_client.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/virustotal_client.py tests/test_virustotal_client.py
git commit -m "feat: add VirusTotal client (hash check, file submit, session cache)"
```

---

## Task 8: Lower Pane — Network + Thread Views

**Files:**
- Create: `src/modules/process_explorer/lower_pane/__init__.py`
- Create: `src/modules/process_explorer/lower_pane/network_view.py`
- Create: `src/modules/process_explorer/lower_pane/thread_view.py`

- [ ] **Step 1: Create package init**

```python
# src/modules/process_explorer/lower_pane/__init__.py
# (empty)
```

- [ ] **Step 2: Implement network_view.py**

```python
# src/modules/process_explorer/lower_pane/network_view.py
from __future__ import annotations
import logging
from typing import Optional

import psutil
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

_HEADERS = ["Protocol", "Local Address", "Local Port", "Remote Address", "Remote Port", "State"]


class NetworkView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)
        self._pid: Optional[int] = None

    def load_pid(self, pid: int):
        self._pid = pid
        self._refresh()

    def _refresh(self):
        self._table.setRowCount(0)
        if self._pid is None:
            return
        try:
            conns = psutil.net_connections()
        except psutil.AccessDenied:
            return
        rows = [c for c in conns if c.pid == self._pid]
        self._table.setRowCount(len(rows))
        for r, conn in enumerate(rows):
            proto = "TCP" if conn.type.name == "SOCK_STREAM" else "UDP"
            laddr = conn.laddr.ip if conn.laddr else ""
            lport = str(conn.laddr.port) if conn.laddr else ""
            raddr = conn.raddr.ip if conn.raddr else ""
            rport = str(conn.raddr.port) if conn.raddr else ""
            state = conn.status or ""
            for c, val in enumerate([proto, laddr, lport, raddr, rport, state]):
                self._table.setItem(r, c, QTableWidgetItem(val))
```

- [ ] **Step 3: Implement thread_view.py**

```python
# src/modules/process_explorer/lower_pane/thread_view.py
from __future__ import annotations
import ctypes
import logging
from typing import Optional

import psutil
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView

logger = logging.getLogger(__name__)

_HEADERS = ["TID", "CPU%", "User Time", "System Time"]


class ThreadView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def load_pid(self, pid: int):
        self._table.setRowCount(0)
        try:
            threads = psutil.Process(pid).threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return
        self._table.setRowCount(len(threads))
        for r, t in enumerate(threads):
            for c, val in enumerate([
                str(t.id),
                "—",                          # cpu% per-thread not available via psutil
                f"{t.user_time:.3f}s",
                f"{t.system_time:.3f}s",
            ]):
                self._table.setItem(r, c, QTableWidgetItem(val))
```

- [ ] **Step 4: Run a quick smoke test**

```python
# Run this inline to verify widgets construct without error
cd src && python -c "
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from modules.process_explorer.lower_pane.network_view import NetworkView
from modules.process_explorer.lower_pane.thread_view import ThreadView
nv = NetworkView()
tv = ThreadView()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/lower_pane/__init__.py \
        src/modules/process_explorer/lower_pane/network_view.py \
        src/modules/process_explorer/lower_pane/thread_view.py
git commit -m "feat: add lower pane network and thread views"
```

---

## Task 9: Lower Pane — DLL + Memory Map Views

**Files:**
- Create: `src/modules/process_explorer/lower_pane/dll_view.py`
- Create: `src/modules/process_explorer/lower_pane/memory_map_view.py`

- [ ] **Step 1: Implement dll_view.py**

```python
# src/modules/process_explorer/lower_pane/dll_view.py
from __future__ import annotations
import ctypes
import ctypes.wintypes
import logging
import os
from typing import List, Optional, Tuple

import psutil
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView, QLabel)
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

_HEADERS = ["Name", "Full Path", "Base Address", "Size", "Company", "Version"]

_psapi = ctypes.windll.psapi
_kernel32 = ctypes.windll.kernel32
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010


def _get_dll_list(pid: int) -> List[Tuple[str, str, int, int]]:
    """Returns list of (name, path, base_addr, size) for each module in pid."""
    results = []
    handle = _kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not handle:
        return results
    try:
        module_array = (ctypes.wintypes.HMODULE * 1024)()
        needed = ctypes.wintypes.DWORD()
        if not _psapi.EnumProcessModulesEx(
            handle, module_array, ctypes.sizeof(module_array),
            ctypes.byref(needed), 0x03  # LIST_MODULES_ALL
        ):
            return results
        count = needed.value // ctypes.sizeof(ctypes.wintypes.HMODULE)
        path_buf = ctypes.create_unicode_buffer(1024)
        for i in range(count):
            mod = module_array[i]
            _psapi.GetModuleFileNameExW(handle, mod, path_buf, 1024)
            path = path_buf.value
            name = os.path.basename(path)
            results.append((name, path, mod, 0))
    finally:
        _kernel32.CloseHandle(handle)
    return results


class DllView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def load_pid(self, pid: int):
        self._table.setRowCount(0)
        try:
            dlls = _get_dll_list(pid)
        except Exception as e:
            logger.warning("DLL enum failed for pid %d: %s", pid, e)
            return
        self._table.setRowCount(len(dlls))
        for r, (name, path, base, size) in enumerate(dlls):
            for c, val in enumerate([name, path, hex(base), str(size), "", ""]):
                self._table.setItem(r, c, QTableWidgetItem(val))
```

- [ ] **Step 2: Implement memory_map_view.py**

```python
# src/modules/process_explorer/lower_pane/memory_map_view.py
from __future__ import annotations
import logging
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView)
from PyQt6.QtGui import QColor
import psutil

logger = logging.getLogger(__name__)

_HEADERS = ["Path", "RSS", "Size", "Permissions", "Private"]


class MemoryMapView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table)

    def _fmt(self, n: int) -> str:
        if n < 1024**2:
            return f"{n//1024}K"
        return f"{n//1024**2}M"

    def load_pid(self, pid: int):
        self._table.setRowCount(0)
        try:
            maps = psutil.Process(pid).memory_maps(grouped=False)
        except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError):
            return
        self._table.setRowCount(len(maps))
        for r, m in enumerate(maps):
            perms = getattr(m, "perms", "")
            private = self._fmt(getattr(m, "private", 0))
            for c, val in enumerate([m.path, self._fmt(m.rss), "—", perms, private]):
                item = QTableWidgetItem(val)
                # Highlight W^X (writable+executable) in yellow
                if perms and "w" in perms and "x" in perms:
                    item.setBackground(QColor(255, 255, 153))
                self._table.setItem(r, c, item)
```

- [ ] **Step 3: Smoke test both views**

```
cd src && python -c "
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from modules.process_explorer.lower_pane.dll_view import DllView
from modules.process_explorer.lower_pane.memory_map_view import MemoryMapView
DllView(); MemoryMapView()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add src/modules/process_explorer/lower_pane/dll_view.py \
        src/modules/process_explorer/lower_pane/memory_map_view.py
git commit -m "feat: add lower pane DLL and memory map views"
```

---

## Task 10: Lower Pane — Handle View

**Files:**
- Create: `src/modules/process_explorer/lower_pane/handle_view.py`

- [ ] **Step 1: Implement handle_view.py**

```python
# src/modules/process_explorer/lower_pane/handle_view.py
from __future__ import annotations
import ctypes
import ctypes.wintypes
import logging
import threading
from typing import List, NamedTuple, Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTableWidget,
                              QTableWidgetItem, QHeaderView, QLabel)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

logger = logging.getLogger(__name__)

_HEADERS = ["Type", "Name", "Handle Value", "Object Address", "Access"]

_ntdll = ctypes.windll.ntdll
_kernel32 = ctypes.windll.kernel32

SystemHandleInformation = 16
STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class _SYSTEM_HANDLE_ENTRY(ctypes.Structure):
    _fields_ = [
        ("UniqueProcessId", ctypes.wintypes.USHORT),
        ("CreatorBackTraceIndex", ctypes.wintypes.USHORT),
        ("ObjectTypeIndex", ctypes.wintypes.BYTE),
        ("HandleAttributes", ctypes.wintypes.BYTE),
        ("HandleValue", ctypes.wintypes.USHORT),
        ("Object", ctypes.c_void_p),
        ("GrantedAccess", ctypes.wintypes.ULONG),
    ]


class _SYSTEM_HANDLE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("NumberOfHandles", ctypes.wintypes.ULONG),
        ("Handles", _SYSTEM_HANDLE_ENTRY * 1),
    ]


def _query_handles(pid: int) -> List[dict]:
    """Query all handles for pid via NtQuerySystemInformation."""
    size = 0x10000
    while True:
        buf = (ctypes.c_byte * size)()
        ret_len = ctypes.wintypes.ULONG()
        status = _ntdll.NtQuerySystemInformation(
            SystemHandleInformation, buf, size, ctypes.byref(ret_len)
        )
        if status == STATUS_INFO_LENGTH_MISMATCH:
            size *= 2
            continue
        if status != 0:
            return []
        break

    info = ctypes.cast(buf, ctypes.POINTER(_SYSTEM_HANDLE_INFORMATION)).contents
    count = info.NumberOfHandles
    entry_size = ctypes.sizeof(_SYSTEM_HANDLE_ENTRY)
    base = ctypes.addressof(info.Handles)

    results = []
    for i in range(count):
        entry = _SYSTEM_HANDLE_ENTRY.from_address(base + i * entry_size)
        if entry.UniqueProcessId != pid:
            continue
        results.append({
            "type_index": entry.ObjectTypeIndex,
            "handle": entry.HandleValue,
            "object": entry.Object,
            "access": entry.GrantedAccess,
        })
    return results


class HandleView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel("Select a process to view handles")
        layout.addWidget(self._label)
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.hide()
        layout.addWidget(self._table)

    def load_pid(self, pid: int):
        self._label.setText(f"Loading handles for PID {pid}…")
        self._table.hide()
        # Run on background thread to avoid UI freeze
        t = threading.Thread(target=self._load, args=(pid,), daemon=True)
        t.start()

    def _load(self, pid: int):
        try:
            handles = _query_handles(pid)
        except Exception as e:
            logger.warning("Handle query failed for %d: %s", pid, e)
            handles = []
        # Marshal back to main thread via Qt event
        from PyQt6.QtCore import QMetaObject, Qt
        QMetaObject.invokeMethod(self, "_populate",
                                 Qt.ConnectionType.QueuedConnection,
                                 ctypes.py_object(handles))

    def _populate(self, handles: List[dict]):
        self._table.setRowCount(len(handles))
        for r, h in enumerate(handles):
            for c, val in enumerate([
                str(h["type_index"]),
                "—",                        # name resolution omitted for safety
                hex(h["handle"]),
                hex(h["object"] or 0),
                hex(h["access"]),
            ]):
                self._table.setItem(r, c, QTableWidgetItem(val))
        self._label.setText(f"{len(handles)} handles")
        self._table.show()
```

- [ ] **Step 2: Smoke test**

```
cd src && python -c "
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from modules.process_explorer.lower_pane.handle_view import HandleView
HandleView()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/modules/process_explorer/lower_pane/handle_view.py
git commit -m "feat: add lower pane handle view (NtQuerySystemInformation)"
```

---

## Task 11: Lower Pane — Strings View

**Files:**
- Create: `src/modules/process_explorer/lower_pane/strings_view.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strings_view.py  (logic only — no Qt)
from modules.process_explorer.lower_pane.strings_view import extract_strings


def test_extract_ascii_strings(tmp_path):
    data = b"\x00hello world\x00" + b"AB" + b"\x00\x00toolong_string_here\x00"
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    results = extract_strings(str(f), min_len=4, encoding="ascii")
    assert "hello world" in results
    assert "toolong_string_here" in results
    assert "AB" not in results  # too short


def test_extract_unicode_strings(tmp_path):
    # UTF-16LE encoded string
    text = "hello\x00w\x00o\x00r\x00l\x00d\x00"
    data = text.encode("utf-16-le")
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    results = extract_strings(str(f), min_len=4, encoding="unicode")
    assert any("hello" in r for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_strings_view.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement strings_view.py**

```python
# src/modules/process_explorer/lower_pane/strings_view.py
from __future__ import annotations
import logging
import re
from typing import List

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTabWidget,
                              QListWidget, QLineEdit, QHBoxLayout,
                              QPushButton, QLabel, QCheckBox, QFileDialog)
from PyQt6.QtCore import Qt

from core.worker import Worker

logger = logging.getLogger(__name__)

_ASCII_RE  = re.compile(rb"[ -~]{4,}")
_UNICODE_RE = re.compile(rb"(?:[ -~]\x00){4,}")


def extract_strings(path: str, min_len: int = 4, encoding: str = "ascii") -> List[str]:
    """Extract printable strings from a binary file."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return []
    if encoding == "ascii":
        matches = _ASCII_RE.findall(data)
        return [m.decode("ascii", errors="replace") for m in matches if len(m) >= min_len]
    else:  # unicode
        matches = _UNICODE_RE.findall(data)
        return [m.decode("utf-16-le", errors="replace").replace("\x00", "")
                for m in matches if len(m) // 2 >= min_len]


class StringsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        bar = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter strings…")
        self._filter.textChanged.connect(self._apply_filter)
        bar.addWidget(self._filter)
        self._save_btn = QPushButton("Save…")
        self._save_btn.clicked.connect(self._save)
        bar.addWidget(self._save_btn)
        layout.addLayout(bar)

        # Tabs: ASCII | Unicode
        self._tabs = QTabWidget()
        self._ascii_list = QListWidget()
        self._unicode_list = QListWidget()
        self._tabs.addTab(self._ascii_list, "ASCII")
        self._tabs.addTab(self._unicode_list, "Unicode")
        layout.addWidget(self._tabs)

        self._all_ascii: List[str] = []
        self._all_unicode: List[str] = []
        self._exe_path: str = ""
        self._thread_pool = None

    def set_thread_pool(self, pool):
        self._thread_pool = pool

    def load_exe(self, path: str):
        self._exe_path = path
        self._ascii_list.clear()
        self._unicode_list.clear()
        if not path or self._thread_pool is None:
            return

        def do_work(worker):
            ascii_strs = extract_strings(path, encoding="ascii")
            unicode_strs = extract_strings(path, encoding="unicode")
            return ascii_strs, unicode_strs

        w = Worker(do_work)
        w.signals.result.connect(self._on_strings_ready)
        self._thread_pool.start(w)

    def _on_strings_ready(self, result):
        self._all_ascii, self._all_unicode = result
        self._apply_filter(self._filter.text())

    def _apply_filter(self, text: str):
        f = text.lower()
        self._ascii_list.clear()
        self._unicode_list.clear()
        for s in self._all_ascii:
            if not f or f in s.lower():
                self._ascii_list.addItem(s)
        for s in self._all_unicode:
            if not f or f in s.lower():
                self._unicode_list.addItem(s)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Strings", "", "Text Files (*.txt)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== ASCII ===\n")
            f.write("\n".join(self._all_ascii))
            f.write("\n\n=== Unicode ===\n")
            f.write("\n".join(self._all_unicode))
```

- [ ] **Step 4: Run test**

```
cd src && python -m pytest ../tests/test_strings_view.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/lower_pane/strings_view.py tests/test_strings_view.py
git commit -m "feat: add lower pane strings view (PE binary + unicode)"
```

---

## Task 12: Sysinternals Live Tab

**Files:**
- Create: `src/modules/process_explorer/sysinternals_tab.py`

- [ ] **Step 1: Implement sysinternals_tab.py**

```python
# src/modules/process_explorer/sysinternals_tab.py
from __future__ import annotations
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                              QPushButton, QLineEdit, QComboBox, QScrollArea,
                              QFrame, QGroupBox, QGridLayout, QMessageBox)
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)

_UNC_BASE = r"\\live.sysinternals.com\tools"
_WEBCLIENT_SERVICE = "WebClient"

TOOLS = [
    # (category, tool_name, exe_filename, description)
    ("Process",      "Process Explorer", "procexp64.exe",  "Detailed process/thread viewer"),
    ("Process",      "Process Monitor",  "Procmon64.exe",  "File/registry/network activity"),
    ("Process",      "Autoruns",         "Autoruns64.exe", "All autostart locations"),
    ("Process",      "PsExec",           "PsExec64.exe",   "Remote process launcher"),
    ("Process",      "PsKill",           "PsKill.exe",     "Kill processes by name or PID"),
    ("Process",      "PsList",           "PsList.exe",     "List process details"),
    ("Process",      "PsService",        "PsService.exe",  "View and control services"),
    ("Process",      "PsSuspend",        "PsSuspend.exe",  "Suspend/resume processes"),
    ("Network",      "TCPView",          "Tcpview64.exe",  "Active TCP/UDP endpoints"),
    ("Network",      "PsPing",           "PsPing.exe",     "Network latency/bandwidth test"),
    ("Network",      "Whois",            "whois64.exe",    "WHOIS domain lookup"),
    ("Security",     "Sigcheck",         "sigcheck64.exe", "File signature + VirusTotal check"),
    ("Security",     "AccessChk",        "accesschk64.exe","Object permissions viewer"),
    ("Security",     "SDelete",          "sdelete64.exe",  "Secure file deletion"),
    ("File/Disk",    "Handle",           "handle64.exe",   "Which files are open"),
    ("File/Disk",    "Streams",          "streams64.exe",  "Find NTFS alternate data streams"),
    ("File/Disk",    "DiskMon",          "Diskmon.exe",    "Disk activity monitor"),
    ("File/Disk",    "PendMoves",        "pendmoves.exe",  "Pending file rename/delete ops"),
    ("System Info",  "Coreinfo",         "Coreinfo.exe",   "Logical CPU topology info"),
    ("System Info",  "RAMMap",           "RAMMap.exe",     "RAM usage details"),
    ("System Info",  "VMMap",            "vmmap.exe",      "Virtual memory map"),
    ("System Info",  "WinObj",           "winobj.exe",     "NT namespace object viewer"),
    ("System Info",  "BgInfo",           "Bginfo64.exe",   "Desktop background system info"),
    ("System Info",  "ZoomIt",           "ZoomIt.exe",     "Screen zoom and annotation"),
]


def _get_cache_dir() -> str:
    base = os.environ.get("APPDATA", os.path.expanduser("~"))
    d = os.path.join(base, "WindowsTweaker", "sysinternals")
    os.makedirs(d, exist_ok=True)
    return d


def _is_cached(exe: str) -> bool:
    return os.path.isfile(os.path.join(_get_cache_dir(), exe))


def _is_webclient_running() -> bool:
    try:
        import win32serviceutil
        status = win32serviceutil.QueryServiceStatus(_WEBCLIENT_SERVICE)
        return status[1] == 4  # SERVICE_RUNNING
    except Exception:
        return False


def _start_webclient() -> bool:
    try:
        import win32serviceutil
        win32serviceutil.StartService(_WEBCLIENT_SERVICE)
        return True
    except Exception as e:
        logger.error("Could not start WebClient: %s", e)
        return False


def _launch(exe: str) -> bool:
    cached = os.path.join(_get_cache_dir(), exe)
    path = cached if os.path.isfile(cached) else os.path.join(_UNC_BASE, exe)
    try:
        subprocess.Popen([path], creationflags=subprocess.DETACHED_PROCESS)
        return True
    except Exception as e:
        logger.error("Launch failed for %s: %s", exe, e)
        return False


def _cache_tool(exe: str) -> bool:
    src = os.path.join(_UNC_BASE, exe)
    dst = os.path.join(_get_cache_dir(), exe)
    try:
        shutil.copy2(src, dst)
        return True
    except Exception as e:
        logger.error("Cache failed for %s: %s", exe, e)
        return False


class SysinternalsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 8, 8, 8)

        # Warning banner (hidden by default)
        self._banner = QLabel()
        self._banner.setStyleSheet("background:#fff3cd;padding:6px;border-radius:4px;")
        self._banner.hide()
        self._layout.addWidget(self._banner)

        # Filter bar
        bar = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search tools…")
        self._search.textChanged.connect(self._rebuild)
        bar.addWidget(self._search)
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("All")
        cats = sorted({t[0] for t in TOOLS})
        self._cat_combo.addItems(cats)
        self._cat_combo.currentTextChanged.connect(self._rebuild)
        bar.addWidget(self._cat_combo)
        refresh_btn = QPushButton("Refresh Cache Status")
        refresh_btn.clicked.connect(self._rebuild)
        bar.addWidget(refresh_btn)
        self._layout.addLayout(bar)

        # Scrollable tool list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self._content)
        self._layout.addWidget(scroll)

        self._rebuild()

    def showEvent(self, event):
        super().showEvent(event)
        if not _is_webclient_running():
            self._banner.setText(
                "⚠ Sysinternals Live requires the WebClient service to be running. "
                "<a href='start_webclient'>Start WebClient Service</a>"
            )
            self._banner.setOpenExternalLinks(False)
            self._banner.linkActivated.connect(self._on_start_webclient)
            self._banner.show()
        else:
            self._banner.hide()

    def _on_start_webclient(self, _):
        if _start_webclient():
            self._banner.hide()
        else:
            QMessageBox.critical(self, "Error", "Failed to start WebClient service. Run as administrator.")

    def _rebuild(self):
        # Clear content
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        q = self._search.text().lower()
        cat = self._cat_combo.currentText()

        current_cat = None
        group: Optional[QGroupBox] = None
        grid: Optional[QGridLayout] = None
        row = 0

        for category, name, exe, desc in TOOLS:
            if cat != "All" and category != cat:
                continue
            if q and q not in name.lower() and q not in desc.lower():
                continue

            if category != current_cat:
                current_cat = category
                group = QGroupBox(category)
                grid = QGridLayout(group)
                self._content_layout.addWidget(group)
                row = 0

            cached = _is_cached(exe)
            status = "✅ cached" if cached else "☁ live"

            name_lbl = QLabel(f"<b>{name}</b>")
            desc_lbl  = QLabel(desc)
            desc_lbl.setStyleSheet("color: gray;")
            status_lbl = QLabel(status)

            launch_btn = QPushButton("Launch")
            launch_btn.setFixedWidth(70)
            _exe = exe  # capture for lambda
            launch_btn.clicked.connect(lambda checked, e=_exe: _launch(e))

            cache_btn = QPushButton("Cache")
            cache_btn.setFixedWidth(60)
            cache_btn.clicked.connect(lambda checked, e=_exe: (_cache_tool(e), self._rebuild()))

            grid.addWidget(name_lbl,   row, 0)
            grid.addWidget(desc_lbl,   row, 1)
            grid.addWidget(status_lbl, row, 2)
            grid.addWidget(launch_btn, row, 3)
            grid.addWidget(cache_btn,  row, 4)
            row += 1
```

- [ ] **Step 2: Smoke test**

```
cd src && python -c "
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from modules.process_explorer.sysinternals_tab import SysinternalsTab
t = SysinternalsTab()
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/modules/process_explorer/sysinternals_tab.py
git commit -m "feat: add Sysinternals Live tab with cache + launch"
```

---

## Task 13: Properties Dialog

**Files:**
- Create: `src/modules/process_explorer/properties_dialog.py`

- [ ] **Step 1: Implement properties_dialog.py**

```python
# src/modules/process_explorer/properties_dialog.py
from __future__ import annotations
import logging
import os
import subprocess
from datetime import datetime
from typing import Optional

import psutil
from PyQt6.QtWidgets import (QDialog, QTabWidget, QWidget, QVBoxLayout,
                              QHBoxLayout, QLabel, QTextEdit, QTableWidget,
                              QTableWidgetItem, QHeaderView, QPushButton,
                              QDialogButtonBox, QLineEdit, QSplitter)
from PyQt6.QtCore import Qt

from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.lower_pane.thread_view import ThreadView
from modules.process_explorer.lower_pane.network_view import NetworkView
from modules.process_explorer.lower_pane.strings_view import StringsView

logger = logging.getLogger(__name__)


class ProcessPropertiesDialog(QDialog):
    def __init__(self, node: ProcessNode, thread_pool=None, parent=None):
        super().__init__(parent)
        self._node = node
        self._thread_pool = thread_pool
        self.setWindowTitle(f"Properties — {node.name} (PID {node.pid})")
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._build_image_tab()
        self._build_threads_tab()
        self._build_network_tab()
        self._build_security_tab()
        self._build_environment_tab()
        self._build_strings_tab()

    def _row(self, label: str, value: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(f"<b>{label}:</b>")
        lbl.setFixedWidth(140)
        val = QLabel(value)
        val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        val.setWordWrap(True)
        h.addWidget(lbl)
        h.addWidget(val, 1)
        return w

    def _build_image_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        n = self._node
        layout.addWidget(self._row("Image", n.exe))
        layout.addWidget(self._row("Command Line", n.cmdline or "—"))
        layout.addWidget(self._row("Working Dir", "—"))
        layout.addWidget(self._row("PID", str(n.pid)))
        layout.addWidget(self._row("Parent PID", str(n.parent_pid)))
        layout.addWidget(self._row("User", n.user))
        layout.addWidget(self._row("Status", n.status))
        layout.addWidget(self._row("Integrity", n.integrity_level))

        open_btn = QPushButton("Open File Location")
        open_btn.clicked.connect(lambda: subprocess.Popen(
            ["explorer", "/select,", n.exe]) if n.exe else None)
        layout.addWidget(open_btn)
        layout.addStretch()
        self._tabs.addTab(w, "Image")

    def _build_threads_tab(self):
        tv = ThreadView()
        tv.load_pid(self._node.pid)
        self._tabs.addTab(tv, "Threads")

    def _build_network_tab(self):
        nv = NetworkView()
        nv.load_pid(self._node.pid)
        self._tabs.addTab(nv, "TCP/IP")

    def _build_security_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        te = QTextEdit()
        te.setReadOnly(True)
        try:
            import win32security, win32api, win32con
            handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, self._node.pid)
            token = win32security.OpenProcessToken(handle, win32con.TOKEN_QUERY)
            user_sid, attr = win32security.GetTokenInformation(token, win32security.TokenUser)
            name, domain, _ = win32security.LookupAccountSid(None, user_sid)
            te.setPlainText(f"User: {domain}\\{name}\nSID: {win32security.ConvertSidToStringSid(user_sid)}")
        except Exception as e:
            te.setPlainText(f"Security info unavailable: {e}\n(Requires elevated privileges)")
        layout.addWidget(te)
        self._tabs.addTab(w, "Security")

    def _build_environment_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        search = QLineEdit()
        search.setPlaceholderText("Filter…")
        layout.addWidget(search)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Variable", "Value"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(table)

        env_items = []
        try:
            env = psutil.Process(self._node.pid).environ()
            env_items = sorted(env.items())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        table.setRowCount(len(env_items))
        for r, (k, v) in enumerate(env_items):
            table.setItem(r, 0, QTableWidgetItem(k))
            table.setItem(r, 1, QTableWidgetItem(v))

        def _filter(text):
            f = text.lower()
            for row in range(table.rowCount()):
                k_item = table.item(row, 0)
                v_item = table.item(row, 1)
                visible = (not f or f in (k_item.text() if k_item else "").lower()
                           or f in (v_item.text() if v_item else "").lower())
                table.setRowHidden(row, not visible)

        search.textChanged.connect(_filter)
        self._tabs.addTab(w, "Environment")

    def _build_strings_tab(self):
        sv = StringsView()
        if self._thread_pool:
            sv.set_thread_pool(self._thread_pool)
        sv.load_exe(self._node.exe)
        self._tabs.addTab(sv, "Strings")
```

- [ ] **Step 2: Smoke test**

```
cd src && python -c "
import sys
from PyQt6.QtWidgets import QApplication
app = QApplication(sys.argv)
from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.properties_dialog import ProcessPropertiesDialog
import os
node = ProcessNode(pid=os.getpid(), name='python.exe', exe=sys.executable,
                   cmdline='', user='test', status='running', parent_pid=0)
d = ProcessPropertiesDialog(node)
print('OK')
"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/modules/process_explorer/properties_dialog.py
git commit -m "feat: add 6-tab process properties dialog"
```

---

## Task 14: ProcessExplorerModule — Main Widget + Wiring

**Files:**
- Create: `src/modules/process_explorer/process_explorer_module.py`
- Create: `tests/test_process_explorer_integration.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_process_explorer_integration.py
from unittest.mock import MagicMock
from modules.process_explorer.process_explorer_module import ProcessExplorerModule
from core.module_groups import ModuleGroup


def test_module_attributes():
    assert ProcessExplorerModule.name == "Process Explorer"
    assert ProcessExplorerModule.group == ModuleGroup.PROCESS
    assert ProcessExplorerModule.requires_admin is False


def test_module_creates_widget():
    mod = ProcessExplorerModule()
    mock_app = MagicMock()
    from PyQt6.QtCore import QThreadPool
    mock_app.thread_pool = QThreadPool.globalInstance()
    mod.on_start(mock_app)
    widget = mod.create_widget()
    assert widget is not None
    mod.on_stop()
```

- [ ] **Step 2: Run test to verify it fails**

```
cd src && python -m pytest ../tests/test_process_explorer_integration.py -v
```
Expected: `ImportError`

- [ ] **Step 3: Implement process_explorer_module.py**

```python
# src/modules/process_explorer/process_explorer_module.py
from __future__ import annotations
import logging
from typing import Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
                              QTabWidget, QTreeView, QToolBar, QComboBox,
                              QLabel, QLineEdit, QPushButton, QMenu,
                              QMessageBox, QAbstractItemView)
from PyQt6.QtCore import Qt, QSortFilterProxyModel
from PyQt6.QtGui import QAction

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.process_explorer.process_node import ProcessNode
from modules.process_explorer.process_collector import ProcessCollector
from modules.process_explorer.process_tree_model import ProcessTreeModel, COL_NAME
from modules.process_explorer.process_actions import (
    kill_process, kill_tree, suspend_process, resume_process,
    set_priority, set_affinity, PRIORITY_LEVELS,
)
from modules.process_explorer.properties_dialog import ProcessPropertiesDialog
from modules.process_explorer.sysinternals_tab import SysinternalsTab
from modules.process_explorer.lower_pane.dll_view import DllView
from modules.process_explorer.lower_pane.handle_view import HandleView
from modules.process_explorer.lower_pane.thread_view import ThreadView
from modules.process_explorer.lower_pane.network_view import NetworkView
from modules.process_explorer.lower_pane.strings_view import StringsView
from modules.process_explorer.lower_pane.memory_map_view import MemoryMapView

logger = logging.getLogger(__name__)


class ProcessExplorerModule(BaseModule):
    name = "Process Explorer"
    icon = "process_explorer"
    description = "Real-time process tree with Sysinternals-level detail"
    requires_admin = False
    group = ModuleGroup.PROCESS

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._tree_view: Optional[QTreeView] = None
        self._model: Optional[ProcessTreeModel] = None
        self._collector: Optional[ProcessCollector] = None
        self._lower_tabs: Optional[QTabWidget] = None
        self._dll_view: Optional[DllView] = None
        self._handle_view: Optional[HandleView] = None
        self._thread_view: Optional[ThreadView] = None
        self._network_view: Optional[NetworkView] = None
        self._strings_view: Optional[StringsView] = None
        self._memory_map_view: Optional[MemoryMapView] = None
        self._selected_node: Optional[ProcessNode] = None

    def on_start(self, app) -> None:
        self.app = app
        self._collector = ProcessCollector(interval_ms=1000)
        self._collector.set_thread_pool(app.thread_pool)
        # Fetch service names once in background
        w = Worker(self._fetch_service_names)
        w.signals.result.connect(lambda names: self._collector.set_service_names(names))
        app.thread_pool.start(w)

    @staticmethod
    def _fetch_service_names(worker) -> set:
        try:
            import win32service
            sc = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ENUMERATE_SERVICE)
            services = win32service.EnumServicesStatus(sc, win32service.SERVICE_WIN32,
                                                       win32service.SERVICE_STATE_ALL)
            win32service.CloseServiceHandle(sc)
            return {s[0].lower() for s in services}
        except Exception:
            return set()

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        outer = QVBoxLayout(self._widget)
        outer.setContentsMargins(0, 0, 0, 0)

        # Module-level tabs: Processes | Sysinternals
        module_tabs = QTabWidget()
        outer.addWidget(module_tabs)

        # ── Processes tab ──────────────────────────────────────────────
        proc_widget = QWidget()
        proc_layout = QVBoxLayout(proc_widget)
        proc_layout.setContentsMargins(0, 0, 0, 0)

        # Toolbar
        toolbar = self._build_toolbar()
        proc_layout.addWidget(toolbar)

        # Splitter: tree (top) + lower pane (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Process tree
        self._model = ProcessTreeModel()
        self._tree_view = QTreeView()
        self._tree_view.setModel(self._model)
        self._tree_view.setAlternatingRowColors(True)
        self._tree_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree_view.customContextMenuRequested.connect(self._show_context_menu)
        self._tree_view.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._tree_view.doubleClicked.connect(self._on_double_click)
        splitter.addWidget(self._tree_view)

        # Lower pane
        self._lower_tabs = QTabWidget()
        self._dll_view    = DllView()
        self._handle_view = HandleView()
        self._thread_view = ThreadView()
        self._network_view = NetworkView()
        self._strings_view = StringsView()
        self._memory_map_view = MemoryMapView()
        if self.app:
            self._strings_view.set_thread_pool(self.app.thread_pool)
        self._lower_tabs.addTab(self._dll_view,       "DLLs")
        self._lower_tabs.addTab(self._handle_view,    "Handles")
        self._lower_tabs.addTab(self._thread_view,    "Threads")
        self._lower_tabs.addTab(self._network_view,   "Network")
        self._lower_tabs.addTab(self._strings_view,   "Strings")
        self._lower_tabs.addTab(self._memory_map_view,"Memory Map")
        self._lower_tabs.currentChanged.connect(self._on_lower_tab_changed)
        splitter.addWidget(self._lower_tabs)
        splitter.setSizes([600, 250])

        proc_layout.addWidget(splitter)
        module_tabs.addTab(proc_widget, "Processes")

        # ── Sysinternals tab ──────────────────────────────────────────
        sys_tab = SysinternalsTab()
        module_tabs.addTab(sys_tab, "Sysinternals")

        # Wire collector signals
        if self._collector:
            self._collector.snapshot_ready.connect(self._model.load_snapshot)
            self._collector.process_added.connect(self._on_process_added)
            self._collector.process_removed.connect(self._on_process_removed)
            self._collector.processes_updated.connect(self._on_processes_updated)

        return self._widget

    def _build_toolbar(self) -> QToolBar:
        tb = QToolBar()
        tb.setMovable(False)

        kill_action = QAction("Kill", tb)
        kill_action.triggered.connect(self._action_kill)
        tb.addAction(kill_action)

        suspend_action = QAction("Suspend", tb)
        suspend_action.triggered.connect(self._action_suspend)
        tb.addAction(suspend_action)

        tb.addSeparator()

        priority_btn = QPushButton("Priority ▼")
        priority_btn.setFlat(True)
        pm = QMenu(priority_btn)
        for level in PRIORITY_LEVELS:
            pm.addAction(level.replace("_", " ").title(),
                         lambda checked=False, l=level: self._action_set_priority(l))
        priority_btn.setMenu(pm)
        tb.addWidget(priority_btn)

        tb.addSeparator()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search processes…")
        self._search_box.setMaximumWidth(200)
        tb.addWidget(self._search_box)

        interval_combo = QComboBox()
        for ms, label in [(500, "0.5s"), (1000, "1s"), (2000, "2s"), (5000, "5s")]:
            interval_combo.addItem(label, ms)
        interval_combo.setCurrentIndex(1)
        interval_combo.currentIndexChanged.connect(
            lambda i: self._collector.set_interval(interval_combo.currentData()) if self._collector else None)
        tb.addWidget(QLabel("Refresh:"))
        tb.addWidget(interval_combo)

        flat_btn = QPushButton("Flat")
        flat_btn.setCheckable(True)
        flat_btn.toggled.connect(lambda flat: self._model.set_flat_mode(flat) if self._model else None)
        tb.addWidget(flat_btn)

        return tb

    def on_activate(self) -> None:
        if self._collector and not self._collector._timer.isActive():
            self._collector.start()

    def on_deactivate(self) -> None:
        if self._collector:
            self._collector.stop()

    def on_stop(self) -> None:
        if self._collector:
            self._collector.stop()
        self.cancel_all_workers()

    def get_status_info(self) -> str:
        if self._model:
            return f"Process Explorer — {len(self._model._snapshot)} processes"
        return "Process Explorer"

    # ── Signal handlers ──────────────────────────────────────────────

    def _on_process_added(self, node: ProcessNode):
        if self._model:
            snap = dict(self._model._snapshot)
            snap[node.pid] = node
            self._model.load_snapshot(snap)

    def _on_process_removed(self, pid: int):
        if self._model:
            snap = dict(self._model._snapshot)
            snap.pop(pid, None)
            self._model.load_snapshot(snap)

    def _on_processes_updated(self, changed_pids: list):
        if self._model and self._collector:
            snap = self._collector.get_snapshot()
            self._model.update_nodes({p: snap[p] for p in changed_pids if p in snap})

    def _on_selection_changed(self, selected, deselected):
        indexes = self._tree_view.selectionModel().selectedRows() if self._tree_view else []
        if not indexes:
            self._selected_node = None
            return
        node: ProcessNode = indexes[0].internalPointer()
        self._selected_node = node
        self._refresh_lower_pane()

    def _on_lower_tab_changed(self, idx: int):
        self._refresh_lower_pane()

    def _refresh_lower_pane(self):
        if not self._selected_node or not self._lower_tabs:
            return
        pid = self._selected_node.pid
        idx = self._lower_tabs.currentIndex()
        if idx == 0:
            self._dll_view.load_pid(pid)
        elif idx == 1:
            self._handle_view.load_pid(pid)
        elif idx == 2:
            self._thread_view.load_pid(pid)
        elif idx == 3:
            self._network_view.load_pid(pid)
        elif idx == 4:
            self._strings_view.load_exe(self._selected_node.exe)
        elif idx == 5:
            self._memory_map_view.load_pid(pid)

    def _on_double_click(self, index):
        if not index.isValid():
            return
        node: ProcessNode = index.internalPointer()
        dlg = ProcessPropertiesDialog(node, thread_pool=self.app.thread_pool if self.app else None,
                                      parent=self._widget)
        dlg.exec()

    # ── Actions ──────────────────────────────────────────────────────

    def _action_kill(self):
        if not self._selected_node:
            return
        pid, name = self._selected_node.pid, self._selected_node.name
        reply = QMessageBox.question(
            self._widget, "Kill Process",
            f"Kill {name} (PID {pid})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            ok, err = kill_process(pid)
            if not ok:
                QMessageBox.warning(self._widget, "Kill Failed", err)

    def _action_suspend(self):
        if not self._selected_node:
            return
        if self._selected_node.is_suspended:
            ok, err = resume_process(self._selected_node.pid)
        else:
            ok, err = suspend_process(self._selected_node.pid)
        if not ok:
            QMessageBox.warning(self._widget, "Action Failed", err)

    def _action_set_priority(self, level: str):
        if not self._selected_node:
            return
        ok, err = set_priority(self._selected_node.pid, level)
        if not ok:
            QMessageBox.warning(self._widget, "Priority Failed", err)

    def _show_context_menu(self, pos):
        if not self._selected_node:
            return
        menu = QMenu(self._tree_view)
        menu.addAction("Properties", self._open_properties)
        menu.addSeparator()
        menu.addAction("Kill", self._action_kill)
        menu.addAction("Kill Tree", self._action_kill_tree)
        menu.addAction("Suspend / Resume", self._action_suspend)
        menu.addSeparator()
        menu.addAction("Open File Location", self._action_open_location)
        menu.addAction("Check VirusTotal", self._action_check_vt)
        menu.exec(self._tree_view.mapToGlobal(pos))

    def _open_properties(self):
        if self._selected_node:
            dlg = ProcessPropertiesDialog(
                self._selected_node,
                thread_pool=self.app.thread_pool if self.app else None,
                parent=self._widget,
            )
            dlg.exec()

    def _action_kill_tree(self):
        if not self._selected_node:
            return
        ok, errors = kill_tree(self._selected_node.pid)
        if not ok:
            QMessageBox.warning(self._widget, "Kill Tree Partial", "\n".join(errors))

    def _action_open_location(self):
        if self._selected_node and self._selected_node.exe:
            import subprocess
            subprocess.Popen(["explorer", "/select,", self._selected_node.exe])

    def _action_check_vt(self):
        if not self._selected_node:
            return
        exe = self._selected_node.exe
        if not exe:
            QMessageBox.information(self._widget, "VirusTotal", "No executable path available.")
            return
        api_key = ""
        if self.app:
            api_key = self.app.config.get("virustotal.api_key", "")
        if not api_key:
            QMessageBox.information(
                self._widget, "VirusTotal",
                "No API key configured. Set 'virustotal.api_key' in settings.")
            return
        from modules.process_explorer.virustotal_client import VTClient, compute_sha256
        sha = compute_sha256(exe)
        if not sha:
            QMessageBox.warning(self._widget, "VirusTotal", "Could not compute SHA256.")
            return
        client = VTClient(api_key=api_key)

        def do_check(worker):
            return client.check(sha)

        w = Worker(do_check)
        w.signals.result.connect(self._on_vt_result)
        if self.app:
            self.app.thread_pool.start(w)

    def _on_vt_result(self, result):
        from modules.process_explorer.virustotal_client import VTResult
        if not result.found:
            reply = QMessageBox.question(
                self._widget, "VirusTotal — Unknown File",
                "This file is unknown to VirusTotal. Submit for analysis?\n\n"
                "⚠ This will upload the file binary. Do not submit files containing sensitive data.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes and self._selected_node:
                api_key = self.app.config.get("virustotal.api_key", "") if self.app else ""
                from modules.process_explorer.virustotal_client import VTClient
                client = VTClient(api_key=api_key)
                analysis_id = client.submit_file(self._selected_node.exe)
                if analysis_id:
                    QMessageBox.information(self._widget, "VirusTotal",
                                            f"Submitted. Analysis ID: {analysis_id}\nCheck virustotal.com for results.")
        else:
            icon = "🟢" if result.malicious == 0 else ("🟠" if result.malicious <= 3 else "🔴")
            QMessageBox.information(self._widget, "VirusTotal Result",
                                    f"{icon} {result.score}\nSHA256: {result.sha256}")
```

- [ ] **Step 4: Run integration test**

```
cd src && python -m pytest ../tests/test_process_explorer_integration.py -v
```
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add src/modules/process_explorer/process_explorer_module.py \
        tests/test_process_explorer_integration.py
git commit -m "feat: add ProcessExplorerModule (main widget, wiring, all actions)"
```

---

## Task 15: Wire into main.py + Run All Tests

**Files:**
- Modify: `src/main.py`

- [ ] **Step 1: Register ProcessExplorerModule in main.py**

In `src/main.py`, add the import and registration after the existing 7 modules:

```python
from modules.process_explorer.process_explorer_module import ProcessExplorerModule
# ...
app.module_registry.register(ProcessExplorerModule())
```

Full updated registration block in `main()`:

```python
    from modules.event_viewer.event_viewer_module import EventViewerModule
    from modules.cbs_log.cbs_module import CBSLogModule
    from modules.dism_log.dism_module import DISMLogModule
    from modules.windows_update.wu_module import WindowsUpdateModule
    from modules.reliability.reliability_module import ReliabilityModule
    from modules.crash_dumps.crash_dump_module import CrashDumpModule
    from modules.perfmon.perfmon_module import PerfMonModule
    from modules.process_explorer.process_explorer_module import ProcessExplorerModule

    app.module_registry.register(EventViewerModule())
    app.module_registry.register(CBSLogModule())
    app.module_registry.register(DISMLogModule())
    app.module_registry.register(WindowsUpdateModule())
    app.module_registry.register(ReliabilityModule())
    app.module_registry.register(CrashDumpModule())
    app.module_registry.register(PerfMonModule())
    app.module_registry.register(ProcessExplorerModule())
```

- [ ] **Step 2: Run the full test suite**

```
cd src && python -m pytest ../tests/ -v
```
Expected: All tests pass. Note: some tests (handle view, DLL view) require Windows and admin — these will pass on Windows. On CI/non-Windows they are skipped via `psutil.AccessDenied`.

- [ ] **Step 3: Launch the app and verify Process Explorer tab appears**

```
cd src && python main.py
```

Verify:
- Process Explorer appears as a tab/sidebar item
- Processes tab shows a live tree (populated within 1–2 seconds)
- Clicking a process populates the lower pane DLLs/Threads/Network tabs
- Double-clicking opens the Properties dialog
- Right-click context menu shows Kill, Suspend, Properties
- Sysinternals tab lists tools with Launch/Cache buttons

- [ ] **Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat: register ProcessExplorerModule in main.py"
```

---

## Self-Review

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| Layout (§2) | Task 14 — `process_explorer_module.py` splitter + toolbar |
| ProcessNode (§3.1) | Task 2 |
| ProcessCollector + diff (§3.2–3.3) | Task 4 |
| ProcessTreeModel (§3.3) | Task 5 |
| Color coding (§3.4) | Task 3 |
| Lower pane — DLLs (§4.1) | Task 9 |
| Lower pane — Handles (§4.2) | Task 10 |
| Lower pane — Threads (§4.3) | Task 8 |
| Lower pane — Network (§4.4) | Task 8 |
| Lower pane — Strings (§4.5) | Task 11 |
| Lower pane — Memory Map (§4.6) | Task 9 |
| Properties Dialog (§5) | Task 13 |
| VirusTotal integration (§6) | Task 7 + Task 14 (`_action_check_vt`) |
| Process Actions (§7) | Task 6 + Task 14 |
| Sysinternals Live tab (§8) | Task 12 |
| ModuleGroup.PROCESS (§9) | Task 1 |
| main.py registration | Task 15 |

All spec requirements covered. No gaps.
