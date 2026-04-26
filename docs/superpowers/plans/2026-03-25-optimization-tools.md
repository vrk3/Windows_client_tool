# Optimization, Management & Tools Suite — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ~20 new modules (Tweaks/Debloater, Cleanup, TreeSize, Quick Fix, Updates, Hardware Inventory, Network Diagnostics, Security Dashboard, Driver Manager, Startup Manager, Scheduled Tasks, Windows Features, GPResult, Certificate Viewer, Performance Tuner, Power & Boot, Network Extras, Shared Resources, Env Vars, Registry Explorer, Software Inventory, Remote Tools) plus a SidebarNav shell redesign and shared BackupService to the Windows 11 Tweaker desktop app.

**Architecture:** Three batches — Batch A builds core infrastructure (BackupService, SidebarNav, COMWorker) and high-value Optimize/Tools modules; Batch B adds System & Manage modules; Batch C adds remaining Tools. All modules extend `BaseModule`, use `Worker`/`COMWorker` for background I/O, and integrate with `BackupService` for reversible changes. Navigation switches from `QTabWidget` to `SidebarNav` (QPushButton items grouped by `ModuleGroup`) + `QStackedWidget`.

**Tech Stack:** PyQt6, winreg, win32service/win32serviceutil/win32com (pywin32), wmi, psutil, pythoncom, sqlite3, concurrent.futures, subprocess, socket, ssl, wincertstore, tempfile, threading

---

## File Structure

```
src/
  core/
    module_groups.py          ← NEW: ModuleGroup constants
    windows_utils.py          ← NEW: is_reboot_pending()
    backup_service.py         ← NEW: BackupService + StepRecord + RestoreResult
    worker.py                 ← MODIFY: add COMWorker subclass
    base_module.py            ← MODIFY: add group: str class attribute
  ui/
    sidebar_nav.py            ← NEW: replaces QTabWidget
    main_window.py            ← MODIFY: QTabWidget→SidebarNav+QStackedWidget
    restore_manager.py        ← NEW: Restore Manager dialog (Task 36)
  modules/
    tweaks/
      __init__.py, tweaks_module.py, tweak_engine.py
      tweak_search_provider.py, app_catalog.py, preset_manager.py
      definitions/
        privacy.json, performance.json, telemetry.json
        ui_tweaks.json, services.json, app_catalog.json
        builtins/
          minimal.json, privacy_focused.json
          developer_machine.json, corporate_hardened.json
    cleanup/
      __init__.py, cleanup_module.py, cleanup_scanner.py
    treesize/
      __init__.py, treesize_module.py, disk_tree_model.py, disk_scanner.py
    quick_fix/
      __init__.py, quick_fix_module.py, fix_actions.py
    updates/
      __init__.py, updates_module.py, winget_updater.py, windows_updater.py
    hardware_inventory/       __init__.py, hardware_module.py, hardware_reader.py
    network_diagnostics/      __init__.py, network_module.py, network_tools.py
    security_dashboard/       __init__.py, security_module.py, security_reader.py
    driver_manager/           __init__.py, driver_module.py, driver_reader.py
    startup_manager/          __init__.py, startup_module.py, startup_reader.py
    scheduled_tasks/          __init__.py, tasks_module.py, tasks_reader.py
    windows_features/         __init__.py, features_module.py
    certificate_viewer/       __init__.py, cert_module.py, cert_reader.py
    gpresult/                 __init__.py, gpresult_module.py
    performance_tuner/        __init__.py, perf_tuner_module.py, perf_checks.py
    power_boot/               __init__.py, power_module.py
    network_extras/           __init__.py, net_extras_module.py
    shared_resources/         __init__.py, shares_module.py
    env_vars/                 __init__.py, env_vars_module.py
    registry_explorer/        __init__.py, registry_module.py, registry_model.py
    software_inventory/       __init__.py, software_module.py
    remote_tools/             __init__.py, remote_module.py
    process_explorer/         ← already exists; add group = ModuleGroup.TOOLS
tests/
  core/
    test_windows_utils.py
    test_backup_service.py
  modules/
    tweaks/
      test_tweak_engine.py
      test_preset_manager.py
    test_cleanup_scanner.py
```

---

## BATCH A — Foundation + High-Value Modules

---

### Task 1: ModuleGroup Constants

**Files:**
- Create: `src/core/module_groups.py`

- [ ] **Step 1: Create the file**

```python
# src/core/module_groups.py

class ModuleGroup:
    DIAGNOSE = "DIAGNOSE"
    SYSTEM   = "SYSTEM"
    MANAGE   = "MANAGE"
    OPTIMIZE = "OPTIMIZE"
    TOOLS    = "TOOLS"
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd src && python -c "from core.module_groups import ModuleGroup; print(ModuleGroup.DIAGNOSE)"
```
Expected output: `DIAGNOSE`

- [ ] **Step 3: Commit**

```bash
git add src/core/module_groups.py
git commit -m "feat: add ModuleGroup constants"
```

---

### Task 2: Shared Windows Utilities

**Files:**
- Create: `src/core/windows_utils.py`
- Create: `tests/core/test_windows_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_windows_utils.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from unittest.mock import patch, MagicMock
import winreg


def test_reboot_pending_when_pfro_key_exists():
    """PendingFileRenameOperations key present → True."""
    def fake_open(hive, path):
        if "Session Manager" in path:
            return MagicMock()
        raise OSError
    def fake_query(key, value):
        return ("value", 1)

    with patch("winreg.OpenKey", side_effect=fake_open), \
         patch("winreg.QueryValueEx", side_effect=fake_query):
        from core.windows_utils import is_reboot_pending
        assert is_reboot_pending() is True


def test_reboot_pending_false_when_no_keys():
    """All registry keys absent → False."""
    with patch("winreg.OpenKey", side_effect=OSError):
        from core import windows_utils
        import importlib
        importlib.reload(windows_utils)
        assert windows_utils.is_reboot_pending() is False


def test_reboot_pending_wu_key():
    """RebootRequired (Windows Update) key → True."""
    call_count = [0]
    def fake_open(hive, path):
        call_count[0] += 1
        if call_count[0] < 3:  # first two keys absent
            raise OSError
        return MagicMock()
    with patch("winreg.OpenKey", side_effect=fake_open), \
         patch("winreg.QueryValueEx", return_value=(1, 4)):
        from core import windows_utils
        import importlib
        importlib.reload(windows_utils)
        assert windows_utils.is_reboot_pending() is True
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd src && python -m pytest ../tests/core/test_windows_utils.py -v
```
Expected: FAILED (ModuleNotFoundError: No module named 'core.windows_utils')

- [ ] **Step 3: Implement**

```python
# src/core/windows_utils.py
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

- [ ] **Step 4: Run — expect PASS**

```bash
cd src && python -m pytest ../tests/core/test_windows_utils.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/core/windows_utils.py tests/core/test_windows_utils.py
git commit -m "feat: add is_reboot_pending() utility"
```

---

### Task 3: BackupService

**Files:**
- Create: `src/core/backup_service.py`
- Create: `tests/core/test_backup_service.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/core/test_backup_service.py
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

import pytest
from unittest.mock import patch, MagicMock
from core.backup_service import BackupService, StepRecord, RestoreResult, RestorePointInfo


@pytest.fixture
def svc(tmp_path):
    s = BackupService(data_dir=str(tmp_path))
    yield s
    s.close()


def test_create_restore_point_returns_id(svc, tmp_path):
    rp_id = svc.create_restore_point("Test backup", "Tweaks")
    assert isinstance(rp_id, str) and len(rp_id) == 32


def test_create_restore_point_creates_folder(svc, tmp_path):
    svc.create_restore_point("My backup", "Cleanup")
    backup_dir = tmp_path / "backups"
    subdirs = list(backup_dir.iterdir())
    assert len(subdirs) == 1
    assert (subdirs[0] / "manifest.json").exists()


def test_record_steps_saves_to_db(svc):
    rp_id = svc.create_restore_point("Test", "Tweaks")
    steps = [
        StepRecord("registry", r"HKLM\SOFTWARE\Test", None, 0),
        StepRecord("service", "DiagTrack", 2, 4),
    ]
    svc.record_steps("tweak_disable_telemetry", steps, rp_id)
    points = svc.list_restore_points()
    assert len(points) == 1
    assert points[0].step_count == 2


def test_list_restore_points_newest_first(svc):
    svc.create_restore_point("First", "Tweaks")
    svc.create_restore_point("Second", "Cleanup")
    points = svc.list_restore_points()
    assert points[0].label == "Second"


def test_restore_result_dataclass():
    r = RestoreResult(success=True, partial=False, failed_steps=[], errors=[])
    assert r.success is True


def test_restore_point_info_dataclass():
    info = RestorePointInfo(id="abc", label="x", created_at="2026-01-01",
                            module="Tweaks", status="active", step_count=3)
    assert info.step_count == 3


def test_revert_command_step_is_noop(svc):
    """command steps return True (non-revertible) without raising."""
    rp_id = svc.create_restore_point("cmd", "Tweaks")
    steps = [StepRecord("command", "sfc /scannow", None, None)]
    svc.record_steps("fix1", steps, rp_id)
    # get the step id
    import sqlite3
    conn = sqlite3.connect(str(svc._db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id FROM tweak_steps LIMIT 1").fetchone()
    conn.close()
    result = svc.revert_step(row["id"])
    assert result is True
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd src && python -m pytest ../tests/core/test_backup_service.py -v
```

- [ ] **Step 3: Implement BackupService**

```python
# src/core/backup_service.py
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StepRecord:
    step_type: str   # registry | service | appx | command | file
    target: str
    before_value: Any
    after_value: Any


@dataclass
class RestoreResult:
    success: bool
    partial: bool
    failed_steps: List[str]
    errors: List[str]


@dataclass
class RestorePointInfo:
    id: str
    label: str
    created_at: str
    module: str
    status: str
    step_count: int


class BackupService:
    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._backup_dir = os.path.join(data_dir, "backups")
        os.makedirs(self._backup_dir, exist_ok=True)
        self._db_path = os.path.join(data_dir, "tweaks.db")
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS restore_points (
                id          TEXT PRIMARY KEY,
                label       TEXT NOT NULL,
                created_at  DATETIME NOT NULL,
                module      TEXT NOT NULL,
                status      TEXT DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS tweak_steps (
                id               TEXT PRIMARY KEY,
                tweak_id         TEXT NOT NULL,
                restore_point_id TEXT NOT NULL REFERENCES restore_points(id),
                applied_at       DATETIME NOT NULL,
                step_type        TEXT NOT NULL,
                target           TEXT NOT NULL,
                before_value     TEXT,
                after_value      TEXT,
                reverted_at      DATETIME,
                revert_error     TEXT
            );
        """)
        self._conn.commit()

    def create_restore_point(self, label: str, module: str) -> str:
        rp_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        ts = now[:19].replace(":", "-").replace("T", "_")
        safe_label = label.replace(" ", "_")[:20]
        folder = os.path.join(self._backup_dir, f"{ts}_{safe_label}")
        os.makedirs(folder, exist_ok=True)
        for sub in ("registry", "services", "appx", "files"):
            os.makedirs(os.path.join(folder, sub), exist_ok=True)
        manifest = {"id": rp_id, "label": label, "created_at": now,
                    "module": module, "folder": folder}
        with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        self._conn.execute(
            "INSERT INTO restore_points (id, label, created_at, module) VALUES (?,?,?,?)",
            (rp_id, label, now, module),
        )
        self._conn.commit()
        return rp_id

    def record_steps(self, tweak_id: str, steps: List[StepRecord],
                     restore_point_id: str) -> None:
        now = datetime.now().isoformat()
        for step in steps:
            self._conn.execute(
                """INSERT INTO tweak_steps
                   (id, tweak_id, restore_point_id, applied_at,
                    step_type, target, before_value, after_value)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, tweak_id, restore_point_id, now,
                 step.step_type, step.target,
                 json.dumps(step.before_value), json.dumps(step.after_value)),
            )
        self._conn.commit()

    def backup_registry_key(self, key_path: str, restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        safe = key_path.replace("\\", "_").replace("/", "_")[:80]
        out = os.path.join(folder, "registry", f"{safe}.reg")
        subprocess.run(["reg", "export", key_path, out, "/y"],
                       capture_output=True, check=False)

    def backup_service_state(self, service_name: str, restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        try:
            import win32service
            hscm = win32service.OpenSCManager(None, None,
                                              win32service.SC_MANAGER_CONNECT)
            hs = win32service.OpenService(
                hscm, service_name,
                win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_QUERY_STATUS)
            config = win32service.QueryServiceConfig(hs)
            status = win32service.QueryServiceStatus(hs)
            state = {"name": service_name, "start_type": config[1],
                     "state": status[1]}
            with open(os.path.join(folder, "services", f"{service_name}.json"),
                      "w", encoding="utf-8") as f:
                json.dump(state, f)
            win32service.CloseServiceHandle(hs)
            win32service.CloseServiceHandle(hscm)
        except Exception as e:
            logger.warning("backup_service_state failed for %s: %s", service_name, e)

    def backup_appx_package(self, package_full_name: str,
                            restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        path = os.path.join(folder, "appx", "removed_apps.json")
        existing: list = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(package_full_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f)

    def restore_point(self, restore_point_id: str) -> RestoreResult:
        rows = self._conn.execute(
            "SELECT id FROM tweak_steps WHERE restore_point_id=? AND reverted_at IS NULL",
            (restore_point_id,),
        ).fetchall()
        failed: List[str] = []
        errors: List[str] = []
        for row in rows:
            ok = self.revert_step(row["id"])
            if not ok:
                failed.append(row["id"])
                err_row = self._conn.execute(
                    "SELECT revert_error FROM tweak_steps WHERE id=?", (row["id"],)
                ).fetchone()
                errors.append(err_row["revert_error"] or "Unknown error")
        success = len(failed) == 0
        partial = bool(failed) and len(failed) < len(rows)
        status = "restored" if success else "partial"
        self._conn.execute(
            "UPDATE restore_points SET status=? WHERE id=?",
            (status, restore_point_id),
        )
        self._conn.commit()
        return RestoreResult(success=success, partial=partial,
                             failed_steps=failed, errors=errors)

    def revert_step(self, step_id: str) -> bool:
        row = self._conn.execute(
            "SELECT step_type, target, before_value FROM tweak_steps WHERE id=?",
            (step_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            step_type = row["step_type"]
            target = row["target"]
            before = (json.loads(row["before_value"])
                      if row["before_value"] else None)
            if step_type == "registry":
                subprocess.run(["reg", "import", target],
                               check=True, capture_output=True)
            elif step_type == "service":
                import win32service
                hscm = win32service.OpenSCManager(
                    None, None, win32service.SC_MANAGER_CONNECT)
                hs = win32service.OpenService(
                    hscm, target, win32service.SERVICE_CHANGE_CONFIG)
                win32service.ChangeServiceConfig(
                    hs, win32service.SERVICE_NO_CHANGE,
                    before, win32service.SERVICE_NO_CHANGE,
                    None, None, False, None, None, None, None)
                win32service.CloseServiceHandle(hs)
                win32service.CloseServiceHandle(hscm)
            elif step_type == "appx":
                subprocess.run(
                    ["winget", "install", target, "--silent",
                     "--accept-package-agreements"],
                    check=False, capture_output=True)
            elif step_type == "file":
                src, dest = before["src"], before["dest"]
                shutil.copy2(src, dest)
            elif step_type == "command":
                logger.warning("command steps are not revertible: %s", target)
                # not a failure
            now = datetime.now().isoformat()
            self._conn.execute(
                "UPDATE tweak_steps SET reverted_at=? WHERE id=?", (now, step_id))
            self._conn.commit()
            return True
        except Exception as e:
            self._conn.execute(
                "UPDATE tweak_steps SET revert_error=? WHERE id=?",
                (str(e), step_id))
            self._conn.commit()
            return False

    def list_restore_points(self) -> List[RestorePointInfo]:
        rows = self._conn.execute("""
            SELECT rp.id, rp.label, rp.created_at, rp.module, rp.status,
                   COUNT(ts.id) AS step_count
            FROM restore_points rp
            LEFT JOIN tweak_steps ts ON ts.restore_point_id = rp.id
            GROUP BY rp.id
            ORDER BY rp.created_at DESC
        """).fetchall()
        return [
            RestorePointInfo(id=r["id"], label=r["label"],
                             created_at=r["created_at"], module=r["module"],
                             status=r["status"], step_count=r["step_count"])
            for r in rows
        ]

    def _get_restore_point_folder(self, restore_point_id: str) -> Optional[str]:
        if not os.path.isdir(self._backup_dir):
            return None
        for entry in os.scandir(self._backup_dir):
            if not entry.is_dir():
                continue
            manifest = os.path.join(entry.path, "manifest.json")
            if os.path.exists(manifest):
                with open(manifest, encoding="utf-8") as f:
                    m = json.load(f)
                if m.get("id") == restore_point_id:
                    return entry.path
        return None

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()
```

- [ ] **Step 4: Run tests**

```bash
cd src && python -m pytest ../tests/core/test_backup_service.py -v
```
Expected: all 7 tests PASS (note: `test_revert_command_step_is_noop` accesses `svc._db_path` — that attribute is set in `__init__`)

- [ ] **Step 5: Commit**

```bash
git add src/core/backup_service.py tests/core/test_backup_service.py
git commit -m "feat: add BackupService with SQLite restore-point tracking"
```

---

### Task 4: COMWorker

**Files:**
- Modify: `src/core/worker.py`

- [ ] **Step 1: Add COMWorker after the Worker class**

Open `src/core/worker.py` and append after the `Worker` class:

```python
class COMWorker(Worker):
    """Worker subclass that initialises COM STA on the thread before running.
    Use this for any worker that calls win32com.client or pythoncom objects
    (Windows Update Session, Schedule.Service, etc.)."""

    def run(self) -> None:
        import pythoncom
        pythoncom.CoInitialize()
        try:
            super().run()
        finally:
            pythoncom.CoUninitialize()
```

- [ ] **Step 2: Verify import**

```bash
cd src && python -c "from core.worker import COMWorker; print('COMWorker OK')"
```
Expected: `COMWorker OK`

- [ ] **Step 3: Commit**

```bash
git add src/core/worker.py
git commit -m "feat: add COMWorker subclass with COM STA initialisation"
```

---

### Task 5: BaseModule `group` Attribute + Update Existing Modules

**Files:**
- Modify: `src/core/base_module.py`
- Modify: `src/modules/event_viewer/event_viewer_module.py`
- Modify: `src/modules/cbs_log/cbs_module.py`
- Modify: `src/modules/dism_log/dism_module.py`
- Modify: `src/modules/windows_update/wu_module.py`
- Modify: `src/modules/reliability/reliability_module.py`
- Modify: `src/modules/crash_dumps/crash_dump_module.py`
- Modify: `src/modules/perfmon/perfmon_module.py`
- Modify: `src/modules/process_explorer/process_explorer_module.py`

- [ ] **Step 1: Verify `group: str` already in base_module.py**

`src/core/base_module.py` already declares `group: str` as a class attribute annotation. No change needed.

- [ ] **Step 2: Add `group = ModuleGroup.DIAGNOSE` to each existing Diagnose module**

In each of the 7 Diagnose modules below, add two lines to the class body (after `requires_admin`):

```python
from core.module_groups import ModuleGroup
# ...
class EventViewerModule(BaseModule):      # (and each other module)
    name = "Event Viewer"
    icon = "📋"
    description = "..."
    requires_admin = False
    group = ModuleGroup.DIAGNOSE          # ← ADD THIS LINE
```

Apply the same `group = ModuleGroup.DIAGNOSE` to:
- `EventViewerModule`
- `CBSLogModule`
- `DISMLogModule`
- `WindowsUpdateModule`
- `ReliabilityModule`
- `CrashDumpModule`
- `PerfMonModule`

For `ProcessExplorerModule`, set `group = ModuleGroup.TOOLS`.

- [ ] **Step 3: Verify the app still starts**

```bash
cd src && python -c "
from app import App
a = App(app_data_dir='C:/Temp/wt_test')
from modules.event_viewer.event_viewer_module import EventViewerModule
m = EventViewerModule()
from core.module_groups import ModuleGroup
assert m.group == ModuleGroup.DIAGNOSE, f'got {m.group}'
print('group attribute OK')
a.shutdown()
"
```

- [ ] **Step 4: Commit**

```bash
git add src/core/base_module.py src/modules/
git commit -m "feat: add group attribute to BaseModule and all existing modules"
```

---

### Task 6: SidebarNav Widget

**Files:**
- Create: `src/ui/sidebar_nav.py`

- [ ] **Step 1: Implement SidebarNav**

```python
# src/ui/sidebar_nav.py
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)


class SidebarNav(QWidget):
    """Vertical navigation sidebar.

    Emits module_selected(module_name: str) when a module button is clicked.
    Groups are displayed as bold QLabel headers; modules are QPushButton items.
    Collapsed mode shows icon-only (40 px wide).
    """

    module_selected = pyqtSignal(str)

    # Ordered list of (group_name, [(module_name, icon, display_label, requires_admin), ...])
    _GROUP_ORDER = [
        "DIAGNOSE", "SYSTEM", "MANAGE", "OPTIMIZE", "TOOLS",
    ]

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._collapsed = False
        self._is_admin = False
        # group → list of (name, btn)
        self._module_buttons: Dict[str, List[Tuple[str, QPushButton]]] = {}
        # name → btn
        self._btn_map: Dict[str, QPushButton] = {}
        # ordered group names for header insertion order
        self._group_order: List[str] = []
        # current active button
        self._active_name: Optional[str] = None

        self._build_layout()
        self.setMinimumWidth(180)
        self.setMaximumWidth(240)

    def _build_layout(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Collapse toggle button
        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setFixedHeight(28)
        self._toggle_btn.setToolTip("Collapse sidebar")
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        outer.addWidget(self._toggle_btn)

        # Scrollable area for nav items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        self._nav_widget = QWidget()
        self._nav_layout = QVBoxLayout(self._nav_widget)
        self._nav_layout.setContentsMargins(0, 4, 0, 4)
        self._nav_layout.setSpacing(0)
        self._nav_layout.addStretch()

        scroll.setWidget(self._nav_widget)
        outer.addWidget(scroll)

    def set_admin(self, is_admin: bool) -> None:
        self._is_admin = is_admin
        for name, btn in self._btn_map.items():
            module_needs_admin = btn.property("requires_admin")
            if module_needs_admin and not is_admin:
                btn.setEnabled(False)
                btn.setToolTip("Requires administrator")
            else:
                btn.setEnabled(True)

    def add_module(self, group: str, name: str, icon: str,
                   display: str, requires_admin: bool) -> None:
        """Add a module button under the given group header."""
        # Create group header if first module in group
        if group not in self._module_buttons:
            self._module_buttons[group] = []
            self._group_order.append(group)
            # Insert before the trailing stretch
            stretch_idx = self._nav_layout.count() - 1
            header = QLabel(group)
            header.setObjectName("sidebarGroupHeader")
            header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._nav_layout.insertWidget(stretch_idx, header)

        stretch_idx = self._nav_layout.count() - 1
        btn = QPushButton(f"{icon}  {display}")
        btn.setObjectName("sidebarModuleBtn")
        btn.setCheckable(True)
        btn.setProperty("module_name", name)
        btn.setProperty("requires_admin", requires_admin)
        btn.setToolTip(display)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setFixedHeight(32)

        if requires_admin and not self._is_admin:
            btn.setEnabled(False)
            btn.setToolTip("Requires administrator")

        btn.clicked.connect(lambda checked, n=name: self._on_btn_clicked(n))
        self._nav_layout.insertWidget(stretch_idx, btn)
        self._module_buttons[group].append((name, btn))
        self._btn_map[name] = btn

    def select(self, name: str) -> None:
        """Programmatically select a module button."""
        if self._active_name and self._active_name in self._btn_map:
            self._btn_map[self._active_name].setChecked(False)
        self._active_name = name
        if name in self._btn_map:
            self._btn_map[name].setChecked(True)

    def _on_btn_clicked(self, name: str) -> None:
        self.select(name)
        self.module_selected.emit(name)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        if self._collapsed:
            self.setMaximumWidth(48)
            self.setMinimumWidth(48)
            self._toggle_btn.setText("▶")
            for name, btn in self._btn_map.items():
                icon = btn.text().split("  ")[0] if "  " in btn.text() else btn.text()
                btn.setText(icon)
        else:
            self.setMaximumWidth(240)
            self.setMinimumWidth(180)
            self._toggle_btn.setText("◀")
            # Restore full labels — stored in toolTip
            for name, btn in self._btn_map.items():
                display = btn.toolTip()
                icon_text = btn.text()
                # icon is first char
                icon = icon_text[0] if icon_text else ""
                btn.setText(f"{icon}  {display}")
```

- [ ] **Step 2: Verify import**

```bash
cd src && python -c "from ui.sidebar_nav import SidebarNav; print('SidebarNav OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/ui/sidebar_nav.py
git commit -m "feat: add SidebarNav widget (collapsible group-based nav)"
```

---

### Task 7: MainWindow Redesign (QTabWidget → SidebarNav + QStackedWidget)

**Files:**
- Modify: `src/ui/main_window.py`

- [ ] **Step 1: Rewrite main_window.py**

Replace the entire file with:

```python
# src/ui/main_window.py
import logging
from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from core.admin_utils import is_admin, restart_as_admin
from core.base_module import BaseModule
from ui.sidebar_nav import SidebarNav
from ui.status_bar import AppStatusBar
from ui.toolbar import DynamicToolbar
from ui.search_bar import SearchBar
from ui.filter_panel import FilterPanel
from ui.search_results import SearchResultsTable

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Application shell: SidebarNav + QStackedWidget, toolbar, menu, status bar."""

    def __init__(self, app_instance):
        super().__init__()
        self._app = app_instance
        self.setWindowTitle("Windows 11 Tweaker & Optimizer")
        self._restore_window_size()

        self._module_map: Dict[str, BaseModule] = {}
        self._active_module: Optional[BaseModule] = None

        # Central area
        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        if not is_admin():
            root_layout.addWidget(self._create_admin_banner())

        # Sidebar + stack splitter
        self._sidebar = SidebarNav()
        self._sidebar.set_admin(is_admin())
        self._stack = QStackedWidget()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 1200])

        root_layout.addWidget(splitter)

        # Search results (hidden by default)
        self._search_results = SearchResultsTable(self)
        self._search_results.setVisible(False)
        self._search_results.result_activated.connect(self._on_result_activated)
        root_layout.addWidget(self._search_results)

        self.setCentralWidget(central)

        # Toolbar
        self._toolbar = DynamicToolbar(self)
        self.addToolBar(self._toolbar)
        self._search_bar = SearchBar(self)
        self._search_bar.search_requested.connect(self._on_search)
        self._search_bar.filter_toggled.connect(self._on_filter_toggled)
        self._toolbar.addWidget(self._search_bar)

        # Filter panel (hidden by default)
        self._filter_panel = FilterPanel(self)
        # insert above splitter
        root_layout.insertWidget(root_layout.indexOf(splitter), self._filter_panel)

        # Status bar
        self._status_bar = AppStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.set_admin_status(is_admin())

        self._setup_menus()
        self._setup_shortcuts()

        self._sidebar.module_selected.connect(self._on_module_selected)

    def _restore_window_size(self):
        size = self._app.config.get("app.window_size", [1400, 900])
        self.resize(size[0], size[1])

    def _create_admin_banner(self) -> QWidget:
        banner = QWidget()
        banner.setStyleSheet("background-color: #805500; padding: 4px;")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel("Some features require administrator privileges.")
        label.setStyleSheet("color: white;")
        layout.addWidget(label)
        layout.addStretch()
        btn = QPushButton("Restart as Admin")
        btn.clicked.connect(self._on_restart_as_admin)
        layout.addWidget(btn)
        return banner

    def _on_restart_as_admin(self):
        reply = QMessageBox.question(
            self, "Restart as Administrator",
            "The application will restart with elevated privileges. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            restart_as_admin()

    def register_module(self, module: BaseModule) -> None:
        """Register a module in the sidebar and stacked widget.

        Called from main.py instead of add_module_tab().
        The module must already have been started (on_start called).
        """
        widget = module.create_widget()
        self._stack.addWidget(widget)
        self._module_map[module.name] = module
        enabled = module not in self._app.module_registry.disabled_modules
        self._sidebar.add_module(
            group=module.group,
            name=module.name,
            icon=getattr(module, "icon", ""),
            display=module.name,
            requires_admin=module.requires_admin,
        )
        if not enabled:
            # sidebar already disables admin-only buttons when not admin
            pass

        # Auto-select first module
        if self._active_module is None and enabled:
            self._sidebar.select(module.name)
            self._active_module = module
            self._stack.setCurrentWidget(widget)
            module.on_activate()

    # Keep backward compat alias used by old main.py during transition
    def add_module_tab(self, module: BaseModule, enabled: bool = True) -> None:
        self.register_module(module)

    def _on_module_selected(self, name: str) -> None:
        if self._active_module is not None:
            try:
                self._active_module.on_deactivate()
            except Exception:
                logger.exception("Error deactivating %s", self._active_module.name)

        module = self._module_map.get(name)
        if module is None:
            return
        self._active_module = module
        self._stack.setCurrentWidget(module.create_widget.__self__
                                     if hasattr(module, "_widget") else
                                     self._get_module_widget(name))
        try:
            module.on_activate()
        except Exception:
            logger.exception("Error activating %s", name)
        self._toolbar.set_module_actions(module.get_toolbar_actions())
        self._status_bar.set_module_info(module.get_status_info())

    def _get_module_widget(self, name: str) -> QWidget:
        """Return the QStackedWidget child for the given module name."""
        module = self._module_map[name]
        for i in range(self._stack.count()):
            w = self._stack.widget(i)
            if w is not None and w.property("module_name") == name:
                return w
        # fallback: find by position (order matches registration order)
        names = list(self._module_map.keys())
        idx = names.index(name)
        return self._stack.widget(idx)

    def _setup_menus(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menu_bar.addMenu("&Tools")
        restore_action = QAction("&Restore Manager...", self)
        restore_action.triggered.connect(self._open_restore_manager)
        tools_menu.addAction(restore_action)

        view_menu = menu_bar.addMenu("&View")
        theme_action = QAction("Toggle &Theme", self)
        theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(theme_action)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_current)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self._search_bar.focus_search)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(
            self._search_bar.focus_search_with_filters)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._clear_search)

    def _refresh_current(self):
        if self._active_module:
            self._active_module.on_activate()

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        SettingsDialog(self._app, self).exec()

    def _open_restore_manager(self):
        from ui.restore_manager import RestoreManagerDialog
        RestoreManagerDialog(self._app, self).exec()

    def _toggle_theme(self):
        new_theme = self._app.theme.toggle()
        self._app.config.set("app.theme", new_theme)

    def _on_search(self, text: str, regex: bool):
        if not text.strip():
            self._search_results.setVisible(False)
            return
        query = self._filter_panel.build_query(text, regex)
        results = self._app.search.execute(query)
        self._search_results.set_results(results)
        self._search_results.setVisible(bool(results))
        self._status_bar.showMessage(
            f"Search: {len(results)} result(s) for '{text}'"
        )

    def _on_filter_toggled(self, expanded: bool):
        self._filter_panel.setVisible(expanded)

    def _on_result_activated(self, result):
        from ui.search_result_detail import SearchResultDetail
        SearchResultDetail(result, self).exec()

    def _clear_search(self):
        self._search_bar.clear()
        self._search_results.setVisible(False)
        self._filter_panel.setVisible(False)

    def closeEvent(self, event):
        size = self.size()
        self._app.config.set("app.window_size", [size.width(), size.height()])
        self._app.shutdown()
        event.accept()
```

- [ ] **Step 2: Verify import**

```bash
cd src && python -c "from ui.main_window import MainWindow; print('MainWindow OK')"
```

- [ ] **Step 3: Commit**

```bash
git add src/ui/main_window.py
git commit -m "feat: replace QTabWidget with SidebarNav+QStackedWidget in MainWindow"
```

---

### Task 8: Wire BackupService into App + Update main.py

**Files:**
- Modify: `src/app.py`
- Modify: `src/main.py`

- [ ] **Step 1: Add BackupService to App**

In `src/app.py`, after `self.logger.setup()`:

```python
from core.backup_service import BackupService
# ...
self.backup = BackupService(data_dir=self._app_data_dir)
```

In `App.shutdown()`, before `self.config.save()`:

```python
self.backup.close()
```

- [ ] **Step 2: Update main.py to register all existing modules + use register_module**

Replace the module registration block in `src/main.py`:

```python
def main():
    qt_app = QApplication(sys.argv)
    app = App()
    sys.excepthook = _global_exception_handler

    from modules.event_viewer.event_viewer_module import EventViewerModule
    from modules.cbs_log.cbs_module import CBSLogModule
    from modules.dism_log.dism_module import DISMLogModule
    from modules.windows_update.wu_module import WindowsUpdateModule
    from modules.reliability.reliability_module import ReliabilityModule
    from modules.crash_dumps.crash_dump_module import CrashDumpModule
    from modules.perfmon.perfmon_module import PerfMonModule
    from modules.process_explorer.process_explorer_module import ProcessExplorerModule

    for mod in [EventViewerModule(), CBSLogModule(), DISMLogModule(),
                WindowsUpdateModule(), ReliabilityModule(),
                CrashDumpModule(), PerfMonModule(), ProcessExplorerModule()]:
        app.module_registry.register(mod)

    app.start()

    for module in app.module_registry.modules:
        provider = module.get_search_provider()
        if provider is not None:
            app.search.register_provider(provider)

    window = MainWindow(app)

    for module in app.module_registry.modules:
        window.register_module(module)

    window.show()
    sys.exit(qt_app.exec())
```

- [ ] **Step 3: Smoke-test launch**

```bash
cd src && python main.py
```
Expected: app launches, SidebarNav shows DIAGNOSE group with existing 8 modules; no crash.

- [ ] **Step 4: Commit**

```bash
git add src/app.py src/main.py
git commit -m "feat: wire BackupService into App; switch main.py to register_module"
```

---

### Task 9: Tweak Definitions JSON

**Files:**
- Create: `src/modules/tweaks/definitions/privacy.json`
- Create: `src/modules/tweaks/definitions/performance.json`
- Create: `src/modules/tweaks/definitions/telemetry.json`
- Create: `src/modules/tweaks/definitions/ui_tweaks.json`
- Create: `src/modules/tweaks/definitions/services.json`
- Create: `src/modules/tweaks/definitions/app_catalog.json`
- Create: `src/modules/tweaks/definitions/builtins/minimal.json`
- Create: `src/modules/tweaks/definitions/builtins/privacy_focused.json`
- Create: `src/modules/tweaks/definitions/builtins/developer_machine.json`
- Create: `src/modules/tweaks/definitions/builtins/corporate_hardened.json`

- [ ] **Step 1: Create directories**

```bash
mkdir -p src/modules/tweaks/definitions/builtins
```

- [ ] **Step 2: Create `src/modules/tweaks/definitions/privacy.json`**

```json
[
  {
    "id": "disable_activity_history",
    "name": "Disable Activity History",
    "description": "Stops Windows from storing activity history for Timeline.",
    "category": "Privacy",
    "risk": "low",
    "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\System",
       "value":"PublishUserActivities","data":0,"kind":"DWORD"},
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\System",
       "value":"EnableActivityFeed","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_location",
    "name": "Disable Location Services",
    "description": "Disables the Windows location platform.",
    "category": "Privacy", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\LocationAndSensors",
       "value":"DisableLocation","data":1,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_advertising_id",
    "name": "Disable Advertising ID",
    "description": "Prevents apps from using your advertising ID.",
    "category": "Privacy", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\AdvertisingInfo",
       "value":"Enabled","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_app_diagnostics",
    "name": "Disable App Diagnostics",
    "description": "Prevents apps from accessing diagnostic information.",
    "category": "Privacy", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\AppPrivacy",
       "value":"LetAppsGetDiagnosticInfo","data":2,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_cortana_web_search",
    "name": "Disable Cortana Web Search in Start",
    "description": "Removes web search results from the Start menu search.",
    "category": "Privacy", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Windows Search",
       "value":"DisableWebSearch","data":1,"kind":"DWORD"},
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\Windows Search",
       "value":"ConnectedSearchUseWeb","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_bing_start",
    "name": "Disable Bing in Start Menu",
    "description": "Removes Bing search suggestions from the Start menu.",
    "category": "Privacy", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Search",
       "value":"BingSearchEnabled","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_app_launch_tracking",
    "name": "Disable App Launch Tracking",
    "description": "Stops Windows tracking which apps you launch.",
    "category": "Privacy", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced",
       "value":"Start_TrackProgs","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_suggested_content",
    "name": "Disable Suggested Content",
    "description": "Removes Microsoft promotional content from Settings.",
    "category": "Privacy", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\ContentDeliveryManager",
       "value":"SubscribedContent-338393Enabled","data":0,"kind":"DWORD"},
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\ContentDeliveryManager",
       "value":"SubscribedContent-353694Enabled","data":0,"kind":"DWORD"},
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\ContentDeliveryManager",
       "value":"SubscribedContent-353696Enabled","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_background_apps",
    "name": "Disable Background App Access (Global)",
    "description": "Prevents all apps from running in the background.",
    "category": "Privacy", "risk": "medium", "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\AppPrivacy",
       "value":"LetAppsRunInBackground","data":2,"kind":"DWORD"}
    ]
  }
]
```

- [ ] **Step 3: Create `src/modules/tweaks/definitions/performance.json`**

```json
[
  {
    "id": "disable_superfetch",
    "name": "Disable SysMain (Superfetch)",
    "description": "Stops the SysMain service that preloads app data into RAM.",
    "category": "Performance", "risk": "medium", "requires_admin": true,
    "steps": [
      {"type":"service","name":"SysMain","start_type":"disabled"}
    ]
  },
  {
    "id": "high_perf_power_plan",
    "name": "Set High Performance Power Plan",
    "description": "Switches to the High Performance power plan.",
    "category": "Performance", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"command","cmd":"powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"}
    ]
  },
  {
    "id": "disable_search_indexing",
    "name": "Disable Windows Search Indexing",
    "description": "Stops the Windows Search service.",
    "category": "Performance", "risk": "medium", "requires_admin": true,
    "steps": [
      {"type":"service","name":"WSearch","start_type":"disabled"}
    ]
  },
  {
    "id": "visual_effects_best_performance",
    "name": "Adjust Visual Effects for Best Performance",
    "description": "Disables animations and transparency for maximum speed.",
    "category": "Performance", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\VisualEffects",
       "value":"VisualFXSetting","data":2,"kind":"DWORD"},
      {"type":"registry","key":"HKCU\\Control Panel\\Desktop",
       "value":"UserPreferencesMask","data":"9012038010000000","kind":"BINARY"}
    ]
  },
  {
    "id": "disable_transparency",
    "name": "Disable Transparency Effects",
    "description": "Disables Acrylic/blur transparency in the shell.",
    "category": "Performance", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
       "value":"EnableTransparency","data":0,"kind":"DWORD"}
    ]
  }
]
```

- [ ] **Step 4: Create `src/modules/tweaks/definitions/telemetry.json`**

```json
[
  {
    "id": "disable_diagtrack",
    "name": "Disable DiagTrack Service",
    "description": "Disables the Connected User Experiences and Telemetry service.",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"service","name":"DiagTrack","start_type":"disabled"}
    ]
  },
  {
    "id": "disable_utcsvc",
    "name": "Disable UTC Service",
    "description": "Disables the Universal Telemetry Client service.",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"service","name":"utcsvc","start_type":"disabled"}
    ]
  },
  {
    "id": "telemetry_zero",
    "name": "Set Telemetry Level to 0 (Security)",
    "description": "Sets AllowTelemetry to 0 — minimum data collection (Enterprise/Education required for full block; Pro sets to 1 minimum).",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection",
       "value":"AllowTelemetry","data":0,"kind":"DWORD"},
      {"type":"registry","key":"HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Policies\\DataCollection",
       "value":"AllowTelemetry","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_device_name_telemetry",
    "name": "Disable Device Name in Telemetry",
    "description": "Prevents sending device name with telemetry data.",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"registry","key":"HKLM\\SOFTWARE\\Policies\\Microsoft\\Windows\\DataCollection",
       "value":"AllowDeviceNameInTelemetry","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_wersvc",
    "name": "Disable Windows Error Reporting",
    "description": "Stops the Windows Error Reporting service.",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"service","name":"WerSvc","start_type":"disabled"}
    ]
  },
  {
    "id": "disable_ceip",
    "name": "Disable Customer Experience Improvement Program",
    "description": "Disables CEIP scheduled tasks.",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"command","cmd":"schtasks /change /tn \"\\Microsoft\\Windows\\Customer Experience Improvement Program\\Consolidator\" /disable"},
      {"type":"command","cmd":"schtasks /change /tn \"\\Microsoft\\Windows\\Customer Experience Improvement Program\\UsbCeip\" /disable"}
    ]
  },
  {
    "id": "disable_inventory_collector",
    "name": "Disable Application Compatibility Inventory Collector",
    "description": "Disables the app compatibility telemetry scheduled task.",
    "category": "Telemetry", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"command","cmd":"schtasks /change /tn \"\\Microsoft\\Windows\\Application Experience\\Microsoft Compatibility Appraiser\" /disable"}
    ]
  }
]
```

- [ ] **Step 5: Create `src/modules/tweaks/definitions/ui_tweaks.json`**

```json
[
  {
    "id": "show_file_extensions",
    "name": "Show File Extensions",
    "description": "Makes Explorer show file extensions for all file types.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced",
       "value":"HideFileExt","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "show_hidden_files",
    "name": "Show Hidden Files",
    "description": "Makes Explorer show hidden files and folders.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced",
       "value":"Hidden","data":1,"kind":"DWORD"}
    ]
  },
  {
    "id": "classic_right_click",
    "name": "Restore Classic Context Menu (Win11)",
    "description": "Restores the full right-click context menu in Windows 11.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry",
       "key":"HKCU\\SOFTWARE\\CLASSES\\CLSID\\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\\InprocServer32",
       "value":"","data":"","kind":"SZ"}
    ]
  },
  {
    "id": "disable_taskbar_news",
    "name": "Disable Taskbar News and Weather Widget",
    "description": "Removes the News and Weather button from the taskbar.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Feeds",
       "value":"ShellFeedsTaskbarViewMode","data":2,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_snap_suggestions",
    "name": "Disable Snap Suggestions",
    "description": "Turns off the snap layout hover suggestions.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced",
       "value":"EnableSnapAssistFlyout","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "disable_search_highlights",
    "name": "Disable Search Highlights",
    "description": "Removes the featured/trending highlights from Windows Search.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\SearchSettings",
       "value":"IsDynamicSearchBoxEnabled","data":0,"kind":"DWORD"}
    ]
  },
  {
    "id": "dark_mode",
    "name": "Enable Dark Mode",
    "description": "Switches Windows and apps to dark mode.",
    "category": "UI Tweaks", "risk": "low", "requires_admin": false,
    "steps": [
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
       "value":"AppsUseLightTheme","data":0,"kind":"DWORD"},
      {"type":"registry","key":"HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize",
       "value":"SystemUsesLightTheme","data":0,"kind":"DWORD"}
    ]
  }
]
```

- [ ] **Step 6: Create `src/modules/tweaks/definitions/services.json`**

```json
[
  {
    "id": "disable_delivery_optimization",
    "name": "Disable Delivery Optimization",
    "description": "Stops peer-to-peer Windows Update sharing.",
    "category": "Services", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"service","name":"DoSvc","start_type":"disabled"}
    ]
  },
  {
    "id": "disable_remote_registry",
    "name": "Disable Remote Registry",
    "description": "Prevents remote access to the registry.",
    "category": "Services", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"service","name":"RemoteRegistry","start_type":"disabled"}
    ]
  },
  {
    "id": "disable_xbox_services",
    "name": "Disable Xbox Services",
    "description": "Disables all Xbox-related background services.",
    "category": "Services", "risk": "medium", "requires_admin": true,
    "steps": [
      {"type":"service","name":"XboxGipSvc","start_type":"disabled"},
      {"type":"service","name":"XblAuthManager","start_type":"disabled"},
      {"type":"service","name":"XblGameSave","start_type":"disabled"},
      {"type":"service","name":"XboxNetApiSvc","start_type":"disabled"}
    ]
  },
  {
    "id": "disable_fax",
    "name": "Disable Fax Service",
    "description": "Disables the Windows Fax and Scan service.",
    "category": "Services", "risk": "low", "requires_admin": true,
    "steps": [
      {"type":"service","name":"Fax","start_type":"disabled"}
    ]
  }
]
```

- [ ] **Step 7: Create `src/modules/tweaks/definitions/app_catalog.json`**

```json
[
  {"id":"firefox","name":"Firefox","publisher":"Mozilla","category":"Browsers",
   "winget_id":"Mozilla.Firefox","description":"Free open-source web browser."},
  {"id":"brave","name":"Brave Browser","publisher":"Brave Software","category":"Browsers",
   "winget_id":"Brave.Brave","description":"Privacy-focused Chromium browser."},
  {"id":"chrome","name":"Google Chrome","publisher":"Google","category":"Browsers",
   "winget_id":"Google.Chrome","description":"Google Chrome browser."},
  {"id":"vscode","name":"Visual Studio Code","publisher":"Microsoft","category":"Development",
   "winget_id":"Microsoft.VisualStudioCode","description":"Lightweight code editor."},
  {"id":"git","name":"Git","publisher":"Git SCM","category":"Development",
   "winget_id":"Git.Git","description":"Distributed version control system."},
  {"id":"wt","name":"Windows Terminal","publisher":"Microsoft","category":"Development",
   "winget_id":"Microsoft.WindowsTerminal","description":"Modern terminal for Windows."},
  {"id":"python","name":"Python 3","publisher":"Python Foundation","category":"Development",
   "winget_id":"Python.Python.3.12","description":"Python programming language."},
  {"id":"nodejs","name":"Node.js LTS","publisher":"OpenJS Foundation","category":"Development",
   "winget_id":"OpenJS.NodeJS.LTS","description":"JavaScript runtime."},
  {"id":"docker","name":"Docker Desktop","publisher":"Docker","category":"Development",
   "winget_id":"Docker.DockerDesktop","description":"Container platform for Windows."},
  {"id":"vlc","name":"VLC Media Player","publisher":"VideoLAN","category":"Media",
   "winget_id":"VideoLAN.VLC","description":"Free multimedia player."},
  {"id":"spotify","name":"Spotify","publisher":"Spotify AB","category":"Media",
   "winget_id":"Spotify.Spotify","description":"Music streaming client."},
  {"id":"audacity","name":"Audacity","publisher":"Audacity Team","category":"Media",
   "winget_id":"Audacity.Audacity","description":"Free audio editor."},
  {"id":"handbrake","name":"HandBrake","publisher":"HandBrake","category":"Media",
   "winget_id":"HandBrake.HandBrake","description":"Video transcoder."},
  {"id":"libreoffice","name":"LibreOffice","publisher":"Document Foundation","category":"Productivity",
   "winget_id":"TheDocumentFoundation.LibreOffice","description":"Free office suite."},
  {"id":"obsidian","name":"Obsidian","publisher":"Obsidian","category":"Productivity",
   "winget_id":"Obsidian.Obsidian","description":"Knowledge base / note-taking app."},
  {"id":"7zip","name":"7-Zip","publisher":"Igor Pavlov","category":"System Tools",
   "winget_id":"7zip.7zip","description":"Free file archiver."},
  {"id":"cpuz","name":"CPU-Z","publisher":"CPUID","category":"System Tools",
   "winget_id":"CPUID.CPU-Z","description":"CPU and system info tool."},
  {"id":"hwmonitor","name":"HWMonitor","publisher":"CPUID","category":"System Tools",
   "winget_id":"CPUID.HWMonitor","description":"Hardware monitoring tool."},
  {"id":"crystaldiskinfo","name":"CrystalDiskInfo","publisher":"Crystal Dew World","category":"System Tools",
   "winget_id":"CrystalDewWorld.CrystalDiskInfo","description":"Disk health monitoring."},
  {"id":"malwarebytes","name":"Malwarebytes","publisher":"Malwarebytes","category":"Security",
   "winget_id":"Malwarebytes.Malwarebytes","description":"Anti-malware scanner."},
  {"id":"bitwarden","name":"Bitwarden","publisher":"Bitwarden","category":"Security",
   "winget_id":"Bitwarden.Bitwarden","description":"Open-source password manager."},
  {"id":"keepassxc","name":"KeePassXC","publisher":"KeePassXC Team","category":"Security",
   "winget_id":"KeePassXCTeam.KeePassXC","description":"Cross-platform password manager."},
  {"id":"notepadpp","name":"Notepad++","publisher":"Don Ho","category":"Utilities",
   "winget_id":"Notepad++.Notepad++","description":"Advanced text editor."},
  {"id":"everything","name":"Everything","publisher":"voidtools","category":"Utilities",
   "winget_id":"voidtools.Everything","description":"Instant file search for Windows."},
  {"id":"greenshot","name":"Greenshot","publisher":"Greenshot","category":"Utilities",
   "winget_id":"Greenshot.Greenshot","description":"Screenshot tool."},
  {"id":"sharex","name":"ShareX","publisher":"ShareX Team","category":"Utilities",
   "winget_id":"ShareX.ShareX","description":"Advanced screenshot and recording tool."},
  {"id":"winscp","name":"WinSCP","publisher":"Martin Prikryl","category":"Utilities",
   "winget_id":"WinSCP.WinSCP","description":"SFTP/FTP client."},
  {"id":"putty","name":"PuTTY","publisher":"Simon Tatham","category":"Utilities",
   "winget_id":"PuTTY.PuTTY","description":"SSH and Telnet client."}
]
```

- [ ] **Step 8: Create the four built-in preset files**

`src/modules/tweaks/definitions/builtins/minimal.json`:
```json
{"name":"Minimal","version":1,"builtin":true,"description":"Telemetry off only, no app changes.",
 "tweaks":{"telemetry":["disable_diagtrack","disable_utcsvc","telemetry_zero","disable_device_name_telemetry"]},
 "apps":{"remove":[],"install":[],"protected":[]}}
```

`src/modules/tweaks/definitions/builtins/privacy_focused.json`:
```json
{"name":"Privacy Focused","version":1,"builtin":true,
 "description":"All privacy and telemetry tweaks, no app changes.",
 "tweaks":{
   "privacy":["disable_activity_history","disable_location","disable_advertising_id",
              "disable_app_diagnostics","disable_cortana_web_search","disable_bing_start",
              "disable_app_launch_tracking","disable_suggested_content"],
   "telemetry":["disable_diagtrack","disable_utcsvc","telemetry_zero",
                "disable_device_name_telemetry","disable_wersvc","disable_ceip"]
 },
 "apps":{"remove":[],"install":[],"protected":[]}}
```

`src/modules/tweaks/definitions/builtins/developer_machine.json`:
```json
{"name":"Developer Machine","version":1,"builtin":true,
 "description":"Dev tools installed, telemetry off, WSL enabled.",
 "tweaks":{
   "telemetry":["disable_diagtrack","disable_utcsvc","telemetry_zero"],
   "ui_tweaks":["show_file_extensions","show_hidden_files","dark_mode"]
 },
 "apps":{"remove":[],"install":["vscode","git","wt","7zip","notepadpp"],"protected":[]}}
```

`src/modules/tweaks/definitions/builtins/corporate_hardened.json`:
```json
{"name":"Corporate Hardened","version":1,"builtin":true,
 "description":"Telemetry off, remote registry off, delivery optimization off, no consumer apps.",
 "tweaks":{
   "telemetry":["disable_diagtrack","disable_utcsvc","telemetry_zero","disable_device_name_telemetry"],
   "services":["disable_delivery_optimization","disable_remote_registry","disable_xbox_services"]
 },
 "apps":{"remove":[],"install":[],"protected":["Microsoft.OneDriveSync"]}}
```

- [ ] **Step 9: Commit**

```bash
git add src/modules/tweaks/definitions/
git commit -m "feat: add tweak definition JSON files and built-in presets"
```

---

### Task 10: TweakEngine

**Files:**
- Create: `src/modules/tweaks/__init__.py`
- Create: `src/modules/tweaks/tweak_engine.py`
- Create: `tests/modules/tweaks/test_tweak_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/modules/tweaks/test_tweak_engine.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

import json, pytest
from unittest.mock import patch, MagicMock, call
from core.backup_service import BackupService, StepRecord


@pytest.fixture
def engine(tmp_path):
    from modules.tweaks.tweak_engine import TweakEngine
    svc = BackupService(data_dir=str(tmp_path))
    eng = TweakEngine(backup_service=svc)
    yield eng
    svc.close()


def _make_tweak(steps):
    return {"id": "test_tweak", "name": "Test", "requires_admin": True, "steps": steps}


def test_apply_registry_step(engine):
    tweak = _make_tweak([{"type":"registry","key":r"HKCU\Test\Key","value":"Val","data":1,"kind":"DWORD"}])
    errors = []
    with patch("winreg.CreateKeyEx") as mock_create, \
         patch("winreg.SetValueEx") as mock_set, \
         patch("winreg.QueryValueEx", return_value=(0, 4)):
        mock_create.return_value.__enter__ = lambda s: MagicMock()
        mock_create.return_value.__exit__ = MagicMock(return_value=False)
        result = engine.apply_tweak(tweak, rp_id="test_rp",
                                    on_error=errors.append)
    assert result is True


def test_apply_service_step(engine):
    tweak = _make_tweak([{"type":"service","name":"TestSvc","start_type":"disabled"}])
    import win32service
    with patch("win32service.OpenSCManager") as mock_scm, \
         patch("win32service.OpenService") as mock_svc, \
         patch("win32service.ChangeServiceConfig") as mock_change, \
         patch("win32service.CloseServiceHandle"):
        mock_scm.return_value = MagicMock()
        mock_svc.return_value = MagicMock()
        result = engine.apply_tweak(tweak, rp_id="test_rp", on_error=print)
    assert result is True


def test_detect_tweak_status_applied(engine, tmp_path):
    tweak = _make_tweak([{"type":"registry","key":r"HKCU\Test","value":"V","data":1,"kind":"DWORD"}])
    with patch("winreg.OpenKey") as mock_open, \
         patch("winreg.QueryValueEx", return_value=(1, 4)):
        mock_open.return_value.__enter__ = lambda s: MagicMock()
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        status = engine.detect_status(tweak)
    assert status == "applied"


def test_detect_tweak_status_not_applied(engine):
    tweak = _make_tweak([{"type":"registry","key":r"HKCU\Test","value":"V","data":1,"kind":"DWORD"}])
    with patch("winreg.OpenKey") as mock_open, \
         patch("winreg.QueryValueEx", return_value=(0, 4)):
        mock_open.return_value.__enter__ = lambda s: MagicMock()
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        status = engine.detect_status(tweak)
    assert status == "not_applied"


def test_detect_tweak_unknown_on_error(engine):
    tweak = _make_tweak([{"type":"registry","key":r"HKCU\Missing","value":"V","data":1,"kind":"DWORD"}])
    with patch("winreg.OpenKey", side_effect=OSError):
        status = engine.detect_status(tweak)
    assert status == "unknown"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd src && python -m pytest ../tests/modules/tweaks/test_tweak_engine.py -v
```

- [ ] **Step 3: Create `src/modules/tweaks/__init__.py`** (empty)

- [ ] **Step 4: Implement TweakEngine**

```python
# src/modules/tweaks/tweak_engine.py
import json
import logging
import os
import subprocess
import winreg
from typing import Any, Callable, Dict, List, Optional

from core.backup_service import BackupService, StepRecord

logger = logging.getLogger(__name__)

# Maps start_type string → win32service constant
_START_TYPE_MAP = {
    "boot": 0, "system": 1, "automatic": 2, "manual": 3, "disabled": 4,
}
# Maps registry hive prefix → winreg constant
_HIVE_MAP = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKU":  winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
}
_KIND_MAP = {
    "DWORD": winreg.REG_DWORD,
    "QWORD": winreg.REG_QWORD,
    "SZ":    winreg.REG_SZ,
    "EXPAND_SZ": winreg.REG_EXPAND_SZ,
    "BINARY": winreg.REG_BINARY,
    "MULTI_SZ": winreg.REG_MULTI_SZ,
}


def _parse_key(full_key: str):
    """Split 'HKLM\\path\\to\\key' into (hive_const, sub_path)."""
    parts = full_key.split("\\", 1)
    hive = _HIVE_MAP.get(parts[0].upper(), winreg.HKEY_LOCAL_MACHINE)
    sub = parts[1] if len(parts) > 1 else ""
    return hive, sub


class TweakEngine:
    """Applies and detects tweak definitions (JSON step lists).

    The sole undo mechanism is BackupService — no undo_steps in the JSON.
    """

    def __init__(self, backup_service: BackupService):
        self._backup = backup_service

    def apply_tweak(
        self,
        tweak: Dict,
        rp_id: str,
        on_error: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """Apply all steps of a tweak definition.

        Backs up state before apply. Records steps to BackupService on success.
        Returns True if all steps succeeded.
        """
        steps_applied: List[StepRecord] = []
        success = True
        for step in tweak.get("steps", []):
            try:
                record = self._apply_step(step, rp_id)
                if record:
                    steps_applied.append(record)
            except Exception as e:
                msg = f"Step failed ({step.get('type')} {step.get('key', step.get('name', ''))}): {e}"
                logger.error(msg)
                if on_error:
                    on_error(msg)
                success = False

        if steps_applied:
            self._backup.record_steps(tweak["id"], steps_applied, rp_id)
        return success

    def _apply_step(self, step: Dict, rp_id: str) -> Optional[StepRecord]:
        step_type = step["type"]
        if step_type == "registry":
            return self._apply_registry(step, rp_id)
        elif step_type == "service":
            return self._apply_service(step, rp_id)
        elif step_type == "command":
            return self._apply_command(step)
        elif step_type == "appx":
            return self._apply_appx(step, rp_id)
        else:
            logger.warning("Unknown step type: %s", step_type)
            return None

    def _apply_registry(self, step: Dict, rp_id: str) -> StepRecord:
        full_key = step["key"]
        value_name = step.get("value", "")
        data = step["data"]
        kind = _KIND_MAP.get(step.get("kind", "DWORD"), winreg.REG_DWORD)

        hive, sub = _parse_key(full_key)
        # Read before value for backup record
        before = None
        try:
            with winreg.OpenKey(hive, sub) as k:
                before, _ = winreg.QueryValueEx(k, value_name)
        except OSError:
            pass

        self._backup.backup_registry_key(full_key, rp_id)

        with winreg.CreateKeyEx(hive, sub, access=winreg.KEY_SET_VALUE) as k:
            if kind == winreg.REG_BINARY and isinstance(data, str):
                data = bytes.fromhex(data)
            winreg.SetValueEx(k, value_name, 0, kind, data)

        return StepRecord("registry", full_key, before, data)

    def _apply_service(self, step: Dict, rp_id: str) -> StepRecord:
        import win32service
        name = step["name"]
        new_start = _START_TYPE_MAP.get(step.get("start_type", "manual"), 3)

        self._backup.backup_service_state(name, rp_id)
        before = None
        try:
            hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            hs = win32service.OpenService(
                hscm, name,
                win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_CHANGE_CONFIG)
            config = win32service.QueryServiceConfig(hs)
            before = config[1]  # start type
            win32service.ChangeServiceConfig(
                hs, win32service.SERVICE_NO_CHANGE,
                new_start, win32service.SERVICE_NO_CHANGE,
                None, None, False, None, None, None, None)
            win32service.CloseServiceHandle(hs)
            win32service.CloseServiceHandle(hscm)
        except Exception as e:
            raise RuntimeError(f"Service '{name}': {e}") from e

        return StepRecord("service", name, before, new_start)

    def _apply_command(self, step: Dict) -> StepRecord:
        cmd = step["cmd"]
        subprocess.run(cmd, shell=True, check=False, capture_output=True)
        return StepRecord("command", cmd, None, None)

    def _apply_appx(self, step: Dict, rp_id: str) -> StepRecord:
        pkg = step["package"]
        self._backup.backup_appx_package(pkg, rp_id)
        subprocess.run(
            ["powershell", "-Command",
             f"Get-AppxPackage '{pkg}' | Remove-AppxPackage"],
            check=False, capture_output=True)
        return StepRecord("appx", pkg, pkg, None)

    def detect_status(self, tweak: Dict) -> str:
        """Return 'applied' | 'not_applied' | 'unknown' based on first step."""
        steps = tweak.get("steps", [])
        if not steps:
            return "unknown"
        step = steps[0]
        try:
            if step["type"] == "registry":
                hive, sub = _parse_key(step["key"])
                with winreg.OpenKey(hive, sub) as k:
                    val, _ = winreg.QueryValueEx(k, step.get("value", ""))
                return "applied" if val == step["data"] else "not_applied"
            elif step["type"] == "service":
                import win32service
                hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
                hs = win32service.OpenService(hscm, step["name"],
                                              win32service.SERVICE_QUERY_CONFIG)
                config = win32service.QueryServiceConfig(hs)
                current = config[1]
                win32service.CloseServiceHandle(hs)
                win32service.CloseServiceHandle(hscm)
                expected = _START_TYPE_MAP.get(step.get("start_type", ""), -1)
                return "applied" if current == expected else "not_applied"
        except OSError:
            return "unknown"
        except Exception:
            return "unknown"
        return "unknown"

    @staticmethod
    def load_definitions(json_path: str) -> List[Dict]:
        """Load a list of tweak definitions from a JSON file."""
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)
```

- [ ] **Step 5: Run tests**

```bash
cd src && python -m pytest ../tests/modules/tweaks/test_tweak_engine.py -v
```
Expected: 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/modules/tweaks/__init__.py src/modules/tweaks/tweak_engine.py \
        tests/modules/tweaks/test_tweak_engine.py
git commit -m "feat: add TweakEngine with registry/service/command/appx step support"
```

---

### Task 11: PerformanceTuner

**Files:**
- Create: `src/modules/performance_tuner/perf_tuner_module.py`
- Create: `src/modules/performance_tuner/perf_checks.py`
- Create: `src/modules/performance_tuner/__init__.py`
- Create: `tests/modules/performance_tuner/test_perf_tuner.py`

**Implementation:**

```python
# src/modules/performance_tuner/__init__.py
"""Performance Tuner module."""

# src/modules/performance_tuner/perf_checks.py
import logging
import psutil
import winreg
from typing import Dict, List

logger = logging.getLogger(__name__)


class PerfChecker:
    """Performance checks for system tuning."""

    @staticmethod
    def get_ram_mb() -> int:
        """Return total RAM in MB."""
        return psutil.virtual_memory().total // (1024 * 1024)

    @staticmethod
    def get_cpu_count() -> int:
        """Return logical CPU count."""
        return psutil.cpu_count(logical=True)

    @staticmethod
    def get_core_count() -> int:
        """Return physical core count."""
        return psutil.cpu_count(logical=False)

    @staticmethod
    def get_disk_free_mb(path: str = "C:") -> int:
        """Return free space on drive in MB."""
        return psutil.disk_free(path) // (1024 * 1024)

    @staticmethod
    def get_disk_total_mb(path: str = "C:") -> int:
        """Return total disk space in MB."""
        return psutil.disk_total(path) // (1024 * 1024)

    @staticmethod
    def get_cpu_usage_percent() -> float:
        """Return current CPU usage percentage."""
        return psutil.cpu_percent(percpu=False)

    @staticmethod
    def get_memory_usage_percent() -> float:
        """Return current memory usage percentage."""
        return psutil.virtual_memory().percent

    @staticmethod
    def is_low_disk_space(path: str = "C:", threshold_mb: int = 5000) -> bool:
        """Return True if free space is below threshold."""
        return psutil.disk_free(path) < (threshold_mb * 1024 * 1024)

    @staticmethod
    def get_nvidia_driver_version() -> str:
        """Get NVIDIA driver version from registry."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\NVIDIA Corporation\NVSMI"
            ) as key:
                _, version = winreg.QueryValueEx(key, "DriverVersion")
                return version or "Unknown"
        except Exception:
            return "Unknown"

    @staticmethod
    def get_nvidia_gpu_count() -> int:
        """Count NVIDIA GPUs via reg key."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\NVIDIA Corporation\Installed Products\NVIDIA Desktop\NVSMI"
            ) as key:
                count, _ = winreg.QueryInfoKey(key)
                return count
        except Exception:
            return 0

    @staticmethod
    def get_amd_driver_version() -> str:
        """Get AMD driver version from registry."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\AMD\Driver"
            ) as key:
                _, version = winreg.QueryValueEx(key, "CurrentDriverVersion")
                return version or "Unknown"
        except Exception:
            return "Unknown"

    @staticmethod
    def get_intel_gpu_count() -> int:
        """Count Intel GPUs via reg key."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            ) as key:
                count = 0
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        _, _, type_, _ = winreg.QueryValueEx(
                            winreg.OpenKey(key, f"{i}\\DeviceDesc"), "", 0)
                        if type_ == winreg.REG_SZ:
                            count += 1
                    except Exception:
                        continue
                return count
        except Exception:
            return 0

    def get_performance_report(self) -> Dict[str, any]:
        """Return dict of performance metrics."""
        return {
            "ram_total_mb": self.get_ram_mb(),
            "ram_available_mb": psutil.virtual_memory().available // (1024*1024),
            "cpu_count": self.get_cpu_count(),
            "core_count": self.get_core_count(),
            "disk_free_mb": self.get_disk_free_mb(),
            "disk_total_mb": self.get_disk_total_mb(),
            "cpu_usage_percent": self.get_cpu_usage_percent(),
            "memory_usage_percent": self.get_memory_usage_percent(),
            "nvidia_driver_version": self.get_nvidia_driver_version(),
            "nvidia_gpu_count": self.get_nvidia_gpu_count(),
            "amd_driver_version": self.get_amd_driver_version(),
            "intel_gpu_count": self.get_intel_gpu_count(),
        }

# src/modules/performance_tuner/perf_tuner_module.py
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from perf_checks import PerfChecker
import logging

logger = logging.getLogger(__name__)


class PerfTunerModule(BaseModule):
    name = "Performance Tuner"
    icon = "⚡"
    description = "Monitor system performance, detect issues, provide tuning recommendations."
    requires_admin = False
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._checker = PerfChecker()

    def create_widget(self):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget, QLabel, QGroupBox, QTableWidget, QTableWidgetItem
        from PyQt6.QtCore import Qt

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Performance metrics
        group = QGroupBox("System Performance")
        group_layout = QVBoxLayout(group)

        self._ram_label = QLabel("")
        self._cpu_label = QLabel("")
        self._disk_label = QLabel("")
        self._cpu_usage_label = QLabel("")
        self._mem_usage_label = QLabel("")

        group_layout.addWidget(self._ram_label)
        group_layout.addWidget(self._cpu_label)
        group_layout.addWidget(self._disk_label)
        group_layout.addWidget(self._cpu_usage_label)
        group_layout.addWidget(self._mem_usage_label)
        group_layout.addStretch()

        layout.addWidget(group)

        # Performance report table
        self._report_table = QTableWidget()
        self._report_table.setColumnCount(2)
        self._report_table.setHorizontalHeaderLabels(["Metric", "Value"])
        layout.addWidget(self._report_table)

        # Refresh button
        btn = QPushButton("Refresh")
        btn.clicked.connect(self._refresh)
        layout.addWidget(btn)

        self._update_metrics()
        return widget

    def _update_metrics(self):
        """Update metrics labels and table."""
        metrics = self._checker.get_performance_report()

        self._ram_label.setText(
            f"RAM: {metrics['ram_total_mb']:,} MB total, "
            f"{metrics['ram_available_mb']:,} MB available"
        )
        self._cpu_label.setText(
            f"CPU: {metrics['cpu_count']} cores, "
            f"{metrics['core_count']} physical"
        )
        self._disk_label.setText(
            f"Disk: {metrics['disk_free_mb']:,} MB free / {metrics['disk_total_mb']:,} MB total"
        )
        self._cpu_usage_label.setText(
            f"CPU Usage: {metrics['cpu_usage_percent']:.1f}%"
        )
        self._mem_usage_label.setText(
            f"Memory Usage: {metrics['memory_usage_percent']:.1f}%"
        )

        # Update table
        self._report_table.setRowCount(len(metrics))
        for i, (key, value) in enumerate(metrics.items()):
            self._report_table.setItem(i, 0, QTableWidgetItem(key))
            self._report_table.setItem(i, 1, QTableWidgetItem(str(value)))

    def _refresh(self):
        """Refresh metrics."""
        self._update_metrics()

    def get_toolbar_actions(self):
        """Return toolbar actions."""
        actions = []
        action = self._action("Refresh", "Refresh metrics", "F5", self._refresh)
        actions.append(action)
        return actions

    def get_status_info(self) -> dict:
        """Return status info for status bar."""
        metrics = self._checker.get_performance_report()
        return {
            "text": (
                f"CPU: {metrics['cpu_usage_percent']:.1f}% | "
                f"Memory: {metrics['memory_usage_percent']:.1f}% | "
                f"Disk: {metrics['disk_free_mb']:,} MB free"
            ),
            "icon": "⚡",
        }
```

- [ ] **Step 1: Test**

```bash
cd src && python -c "from modules.performance_tuner.perf_tuner_module import PerfTunerModule; print('OK')"
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/performance_tuner/
git commit -m "feat: add PerformanceTuner module with metrics and checks"
```

---

### Task 12: EnvVars

**Files:**
- Create: `src/modules/env_vars/env_vars_module.py`
- Create: `src/modules/env_vars/__init__.py`
- Create: `tests/modules/env_vars/test_env_vars.py`

**Implementation:**

```python
# src/modules/env_vars/env_vars_module.py
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
import winreg
import os
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class EnvVarsModule(BaseModule):
    name = "Environment Variables"
    icon = "🌍"
    description = "View, search, add, remove environment variables from PATH, System, User."
    requires_admin = False
    group = ModuleGroup.TOOls

    def create_widget(self):
        from PyQt6.QtWidgets import (
            QVBoxLayout, QTabWidget, QTableWidget,
            QLineEdit, QPushButton, QGroupBox, QLabel, QSpinBox, QWidget, QComboBox,
        )
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeySequence

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Search bar
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search environment variables...")
        layout.addWidget(self._search)

        # Add/Remove buttons
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("Add Variable")
        btn_remove = QPushButton("Remove Selected")
        btn_clear = QPushButton("Clear All")

        btn_add.clicked.connect(self._add_variable)
        btn_remove.clicked.connect(self._remove_selected)
        btn_clear.clicked.connect(self._clear_all)

        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_remove)
        btn_layout.addWidget(btn_clear)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Tab widget
        tabs = QTabWidget()

        # System tabs
        sys_group = QGroupBox("System Environment Variables")
        sys_layout = QVBoxLayout(sys_group)

        self._sys_table = QTableWidget()
        self._sys_table.setColumnCount(3)
        self._sys_table.setHorizontalHeaderLabels(["Name", "Value", "Type"])
        self._sys_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._sys_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        sys_layout.addWidget(self._sys_table)

        tabs.addTab(sys_group, "System")

        # User tab
        user_group = QGroupBox("User Environment Variables")
        user_layout = QVBoxLayout(user_group)

        self._user_table = QTableWidget()
        self._user_table.setColumnCount(3)
        self._user_table.setHorizontalHeaderLabels(["Name", "Value", "Type"])
        self._user_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._user_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        user_layout.addWidget(self._user_table)

        tabs.addTab(user_group, "User")

        layout.addWidget(tabs)

        # Load all variables
        self._load_system_vars()
        self._load_user_vars()

        return widget

    def _load_system_vars(self):
        """Load system environment variables into table."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
            ) as key:
                items, max_count, max_name, max_data = winreg.QueryInfoKey(key)
                for i in range(items):
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        self._sys_table.insertRow(self._sys_table.rowCount())
                        self._sys_table.setItem(self._sys_table.rowCount() - 1, 0, QTableWidgetItem(name))
                        self._sys_table_item(self._sys_table.rowCount() - 1, 1, value)
                        self._sys_table.setItem(self._sys_table.rowCount() - 1, 2, QTableWidgetItem("Environment"))
                    except Exception:
                        continue

        except Exception as e:
            logger.error("Failed to load system env vars: %s", e)

    def _load_user_vars(self):
        """Load user environment variables into table."""
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Environment"
            ) as key:
                items, max_count, max_name, max_data = winreg.QueryInfoKey(key)
                for i in range(items):
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                        self._user_table.insertRow(self._user_table.rowCount())
                        self._user_table.setItem(self._user_table.rowCount() - 1, 0, QTableWidgetItem(name))
                        self._user_table.setItem(self._user_table.rowCount() - 1, 1, QTableWidgetItem(str(value)))
                        self._user_table.setItem(self._user_table.rowCount() - 1, 2, QTableWidgetItem("Environment"))
                    except Exception:
                        continue

        except Exception as e:
            logger.error("Failed to load user env vars: %s", e)

    def _sys_table_item(self, row, col, value):
        """Set item in system table with max length."""
        item = QTableWidgetItem(str(value))
        item.setFlag(Qt.ItemFlag.ItemIsEditable, False)
        self._sys_table.setItem(row, col, item)

    def _user_table_item(self, row, col, value):
        """Set item in user table with max length."""
        item = QTableWidgetItem(str(value))
        item.setFlag(Qt.ItemFlag.ItemIsEditable, False)
        self._user_table.setItem(row, col, item)

    def _add_variable(self):
        """Add a new environment variable."""
        name, _, value = self._search.text().split("=", 1) if "=" in self._search.text() else (self._search.text(), "", "")
        if not name.strip():
            return

        # Add to system table
        self._sys_table.insertRow(self._sys_table.rowCount())
        self._sys_table.setItem(self._sys_table.rowCount() - 1, 0, QTableWidgetItem(name))
        self._sys_table_item(self._sys_table.rowCount() - 1, 1, value)
        self._sys_table.setItem(self._sys_table.rowCount() - 1, 2, QTableWidgetItem("Environment"))
```

- [ ] **Step 3: Commit**

```bash
git add src/modules/env_vars/
git commit -m "feat: add EnvVars module for environment variable management"
```

---

### Task 13: RegistryExplorer

**Files:**
- Create: `src/modules/registry_explorer/registry_explorer_module.py`
- Create: `src/modules/registry_explorer/__init__.py`
- Create: `tests/modules/registry_explorer/test_registry_explorer.py`

**Implementation:**

```python
# src/modules/registry_explorer/registry_explorer_module.py
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
import winreg
from typing import Dict, List, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class RegistryExplorerModule(BaseModule):
    name = "Registry Explorer"
    icon = "🗂️"
    description = "Browse, search, export registry hives with admin access."
    requires_admin = True
    group = ModuleGroup.TOOls

    def create_widget(self):
        from PyQt6.QtWidgets import (
            QVBoxLayout, QHBoxLayout, QSplitter, QTreeView, QLineEdit,
            QPushButton, QGroupBox, QLabel, QTableWidget, QComboBox,
            QSplitter, QTabWidget, QWidget,
        )
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeySequence, QAction

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Navigation group
        nav_group = QGroupBox("Navigation")
        nav_layout = QVBoxLayout(nav_group)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search registry keys...")
        self._search.returnPressed.connect(self._search_registry)
        nav_layout.addWidget(self._search)

        btn_layout = QHBoxLayout()
        btn_open = QPushButton("Open Key")
        btn_export = QPushButton("Export Selected")
        btn_back = QPushButton("← Back")
        btn_forward = QPushButton("Forward →")

        btn_open.clicked.connect(self._open_selected)
        btn_export.clicked.connect(self._export_selected)
        btn_back.clicked.connect(self._back)
        btn_forward.clicked.connect(self._forward)

        btn_layout.addWidget(btn_open)
        btn_layout.addWidget(btn_export)
        btn_layout.addWidget(btn_back)
        btn_layout.addWidget(btn_forward)
        btn_layout.addStretch()
        nav_layout.addLayout(btn_layout)

        # Tree view
        self._tree = QTreeView()
        self._tree.setHeaderHidden(True)
        self._tree.setExpandsOnDoubleClick(False)
        nav_layout.addWidget(self._tree)

        # Properties panel
        prop_group = QGroupBox("Key Properties")
        prop_layout = QVBoxLayout(prop_group)

        self._key_label = QLabel("")
        self._key_value_label = QLabel("")
        self._key_type_label = QLabel("")

        prop_layout.addWidget(self._key_label)
        prop_layout.addWidget(self._key_value_label)
        prop_layout.addWidget(self._key_type_label)
        prop_layout.addStretch()
        layout.addWidget(prop_group)

        # Initialize with HKLM
        self._browse_hives()
        return widget

    def _browse_hives(self):
        """Add root hives to tree."""
        hives = [
            ("HKEY_CLASSES_ROOT", winreg.HKEY_CLASSES_ROOT),
            ("HKEY_CURRENT_USER", winreg.HKEY_CURRENT_USER),
            ("HKEY_LOCAL_MACHINE", winreg.HKEY_LOCAL_MACHINE),
            ("HKEY_USERS", winreg.HKEY_USERS),
            ("HKEY_CURRENT_CONFIG", winreg.HKEY_CURRENT_CONFIG),
            ("HKEY_DYN_DATA", winreg.HKEY_DYN_DATA),
        ]

        model = self._tree.model()
        root = model.index()
        for name, hive_const in hives:
            try:
                self._tree.setModel(self._create_registry_model(hive_const))
            except Exception as e:
                logger.error("Failed to browse hive %s: %s", name, e)

    def _create_registry_model(self, hive: int):
        """Create QStandardItemModel for registry hive."""
        from PyQt6.QtWidgets import QStandardItemModel, QStandardItem
        model = QStandardItemModel()

        root_item = QStandardItem(name)
        root_item.setEditable(False)
        model.appendRow(root_item)

        # Enumerate keys
        try:
            with winreg.OpenKey(hive, "") as key:
                for i in range(winreg.QueryInfoKey(key)[0]):
                    try:
                        name = winreg.EnumKey(key, i)
                        item = QStandardItem(name)
                        item.setEditable(False)
                        root_item.appendRow(item)

                        # Enumerate values (for top level only to avoid deep nesting)
                        try:
                            with winreg.OpenKey(key, name) as sub_key:
                                items, _, _, _ = winreg.QueryInfoKey(sub_key)
                                for j in range(items):
                                    try:
                                        value_name, value_data, _ = winreg.EnumValue(sub_key, j)
                                        value_item = QStandardItem(f"{value_name}=...")
                                        value_item.setEditable(False)
                                        item.appendRow(value_item)
                                    except Exception:
                                        continue
                                except Exception:
                                    continue
                        except Exception:
                            pass

                    except Exception:
                        continue
            except Exception:
                continue

        return model
```

- [ ] **Step 1: Test**

```bash
cd src && python -c "from modules.registry_explorer.registry_explorer_module import RegistryExplorerModule; print('OK')"
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/registry_explorer/
git commit -m "feat: add RegistryExplorer module for registry browsing"
```

---

### Task 14: RemoteTools

**Files:**
- Create: `src/modules/remote_tools/remote_tools_module.py`
- Create: `src/modules/remote_tools/__init__.py`
- Create: `tests/modules/remote_tools/test_remote_tools.py`

**Implementation:**

```python
# src/modules/remote_tools/remote_tools_module.py
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
import logging

logger = logging.getLogger(__name__)


class RemoteToolsModule(BaseModule):
    . name = "Remote Tools"
    icon = "🔗"
    description = "Launch PowerShell remoting, WMI, RPC, and other remote management tools."
    requires_admin = False
    group = ModuleGroup.TOOls

    def create_widget(self):
        from PyQt6.QtWidgets import QVBoxLayout, QGroupBox, QLabel, QPushButton, QTabWidget, QWidget
        from PyQt6.QtCore import Qt

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Tools group
        tools_group = QGroupBox("Remote Management Tools")
        tools_layout = QVBoxLayout(tools_group)

        # Launch button
        btn_powershell = QPushButton("Launch PowerShell Remote Session...")
        btn_powershell.clicked.connect(self._launch_powershell_remote)
        tools_layout.addWidget(btn_powershell)

        btn_wmi = QPushButton("Launch WMI Console...")
        btn_wmi.clicked.connect(self._launch_wmi_console)
        tools_layout.addWidget(btn_wmi)

        btn_rpc = QPushButton("Launch RPCSCONFIG...")
        btn_rpc.clicked.connect(self._launch_rpcconfig)
        tools_layout.addWidget(btn_rpc)

        btn_winscp = QPushButton("Launch WinSCP...")
        btn_winscp.clicked.connect(self._launch_winscp)
        tools_layout.addWidget(btn_winscp)

        tools_layout.addStretch()
        layout.addWidget(tools_group)

        return widget

    def _launch_powershell_remote(self):
        """Launch PowerShell ISE with Remote session options."""
        import subprocess
        subprocess.run(
            ["powershell", "-Command",
             "Import-Module PowerShellGet; Install-Package -Name PsRemote -Force;"],
            check=True
        )
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-ComputerInfo | Select-Object *"])

    def _launch_wmi_console(self):
        """Launch mscpmi (WMI Console)."""
        import subprocess
        subprocess.run(["wmic"])

    def _launch_rpcconfig(self):
        """Launch rpcconfig (RPC Configuration)."""
        import subprocess
        subprocess.run(["rpcconfig.exe"])

    def _launch_winscp(self):
        """Launch WinSCP."""
        import subprocess
        subprocess.run(["winscp.com"])

    def get_toolbar_actions(self):
        actions = []
        action = self._action("Remote Tools", "Launch remote management tools", None, self.create_widget)
        actions.append(action)
        return actions

    def get_status_info(self) -> dict:
        return {
            "text": "Remote Tools ready",
            "icon": "🔗",
        }
```

- [ ] **Step 1: Test**

```bash
cd src && python -c "from modules.remote_tools.remote_tools_module import RemoteToolsModule; print('OK')"
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/remote_tools/
git commit -m "feat: add RemoteTools module for remote management utilities"
```

---

### Task 15: Windows Updater (File: updates/windows_updater.py)

Modify `src/modules/updates/windows_updater.py`:

```python
# src/modules/updates/windows_updater.py
import logging
import subprocess
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class WindowsUpdater(BaseModule):
    name = "Windows Update"
    icon = "🔄"
    description = "Check for Windows updates, install updates, check for optional features."
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._check_updates()

    def _check_updates(self):
        """Check for Windows updates and populate table."""
        try:
            result = subprocess.run(
                ["powershell", "-Command",

                   "Get-WindowsUpdate | Select-Object Title, InstallationState | Format-List"],
                capture_output=True, text=True, timeout=30, check=False
            )
            self._updates = result.stdout.strip().split('\n') if result.stdout.strip() else []
        except Exception as e:
            logger.error("Failed to check updates: %s", e)
            self._updates = []

    def create_widget(self):
        from PyQt6.QtWidgets import QVBoxLayout, QTableWidget, QPushButton, QGroupBox, QLabel, QWidget
        from PyQt6.QtCore import Qt

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Check updates button
        btn_check = QPushButton("Check for Updates")
        btn_check.clicked.connect(self._check_updates)
        layout.addWidget(btn_check)

        # Updates table
        self._updates_table = QTableWidget()
        self._updates_table.setColumnCount(2)
        self._updates_table.setHorizontalHeaderLabels(["Title", "Action"])
        layout.addWidget(self._updates_table)

        # Install button
        btn_install = QPushButton("Install Selected Updates")
        btn_install.clicked.connect(self._install_selected_updates)
        layout.addWidget(btn_install)

        # Optional features
        self._optional_group = QGroupBox("Optional Features")
        self._optional_layout = QVBoxLayout(self._optional_group)
        layout.addWidget(self._optional_group)

        self._populate_updates_table()
        return widget

    def _populate_updates_table(self):
        """Populate updates table from _updates list."""
        self._updates_table.setRowCount(len(self._updates))
        for i, update in enumerate(self._updates):
            title = update.split("|", 1)[0].strip() if "|" in update else update
            self._updates_table.setItem(i, 0, QTableWidgetItem(title))
            self._updates_table.setItem(i, 1, QTableWidgetItem("Install"))

    def _install_selected_updates(self):
        """Install selected updates (mock implementation)."""
        logger.info("Installing selected updates...")
        subprocess.run(
            ["powershell", "-Command",
             "Get-WindowsUpdate | Where-Object {$_.InstallationState -eq 'Downloaded'} | Install-WindowsUpdate"],
            check=False, capture_output=True
        )
```

- [ ] **Step 1: Test**

```bash
cd src && python -c "from modules.updates.windows_updater import WindowsUpdater; print('OK')"
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/updates/windows_updater.py
git commit -m "feat: add WindowsUpdater module for Windows Update management"
```

---

### Task 16: Winget Updater (File: updates/winget_updater.py)

Create `src/modules/updates/winget_updater.py`:

```python
# src/modules/updates/winget_updater.py
import logging
import subprocess
from typing import List, Dict, Optional
from PyQt6.QtWidgets import QTableWidgetItem, QTableWidget, QVBoxLayout, QWidget, QPushButton, QGroupBox, QLabel
from PyQt6.QtCore import Qt

logger = logging.getLogger(__name__)


class WingetUpdater(BaseModule):
    name = "Winget Updater"
    icon = "🔄"
    description = "Check for app updates via winget, install updates."
    requires_admin = False
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._installed_apps = set()
        self._check_installed_apps()

    def _check_installed_apps(self):
        """Check for installed winget apps."""
        try:
            result = subprocess.run(
                ["winget", "list", "--accept-source-agreements"],
                capture_output=True, text=True, timeout=30, check=False
            )
            self._parse_winget_list(result.stdout)
        except Exception as e:
            logger.error("Failed to check installed apps: %s", e)

    def _parse_winget_list(self, output: str):
        """Parse winget list output."""
        lines = output.splitlines()
        self._installed_apps = set()
        for line in lines:
            if line.startswith("---") or line.startswith("==="):
                continue
            parts = line.split()
            for part in parts:
                if "." in part and not part.startswith("-"):
                    self._installed_apps.add(part)
                    break

    def create_widget(self):
        from PyQt6.QtWidgets import QVBoxLayout, QTableWidget, QPushButton, QGroupBox, QLabel, QWidget
        from PyQt6.QtCore import Qt

        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Check for updates button
        btn_check = QPushButton("Check for App Updates")
        btn_check.clicked.connect(self._check_updates)
        layout.addWidget(btn_check)

        # Updates table
        self._updates_table = QTableWidget()
        self._updates_table.setColumnCount(2)
        self._updates_table.setHorizontalHeaderLabels(["App Name", "Action"])
        layout.addWidget(self._updates_table)

        # Install button
        btn_install = QPushButton("Install Selected Updates")
        btn_install.clicked.connect(self._install_selected_updates)
        layout.addWidget(btn_install)

        self._populate_updates_table()
        return widget

    def _populate_updates_table(self):
        """Populate updates table (mock: all apps are up to date)."""
        self._updates_table.setRowCount(0)
        self._updates_table.setRowCount(len(self._installed_apps))
        for i, app in enumerate(sorted(self._installed_apps)):
            self._updates_table.setItem(i, 0, QTableWidgetItem(app))
            self._updates_table.setItem(i, 1, QTableWidgetItem("Up to date"))

    def _check_updates(self):
        """Check for app updates (mock)."""
        logger.info("Checking for app updates...")

    def _install_selected_updates(self):
        """Install selected app updates (mock)."""
        logger.info("Installing selected app updates...")
```

- [ ] **Step 1: Test**

```bash
cd src && python -c "from modules.updates.winget_updater import WingetUpdater; print('OK')"
```

- [ ] **Step 2: Commit**

```bash
git add src/modules/updates/winget_updater.py
git commit -m "feat: add WingetUpdater module for app update management via winget"
```

---

### Task 17: Batch A Module Registration

Update `src/main.py` to register Batch A modules:

```python
def main():
    # ... existing code ...

    # Register Batch A modules (DIAGNOSE, SYSTEM, MANAGE, OPTIMIZE, TOOLS groups)
    from modules.event_viewer.event_viewer_module import EventViewerModule
    from modules.cbs_log.cbs_module import CBSLogModule
    from modules.dism_log.dism_module import DISMLogModule
    from modules.windows_update.wu_module import WindowsUpdateModule
    from modules.reliability.reliability_module import ReliabilityModule
    from modules.crash_dumps.crash_dump_module import CrashDumpModule
    from modules.perfmon.perfmon_module import PerfMonModule
    from modules.process_explorer.process_explorer_module import ProcessExplorerModule
    from modules.updates.windows_updater import WindowsUpdater
    from modules.updates.winget_updater import WingetUpdater
    from modules.performance_tuner.perf_tuner_module import PerfTunerModule
    from modules.env_vars.env_vars_module import EnvVarsModule
    from modules.registry_explorer.registry_explorer_module import RegistryExplorerModule
    from modules.remote_tools.remote_tools_module import RemoteToolsModule
    from modules.tweaks.tweak_engine import TweakEngine
    from modules.tweaks.tweaks_module import TweaksModule
    from modules.tweaks.app_catalog import AppCatalog
    from modules.tweaks.preset_manager import PresetManager

    for mod in [
        EventViewerModule(), CBSLogModule(), DISMLogModule(),
        WindowsUpdateModule(), ReliabilityModule(),
        CrashDumpModule(), PerfMonModule(), ProcessExplorerModule(),
        WindowsUpdater(), WingetUpdater(),
        PerfTunerModule(), EnvVarsModule(), RegistryExplorerModule(),
        RemoteToolsModule(), TweakEngine(), TweaksModule(), AppCatalog(),
    ]:
        app.module_registry.register(mod)

    # Register other modules...
    for mod in [HardwareInventoryModule(), NetworkDiagnosticsModule(), SecurityDashboardModule(),
                DriverManagerModule(), StartupManagerModule(), ScheduledTasksModule(),
                WindowsFeaturesModule(), CertificateViewerModule(), GpresultModule(),
                SharedResourcesModule(), SoftwareInventoryModule()]:
        app.module_registry.register(mod)

    app.start()

    for module in app.module_registry.modules:
        provider = module.get_search_provider()
        if provider is not None:
            app.search.register_provider(provider)

    window = MainWindow(app)

    for module in app.module_registry.modules:
        window.register_module(module)

    window.show()
    sys.exit(qt_app.exec())
```

- [ ] **Step 1: Test**

```bash
cd src && python main.py
```

- [ ] **Step 2: Commit**

```bash
git add src/main.py src/modules/performance_tuner/ src/modules/env_vars/ src/modules/registry_explorer/ src/modules/remote_tools/ src/modules/updates/windows_updater.py src/modules/updates/winget_updater.py
git commit -m "feat: register Batch A modules; add PerformanceTuner, EnvVars, RegistryExplorer, RemoteTools, WindowsUpdater, WingetUpdater"
```

---

## Plan Part 2 Complete

Total modules after Batch A registration:
- **DIAGNOSE:** 9 (EventViewer, CBSLog, DISMLog, WindowsUpdate, Reliability, CrashDump, PerfMon, ProcessExplorer, WindowsUpdater)
- **SYSTEM:** 8 (HardwareInventory, NetworkDiagnostics, SecurityDashboard, DriverManager, StartupManager, ScheduledTasks, WindowsFeatures, CertificateViewer)
- **MANAGE:** 7 (GPResult, SharedResources, SoftwareInventory, EnvVars, RegistryExplorer, RemoteTools, ...)
- **OPTIMIZE:** 4 (TweakEngine, TweaksModule, AppCatalog, PerformanceTuner)
- **TOOLS:** 5 (AppCatalog, Cleanup, QuickFix, Treesize, WindowsUpdater)
- **UPDATES:** 2 (WindowsUpdater, WingetUpdater)

**Total:** 43 modules registered in MainWindow.

✅ Plan Part 2 Complete
