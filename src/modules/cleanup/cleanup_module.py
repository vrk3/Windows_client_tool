"""
Cleanup module — 8-tab overhaul.

Tabs: Overview · System Junk · Browser Caches · App & Game Caches ·
      Windows Update · Logs & Reports · Large Items · Dev Tools

Cross-cutting: auto-scan on first tab switch, safety colour-coding,
age filter per tab, running-process guard, >500 MB confirmation,
error panel, freed-session counter, DISM button on Large Items.
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from modules.cleanup import cleanup_scanner as cs
from modules.cleanup.tabs import (
    _ScanTab,
    _BrowserCleanupTab,
    _LargeItemsTab,
    _OverviewTab,
)


# Alias LARGE_SCANNERS so the main module still has access for reference
from modules.cleanup.tabs._large_items_tab import LARGE_SCANNERS


class CleanupModule(BaseModule):
    name = "Cleanup"
    icon = "🗑️"
    description = "Scan and remove junk files, caches, logs, and more"
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def create_widget(self) -> QWidget:
        outer = QWidget()
        main_lay = QVBoxLayout(outer)
        main_lay.setContentsMargins(4, 4, 4, 4)
        main_lay.setSpacing(4)

        # ── Module-level toolbar ──
        header = QHBoxLayout()
        self._freed_lbl = QLabel("Freed this session: 0 B")
        self._freed_lbl.setStyleSheet("color: #4caf50; font-weight: bold; padding: 2px 6px;")
        self._freed_bytes = 0
        header.addStretch()
        header.addWidget(self._freed_lbl)
        main_lay.addLayout(header)

        # ── Tabs ──
        self._tabs = QTabWidget()
        main_lay.addWidget(self._tabs, 1)

        # 1. Overview
        self._overview = _OverviewTab()
        self._tabs.addTab(self._overview, "Overview")

        # 2. System Junk
        sys_scanners = {
            cs.scan_temp_files:       ("Temp Files",       "safe"),
            cs.scan_prefetch:         ("Prefetch",          "caution"),
            cs.scan_thumbnail_cache:  ("Thumbnail Cache",   "safe"),
            cs.scan_user_crash_dumps: ("User Crash Dumps",  "caution"),
        }
        self._sys_tab = _ScanTab(sys_scanners)
        self._tabs.addTab(self._sys_tab, "System Junk")

        # 3. Browser Caches
        self._browser = _BrowserCleanupTab()
        self._tabs.addTab(self._browser, "Browser Caches")

        # 4. App & Game Caches
        app_scanners = {
            cs.scan_app_caches:           ("App Caches",             "safe"),
            cs.scan_store_app_caches:     ("Store / UWP Caches",     "safe"),
            cs.scan_d3d_shader_cache:     ("GPU Shader Cache",        "safe"),
            cs.scan_appdata_autodiscover: ("Auto-discovered Caches",  "caution"),
            cs.scan_steam_cache:          ("Steam Cache",             "safe"),
            cs.scan_stremio_cache:        ("Stremio Cache",           "safe"),
            cs.scan_outlook_cache:        ("Outlook Cache",           "safe"),
            cs.scan_winget_packages:      ("WinGet Packages",         "safe"),
        }
        self._app_tab = _ScanTab(app_scanners)
        self._tabs.addTab(self._app_tab, "App & Game Caches")

        # 5. Windows Update
        wu_scanners = {
            cs.scan_wu_cache:              ("WU Download Cache",   "caution"),
            cs.scan_delivery_optimization: ("Delivery Opt. Cache", "safe"),
        }
        self._wu_tab = _ScanTab(wu_scanners, wu_cache=True)
        self._tabs.addTab(self._wu_tab, "Windows Update")

        # 6. Logs & Reports
        log_scanners = {
            cs.scan_windows_logs:     ("Windows Logs",      "caution"),
            cs.scan_event_logs:       ("Event Log Files",   "caution"),
            cs.scan_wer_reports:      ("WER Crash Reports", "caution"),
            cs.scan_memory_dumps:     ("Memory Dumps",      "caution"),
            cs.scan_panther_logs:     ("Panther Logs",       "caution"),
            cs.scan_dmf_logs:         ("DMF Logs",           "caution"),
            cs.scan_onedrive_logs:    ("OneDrive Logs",      "safe"),
            cs.scan_defender_history: ("Defender History",   "safe"),
        }
        self._logs_tab = _ScanTab(log_scanners)
        self._tabs.addTab(self._logs_tab, "Logs & Reports")

        # 7. Large Items + DISM
        self._large = _LargeItemsTab()
        self._tabs.addTab(self._large, "Large Items")

        # 8. Dev Tools
        dev_scanners = {
            cs.scan_dev_tool_caches: ("Dev Tool Caches", "safe"),
        }
        self._dev_tab = _ScanTab(dev_scanners)
        self._tabs.addTab(self._dev_tab, "Dev Tools")

        # ── Wire signals ──
        for tab in (
            self._overview, self._sys_tab, self._browser, self._app_tab,
            self._wu_tab, self._logs_tab, self._large, self._dev_tab,
        ):
            tab.freed_bytes.connect(self._on_freed)

        self._tabs.currentChanged.connect(self._on_tab_changed)

        return outer

    # ── Freed-session counter ──

    def _on_freed(self, nbytes: int):
        self._freed_bytes += nbytes
        self._freed_lbl.setText(f"Freed this session: {cs.format_size(self._freed_bytes)}")

    # ── Auto-scan on tab switch ──

    def _on_tab_changed(self, index: int):
        tab = self._tabs.widget(index)
        if hasattr(tab, "auto_scan"):
            tab.auto_scan()

    # ── BaseModule lifecycle ──

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self._cancel_all_tabs()
        self.cancel_all_workers()

    def on_activate(self) -> None:
        """Auto-scan the overview when the module is first opened."""
        self._overview.auto_scan()

    def on_deactivate(self) -> None:
        self._cancel_all_tabs()

    def _cancel_all_tabs(self) -> None:
        for tab in (
            self._overview, self._sys_tab, self._browser, self._app_tab,
            self._wu_tab, self._logs_tab, self._large, self._dev_tab,
        ):
            if hasattr(tab, "_cancel_all"):
                tab._cancel_all()

    def get_status_info(self) -> str:
        return "Cleanup"
