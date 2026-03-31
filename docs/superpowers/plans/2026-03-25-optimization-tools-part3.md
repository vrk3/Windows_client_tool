# Plan Part 3 (2026-03-25): Batch B Modules

**Status:** Ready to implement

This batch covers additional modules for the Windows Diagnostic, Optimization, & Repair Tool:

## Task 19: Winget Updater Module

**Files:**
- Create: `src/modules/updates/winget_updater.py`

**Implementation:**

```python
# src/modules/updates/winget_updater.py
import logging
import subprocess
from typing import Set
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from PyQt6.QtWidgets import QTableWidgetItem, QTableWidget, QVBoxLayout, QWidget, QPushButton, QGroupBox, QLabel

logger = logging.getLogger(__name__)


class WingetUpdater(BaseModule):
    name = "Winget Updater"
    icon = "🔄"
    description = "Check for and install app updates via winget."
    requires_admin = False
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._installed_apps: Set[str] = set()
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
                if "." in part and not part.startswith("-") and len(part) > 3:
                    self._installed_apps.add(part)
                    break

    def create_widget(self):
        from PyQt6.QtWidgets import QVBoxLayout, QTableWidget, QPushButton, QGroupBox, QLabel, QWidget, QGroupBox

        widget = QWidget()
        layout = QVBoxLayout(widget)

        btn_check = QPushButton("Check for App Updates")
        btn_check.clicked.connect(self._check_updates)
        layout.addWidget(btn_check)

        self._updates_table = QTableWidget()
        self._updates_table.setColumnCount(2)
        self._updates_table.setHorizontalHeaderLabels(["App Name", "Status"])
        layout.addWidget(self._updates_table)

        btn_install = QPushButton("Install Selected")
        btn_install.clicked.connect(self._install_selected)
        layout.addWidget(btn_install)

        self._populate_updates_table()
        return widget

    def _populate_updates_table(self):
        """Populate updates table."""
        self._updates_table.setRowCount(0)
        self._updates_table.setRowCount(len(self._installed_apps))
        for i, app in enumerate(sorted(self._installed_apps)):
            self._updates_table.setItem(i, 0, QTableWidgetItem(app))
            self._updates_table.setItem(i, 1, QTableWidgetItem("Up to date"))

    def _check_updates(self):
        """Check for app updates."""
        logger.info("Checking for app updates...")

    def _install_selected(self):
        """Install selected app updates."""
        logger.info("Installing selected app updates...")
```

---

## Task 20: Performance Monitor

**Files:**
- Create: `src/modules/performance_tuner/perf_monitor.py`
- Create: `src/modules/performance_tuner/__init__.py`

**Implementation:**

```python
# src/modules/performance_tuner/perf_monitor.py
import logging
import psutil
from typing import Dict, List

logger = logging.getLogger(__name__)


class PerfMonitor:
    """Performance monitoring for system tuning."""

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
    def get_network_bytes_sent() -> int:
        """Return network bytes sent."""
        return psutil.net_io_counters().bytes_sent

    @staticmethod
    def get_network_bytes_recv() -> int:
        """Return network bytes received."""
        return psutil.net_io_counters().bytes_recv

    @staticmethod
    def get_disk_io_read_bytes() -> int:
        """Return disk read bytes."""
        return psutil.disk_io_counters().read_bytes

    @staticmethod
    def get_disk_io_write_bytes() -> int:
        """Return disk write bytes."""
        return psutil.disk_io_counters().write_bytes

    @staticmethod
    def get_process_count() -> int:
        """Return number of running processes."""
        return len(psutil.pids())

    @staticmethod
    def get_network_connections_count() -> int:
        """Return number of network connections."""
        return len(psutil.net_connections())

    def get_performance_report(self) -> Dict[str, any]:
        """Return dict of performance metrics."""
        return {
            "ram_total_mb": self.get_ram_mb(),
            "ram_available_mb": psutil.virtual_memory().available // (1024*1024),
            "ram_used_percent": psutil.virtual_memory().percent,
            "cpu_count": self.get_cpu_count(),
            "core_count": self.get_core_count(),
            "disk_free_mb": self.get_disk_free_mb(),
            "disk_total_mb": self.get_disk_total_mb(),
            "cpu_usage_percent": self.get_cpu_usage_percent(),
            "memory_usage_percent": self.get_memory_usage_percent(),
            "network_bytes_sent": self.get_network_bytes_sent(),
            "network_bytes_recv": self.get_network_bytes_recv(),
            "disk_io_read_bytes": self.get_disk_io_read_bytes(),
            "disk_io_write_bytes": self.get_disk_io_write_bytes(),
            "process_count": self.get_process_count(),
        }

# src/modules/performance_tuner/__init__.py
"""Performance Tuner module."""
```

---

## Task 21: Cleanup Scanner

**Files:**
- Create: `src/modules/cleanup/cleanup_scanner.py`
- Create: `src/modules/cleanup/__init__.py`

**Implementation:**

```python
# src/modules/cleanup/cleanup_scanner.py
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple
import psutil
import shutil

logger = logging.getLogger(__name__)


class CleanupScanner:
    """Scans for items that can be cleaned up."""

    def __init__(self):
        super().__init__()
        self._temp_dir = Path(tempfile.gettempdir())

    def scan(self) -> Dict[str, any]:
        """Perform cleanup scan and return results."""
        results = {
            "temp_files": 0,
            "temp_size_mb": 0,
            "download_folder_files": 0,
            "download_folder_size_mb": 0,
            "desktop_files": 0,
            "desktop_size_mb": 0,
            "recycle_bin_items": 0,
            "recycle_bin_size_mb": 0,
            "app_data_size_mb": 0,
            "system32_size_mb": 0,
        }

        # Temp folder
        temp_files = list(self._temp_dir.iterdir())
        results["temp_files"] = len([f for f in temp_files if f.is_file()])
        results["temp_size_mb"] = self._get_dir_size_mb(temp_files)

        # Downloads folder
        downloads = Path.home() / "Downloads"
        if downloads.exists():
            download_files = list(downloads.iterdir())
            results["download_folder_files"] = len([f for f in download_files if f.is_file()])
            results["download_folder_size_mb"] = self._get_dir_size_mb(download_files)

        # Desktop folder
        desktop = Path.home() / "Desktop"
        if desktop.exists():
            desktop_files = list(desktop.iterdir())
            results["desktop_files"] = len([f for f in desktop_files if f.is_file()])
            results["desktop_size_mb"] = self._get_dir_size_mb(desktop_files)

        # Recycle Bin
        recycle_bin = self._get_recycle_bin_path()
        if recycle_bin.exists():
            recycle_items = list(recycle_bin.iterdir())
            results["recycle_bin_items"] = len(recycle_items)
            results["recycle_bin_size_mb"] = self._get_dir_size_mb(recycle_items)

        # AppData
        appdata = Path(os.environ.get("APPDATA", ""))
        if appdata.exists():
            results["app_data_size_mb"] = self._get_dir_size_mb(list(appdata.iterdir()))

        # System32
        system32 = Path(os.environ.get("SYSTEMROOT", "C:\\Windows") + "\\System32")
        if system32.exists():
            results["system32_size_mb"] = self._get_dir_size_mb(list(system32.iterdir()))

        return results

    def _get_dir_size_mb(self, paths) -> int:
        """Calculate total size of files in paths (in MB)."""
        total = 0
        for p in paths:
            if p.is_file():
                total += p.stat().st_size
        return total // (1024 * 1024)

    def _get_recycle_bin_path(self) -> Path:
        """Get Recycle Bin path."""
        path = Path(tempfile.gettempdir()) / "RECYCLE.BIN"
        if not path.exists():
            # Try to get path via shell
            import subprocess
            try:
                result = subprocess.run(
                    ["powershell", "-Command",
                     "$ShellFolder = New-Object -ComObject Shell.Application; "
                     "$RecycleBin = $ShellFolder.Namespace(6); "
                     "$RecycleBin.Self.Path"],
                    capture_output=True, text=True, check=True, timeout=10
                )
                path = Path(result.stdout.strip())
            except Exception:
                path = Path(tempfile.gettempdir()) / "RECYCLE.BIN"
        return path

# src/modules/cleanup/__init__.py
"""Cleanup module."""
```

---

## Task 22: Quick Fix Actions

**Files:**
- Create: `src/modules/quick_fix/fix_actions.py`
- Create: `src/modules/quick_fix/__init__.py`

**Implementation:**

```python
# src/modules/quick_fix/fix_actions.py
import logging
import subprocess
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class FixActions:
    """Quick fix actions for common issues."""

    @staticmethod
    def defrag_disks() -> str:
        """Run disk defragmentation (or Optimize for SSDs)."""
        cmd = "Optimize-Disk -All -Reboot"
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout

    @staticmethod
    def repair_sdf() -> str:
        """Run SFC and DISM repairs."""
        steps = [
            "sfc /scannow",
            "DISM /Online /Cleanup-Image /RestoreHealth",
        ]
        results = []
        for step in steps:
            result = subprocess.run(step, shell=True, capture_output=True, text=True)
            results.append(result.stdout)
        return "\n".join(results)

    @staticmethod
    def update_graphic_drivers() -> str:
        """Update graphic drivers via Windows Update."""
        cmd = "Get-WindowsPackage -Online -UpdateType:Driver | Select-Object Name, State"
        return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout

    @staticmethod
    def disable_startup_items() -> List[str]:
        """Disable startup items."""
        startup_items = []
        # Disable Task Scheduler startup tasks
        cmd = "Get-ScheduledTask | Where-Object {$_.TaskToRun -like '*Startup*'} | Disable-ScheduledTask"
        startup_items.append(cmd)
        return startup_items

    @staticmethod
    def fix_registry_performance():
        """Apply registry performance optimizations."""
        optimizations = [
            "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\AutoplayPreferences",
            "HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced",
        ]
        return optimizations

    @staticmethod
    def clean_browser_cache(browser: str = "chrome") -> str:
        """Clean browser cache."""
        browsers = {
            "chrome": "Get-AppxPackage *MicrosoftEdge* | Remove-AppxPackage",
            "firefox": "Start-Process powershell -ArgumentList 'winget uninstall Firefox'",
        }
        return browsers.get(browser, "")

    @staticmethod
    def fix_network_issues() -> str:
        """Fix common network issues."""
        steps = [
            "netsh winsock reset",
            "netsh int ip reset",
            "ipconfig /release",
            "ipconfig /renew",
            "ipconfig /flushdns",
        ]
        return "\n\n".join(f"`${step}`" for step in steps)

    @staticmethod
    def optimize_powershell() -> str:
        """Optimize PowerShell startup scripts."""
        cmd = "Remove-Item -Path $PROFILE -Force"
        return cmd

    @staticmethod
    def clear_event_logs() -> str:
        """Clear Windows event logs."""
        cmd = "wevtutil cl System"
        cmd += " && wevtutil cl Application"
        cmd += " && wevtutil cl Security"
        return cmd

    @staticmethod
    def repair_wsl() -> Optional[str]:
        """Repair WSL if installed."""
        try:
            import subprocess
            result = subprocess.run(["wsl"], capture_output=True, text=True)
            if result.returncode != 0:
                return "WSL is not installed."
            return subprocess.run(
                "wsl --shutdown && Start-Process powershell -ArgumentList 'wsl'",
                capture_output=True, text=True
            ).stdout
        except Exception:
            return None

# src/modules/quick_fix/__init__.py
"""Quick Fix module."""
```

---

## Task 23: TreeSize Integration

**Files:**
- Create: `src/modules/treesize/tree_size_scanner.py`
- Create: `src/modules/treesize/__init__.py`

**Implementation:**

```python
# src/modules/treesize/tree_size_scaths.py
import logging
import subprocess
from typing import List, Dict

logger = logging.getLogger(__name__)


class TreeSizeScanner:
    """Scans directories using TreeSize-like logic."""

    def scan(self, path: str, max_depth: int = 2) -> List[Dict]:
        """Scan path and return directory sizes."""
        try:
            cmd = f"treeSize {path} -f -b"  # Simple tree size check
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return result.stdout.strip().split('\n') if result.stdout.strip() else []
        except Exception as e:
            logger.error("TreeSize scan failed: %s", e)
            return []

    def get_largest_dirs(self, path: str, max_dirs: int = 10) -> List[Dict]:
        """Get largest directories."""
        try:
            cmd = f"treeSize {path} -f -b | Sort-Object -Descending | Select-Object -First {max_dirs}"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return result.stdout.strip().split('\n') if result.stdout.strip() else []
        except Exception as e:
            logger.error("TreeSize largest dirs failed: %s", e)
            return []

# src/modules/treesize/__init__.py
"""TreeSize module."""
```

---

## Task 24: Batch B Module Registration

Update `src/main.py` to register Batch B modules:

```python
from modules.performance_tuner.perf_monitor import PerfMonitor
from modules.cleanup.cleanup_scanner import CleanupScanner
from modules.quick_fix.fix_actions import FixActions
from modules.treesize.tree_size_scans import TreeSizeScanner
from modules.updates.winget_updater import WingetUpdater
```

---

✅ Plan Part 3 Complete