"""
Security Dashboard — interactive security posture monitoring and control.

Provides real-time status of Windows security features with the ability
to toggle Defender settings, firewall profiles, SmartScreen, and more.
Each toggle stores its previous state for per-setting revert.
"""

import re
from datetime import datetime
from functools import partial
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QProgressBar,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QGroupBox, QScrollArea, QSizePolicy, QStackedWidget,
)
from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QFont

try:
    import sip as _sip
    _widget_valid = lambda w: w is not None and not _sip.isdeleted(w)
except ImportError:
    _widget_valid = lambda w: w is not None

import logging
logger = logging.getLogger(__name__)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult
from core.worker import Worker, COMWorker
from ui.error_banner import ErrorBanner
from modules.security_dashboard.security_reader import (
    get_all_security_status,
    get_extended_status,
    get_security_events,
    run_quick_scan,
    run_update_definitions,
    check_defender_signatures,
    set_defender_realtime,
    set_defender_cloud,
    set_defender_sample_submission,
    set_pua_protection,
    set_controlled_folder_access,
    set_tamper_protection,
    set_network_protection_defender,
    set_firewall_profile,
    set_smartscreen,
    set_lsass_protection,
    set_uac_level,
    set_defender_behavior_monitoring,
    set_defender_script_scanning,
    set_defender_archive_scanning,
    set_defender_ioav,
    set_defender_removable_drive_scanning,
    set_defender_catchup_scans,
    set_llmnr,
    set_wpad,
    set_wdigest_credential_caching,
    set_ntlm_level,
    set_pagefile_clear,
    set_ps_script_block_logging,
    # CVE checks (for CVEs tab)
    check_spectre_v2, check_meltdown, check_ssbd, check_l1tf, check_mds,
    check_printnightmare, check_zerologon, check_petitpotam, check_follina,
    check_blacklotus, check_kerberos_armoring, check_credential_guard_vbs,
    check_ntlm_relay_protection, check_smb_ghost,
)

COLOR_MAP = {
    "green": "#27AE60",
    "amber": "#E67E22",
    "red":   "#E74C3C",
}

# ── Reusable Toggle Card ───────────────────────────────────────────────────

class _ToggleCard(QFrame):
    """Interactive security card with toggle switch, revert, and status.

    Lifecycle:
      1. Card created with title/icon/description
      2. set_state(enabled, status_text, color) — render current state
      3. User clicks Toggle → _on_toggle() → card calls self._toggle_fn(enabled)
      4. While toggling: show_action("Applying...")
      5. On result: show_result(success, message) — shows Revert if changed
      6. User clicks Revert → _on_revert() → card calls self._revert_fn()
    """

    action_requested = pyqtSignal(str, object)  # signal: (action_id, payload)

    def __init__(self, title: str, icon: str, description: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(100)

        self._title = title
        self._icon = icon
        self._toggle_fn: Optional[Callable] = None
        self._revert_fn: Optional[Callable] = None
        self._action_id: str = ""
        self._original_state: Optional[bool] = None
        self._changed = False
        self._current_enabled: Optional[bool] = None
        self._worker = None

        self._build_ui(description)

    def _build_ui(self, description: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)

        # Top row: icon + title + status badge
        top = QHBoxLayout()
        self._title_lbl = QLabel(f"{self._icon}  {self._title}")
        f = self._title_lbl.font()
        f.setBold(True)
        pt = f.pointSize()
        if pt > 0:
            f.setPointSize(pt + 1)
        self._title_lbl.setFont(f)
        top.addWidget(self._title_lbl, 1)

        self._status_badge = QLabel("---")
        self._status_badge.setStyleSheet(
            "font-size: 12px; font-weight: bold; padding: 2px 8px; "
            "border-radius: 3px; background: #3c3c3c;"
        )
        top.addWidget(self._status_badge)
        root.addLayout(top)

        # Description
        if description:
            desc = QLabel(description)
            desc.setStyleSheet("color: #999; font-size: 11px;")
            desc.setWordWrap(True)
            root.addWidget(desc)

        # Bottom row: toggle + revert + action status
        bottom = QHBoxLayout()

        self._toggle_btn = QPushButton("Enable")
        self._toggle_btn.setFixedWidth(80)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                background: #27AE60; color: white; border: none;
                padding: 4px 12px; border-radius: 3px; font-weight: bold;
            }
            QPushButton:hover { background: #2ECC71; }
            QPushButton:disabled { background: #555; color: #888; }
        """)
        self._toggle_btn.clicked.connect(self._on_toggle)
        bottom.addWidget(self._toggle_btn)

        self._revert_btn = QPushButton("Revert")
        self._revert_btn.setFixedWidth(70)
        self._revert_btn.setStyleSheet("""
            QPushButton {
                background: #E67E22; color: white; border: none;
                padding: 4px 8px; border-radius: 3px;
            }
            QPushButton:hover { background: #F39C12; }
            QPushButton:disabled { background: #555; color: #888; }
        """)
        self._revert_btn.clicked.connect(self._on_revert)
        self._revert_btn.hide()
        bottom.addWidget(self._revert_btn)

        self._action_lbl = QLabel()
        self._action_lbl.setStyleSheet("color: #999; font-size: 11px;")
        bottom.addWidget(self._action_lbl, 1)

        root.addLayout(bottom)

    # ── Public API ────────────────────────────────────────────────────────

    def configure(self, action_id: str,
                  toggle_fn: Callable[[bool], Any],
                  revert_fn: Optional[Callable] = None):
        """Wire up the toggle/revert callbacks."""
        self._action_id = action_id
        self._toggle_fn = toggle_fn
        self._revert_fn = revert_fn or toggle_fn

    def set_state(self, enabled: Optional[bool], status_text: str, color: str):
        """Render the current security state."""
        self._current_enabled = enabled
        self._changed = False
        self._revert_btn.hide()

        hex_color = COLOR_MAP.get(color, "#888")
        self._status_badge.setText(status_text)
        self._status_badge.setStyleSheet(
            f"font-size: 12px; font-weight: bold; padding: 2px 8px; "
            f"border-radius: 3px; background: {hex_color}; color: white;"
        )
        self.setStyleSheet(f"QFrame#toggle_card {{ border-left: 4px solid {hex_color}; }}")
        self.setObjectName("toggle_card")

        if enabled is None:
            self._toggle_btn.setText("N/A")
            self._toggle_btn.setEnabled(False)
            self._toggle_btn.setStyleSheet("""
                QPushButton { background: #555; color: #888; border: none;
                padding: 4px 12px; border-radius: 3px; }
            """)
        elif enabled:
            self._toggle_btn.setText("Disable")
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setStyleSheet("""
                QPushButton { background: #E74C3C; color: white; border: none;
                padding: 4px 12px; border-radius: 3px; font-weight: bold; }
                QPushButton:hover { background: #C0392B; }
                QPushButton:disabled { background: #555; color: #888; }
            """)
        else:
            self._toggle_btn.setText("Enable")
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setStyleSheet("""
                QPushButton { background: #27AE60; color: white; border: none;
                padding: 4px 12px; border-radius: 3px; font-weight: bold; }
                QPushButton:hover { background: #2ECC71; }
                QPushButton:disabled { background: #555; color: #888; }
            """)

    def set_loading(self):
        """Show loading/unknown state."""
        self._toggle_btn.setText("...")
        self._toggle_btn.setEnabled(False)
        self._toggle_btn.setStyleSheet("""
            QPushButton { background: #555; color: #888; border: none;
            padding: 4px 12px; border-radius: 3px; }
        """)
        self._status_badge.setText("Loading...")
        self._status_badge.setStyleSheet(
            "font-size: 12px; font-weight: bold; padding: 2px 8px; "
            "border-radius: 3px; background: #3c3c3c; color: #888;"
        )

    def show_action(self, message: str):
        """Show a transient action status (applying, reverting, etc.)."""
        self._action_lbl.setText(message)
        self._action_lbl.setStyleSheet("color: #E67E22; font-size: 11px;")
        self._toggle_btn.setEnabled(False)
        self._revert_btn.setEnabled(False)

    def show_result(self, success: bool, message: str, after_state: Optional[bool] = None):
        """Show the result of a toggle/revert action."""
        if success:
            self._changed = not self._changed
            color = "#27AE60"
            if self._changed:
                self._revert_btn.show()
                self._revert_btn.setEnabled(True)
                self._action_lbl.setText(f"Changed. {message}")
            else:
                self._revert_btn.hide()
                self._action_lbl.setText(f"Reverted. {message}")
            if after_state is not None:
                self._current_enabled = after_state
                self._refresh_button(after_state)
        else:
            color = "#E74C3C"
            self._action_lbl.setText(f"Error: {message}")
            self._toggle_btn.setEnabled(True)
            self._revert_btn.setEnabled(True if self._changed else False)
        self._action_lbl.setStyleSheet(f"color: {color}; font-size: 11px;")

    def _on_toggle(self):
        """User clicked Enable/Disable."""
        if not self._toggle_fn:
            return
        if self._worker is not None:
            return  # already toggling
        new_state = not self._current_enabled
        self.show_action("Applying...")

        def do_toggle(worker):
            return self._toggle_fn(new_state)

        self._worker = Worker(do_toggle)
        self._worker.signals.result.connect(
            partial(self._on_toggle_result, new_state=new_state))
        self._worker.signals.error.connect(
            partial(self._on_toggle_error, new_state=new_state))

        QThreadPool.globalInstance().start(self._worker)

    def _on_toggle_result(self, result: dict, new_state: bool):
        if not _widget_valid(self):
            return
        success = isinstance(result, dict) and result.get("success", False)
        msg = result.get("message", "") if isinstance(result, dict) else str(result)
        self.show_result(success, msg, new_state if success else None)
        self._worker = None

    def _on_toggle_error(self, err, new_state: bool):
        if not _widget_valid(self):
            return
        err_msg = str(err[1]) if isinstance(err, tuple) else str(err)
        self.show_result(False, err_msg)
        self._toggle_btn.setEnabled(True)
        self._worker = None

    def _on_revert(self):
        """User clicked Revert."""
        if not self._revert_fn:
            return
        if self._worker is not None:
            return  # already active
        original = not self._current_enabled
        self.show_action("Reverting...")

        def do_revert(worker):
            return self._revert_fn(original)

        self._worker = Worker(do_revert)
        self._worker.signals.result.connect(
            partial(self._on_revert_result, revert_to=original))
        self._worker.signals.error.connect(
            partial(self._on_toggle_error, new_state=False))

        QThreadPool.globalInstance().start(self._worker)

    def _on_revert_result(self, result: dict, revert_to: bool):
        if not _widget_valid(self):
            return
        success = isinstance(result, dict) and result.get("success", False)
        msg = result.get("message", "") if isinstance(result, dict) else str(result)
        self.show_result(success, msg, revert_to if success else None)
        self._worker = None

    def _refresh_button(self, enabled: bool):
        """Refresh the toggle button appearance without triggering action."""
        if enabled:
            self._toggle_btn.setText("Disable")
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setStyleSheet("""
                QPushButton { background: #E74C3C; color: white; border: none;
                padding: 4px 12px; border-radius: 3px; font-weight: bold; }
                QPushButton:hover { background: #C0392B; }
                QPushButton:disabled { background: #555; color: #888; }
            """)
        else:
            self._toggle_btn.setText("Enable")
            self._toggle_btn.setEnabled(True)
            self._toggle_btn.setStyleSheet("""
                QPushButton { background: #27AE60; color: white; border: none;
                padding: 4px 12px; border-radius: 3px; font-weight: bold; }
                QPushButton:hover { background: #2ECC71; }
                QPushButton:disabled { background: #555; color: #888; }
            """)

    def cancel(self):
        if self._worker:
            self._worker.cancel()
            self._worker = None


# ── Read-Only Status Card ──────────────────────────────────────────────────

class _StatusCard(QFrame):
    """Read-only coloured status card with title, status badge, and detail rows."""

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)

        self._title_lbl = QLabel(title)
        font = self._title_lbl.font()
        font.setBold(True)
        pt = font.pointSize()
        if pt > 0:
            font.setPointSize(pt + 1)
        self._title_lbl.setFont(font)
        layout.addWidget(self._title_lbl)

        self._status_lbl = QLabel("Loading...")
        self._status_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self._status_lbl)

        self._details_layout = QVBoxLayout()
        layout.addLayout(self._details_layout)
        layout.addStretch()

    def update_status(self, data: dict):
        color = COLOR_MAP.get(data.get("color", "amber"), "#888")
        status = data.get("status", "Unknown")
        self._status_lbl.setText(status)
        self._status_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {color};")
        self.setStyleSheet(f"QFrame {{ border-left: 4px solid {color}; }}")

        # Clear and rebuild detail rows
        while self._details_layout.count():
            item = self._details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for k, v in data.get("details", []):
            row = QHBoxLayout()
            k_lbl = QLabel(f"{k}:")
            k_lbl.setStyleSheet("color: gray;")
            v_lbl = QLabel(str(v))
            row.addWidget(k_lbl)
            row.addStretch()
            row.addWidget(v_lbl)
            container = QWidget()
            container.setLayout(row)
            self._details_layout.addWidget(container)


# ── Main Module ────────────────────────────────────────────────────────────

class SecurityDashboardModule(BaseModule):
    name = "Security Dashboard"
    icon = "\U0001f6e1\ufe0f"
    description = "Windows security status overview with controls"
    requires_admin = True
    group = ModuleGroup.SYSTEM

    def __init__(self):
        super().__init__()
        self._workers: list = []
        self._loaded_overview = False
        self._loaded_controls = False
        self._loaded_advanced = False
        self._loaded_cves = False
        self._loaded_events = False
        self._toggle_cards: List[_ToggleCard] = []
        self._events_progress: Optional[QProgressBar] = None
        self._events_table: Optional[QTableWidget] = None

    def get_refresh_interval(self) -> Optional[int]:
        return 30_000

    def get_search_provider(self) -> Optional[SearchProvider]:
        return SecuritySearchProvider()

    def refresh_data(self) -> None:
        self._refresh_overview()
        if self._loaded_controls:
            self._refresh_controls()

    def on_start(self, app) -> None:
        self.app = app

    # ── Widget Creation ───────────────────────────────────────────────────

    def create_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Error banner
        self._error_banner = ErrorBanner()
        self._error_banner.hide()
        layout.addWidget(self._error_banner)

        # Header
        header_row = QHBoxLayout()
        self._banner = QLabel("Security Status")
        font = self._banner.font()
        font.setBold(True)
        pt = font.pointSize()
        if pt > 0:
            font.setPointSize(pt + 2)
        self._banner.setFont(font)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._manual_refresh)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        header_row.addWidget(self._banner, 1)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)
        layout.addWidget(self._progress)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_overview_tab(), "Overview")
        self._tabs.addTab(self._build_controls_tab(), "Controls")
        self._tabs.addTab(self._build_advanced_tab(), "Advanced")
        self._tabs.addTab(self._build_cve_tab(), "CVEs")
        self._tabs.addTab(self._build_events_tab(), "Security Events")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

        return w

    # ── Tab 1: Overview ───────────────────────────────────────────────────

    def _build_overview_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        # Core security grid (2x2)
        core_label = QLabel("Core Security")
        core_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0b0;")
        layout.addWidget(core_label)

        grid = QGridLayout()
        grid.setSpacing(12)
        self._defender_card = _StatusCard("\U0001f6e1 Windows Defender")
        self._firewall_card = _StatusCard("\U0001f525 Firewall")
        self._bitlocker_card = _StatusCard("\U0001f4be BitLocker")
        self._boot_card = _StatusCard("\U0001f510 Secure Boot & TPM")
        grid.addWidget(self._defender_card, 0, 0)
        grid.addWidget(self._firewall_card, 0, 1)
        grid.addWidget(self._bitlocker_card, 1, 0)
        grid.addWidget(self._boot_card, 1, 1)
        layout.addLayout(grid)

        # Additional checks grid
        adv_label = QLabel("Additional Protections")
        adv_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0b0;")
        layout.addWidget(adv_label)

        grid2 = QGridLayout()
        grid2.setSpacing(12)
        self._uac_card = _StatusCard("\U0001f6e1 UAC")
        self._smartscreen_card = _StatusCard("\U0001f4e7 SmartScreen")
        self._hvci_card = _StatusCard("\U0001f512 HVCI / Memory Integrity")
        self._credguard_card = _StatusCard("\U0001f6f0 Credential Guard")
        self._lsass_card = _StatusCard("\U0001f512 LSASS Protection")
        self._rdp_card = _StatusCard("\U0001f310 Remote Desktop")
        self._smbv1_card = _StatusCard("\U0001f5c4 SMBv1")
        self._tamper_card = _StatusCard("\U0001f512 Tamper Protection")
        self._applocker_card = _StatusCard("\U0001f4dc AppLocker / WDAC")
        self._winhello_card = _StatusCard("\U0001f440 Windows Hello")
        grid2.addWidget(self._uac_card, 0, 0)
        grid2.addWidget(self._smartscreen_card, 0, 1)
        grid2.addWidget(self._hvci_card, 1, 0)
        grid2.addWidget(self._credguard_card, 1, 1)
        grid2.addWidget(self._lsass_card, 2, 0)
        grid2.addWidget(self._rdp_card, 2, 1)
        grid2.addWidget(self._applocker_card, 3, 0)
        grid2.addWidget(self._winhello_card, 3, 1)
        grid2.addWidget(self._smbv1_card, 4, 0)
        grid2.addWidget(self._tamper_card, 4, 1)
        layout.addLayout(grid2)

        layout.addStretch()
        scroll.setWidget(tab)
        return scroll

    def _refresh_overview(self):
        """Load overview data in background."""
        self._progress.show()

        worker = COMWorker(lambda _w: get_extended_status())
        self._workers.append(worker)

        def on_result(data: dict):
            if not _widget_valid(self._banner):
                return
            self._progress.hide()

            # Core cards
            self._defender_card.update_status(data["defender"])
            self._firewall_card.update_status(data["firewall"])
            self._bitlocker_card.update_status(data["bitlocker"])
            self._boot_card.update_status(data["secure_boot_tpm"])

            # Additional cards
            self._uac_card.update_status(data["uac"])
            self._smartscreen_card.update_status(data["smartscreen"])
            self._hvci_card.update_status(data["hvci"])
            self._credguard_card.update_status(data["credential_guard"])
            self._lsass_card.update_status(data["lsass_protection"])
            self._tamper_card.update_status(data["tamper_protection"])
            self._rdp_card.update_status(data["rdp"])
            self._smbv1_card.update_status(data["smbv1"])
            self._applocker_card.update_status(data.get("applocker", {}))
            self._winhello_card.update_status(data.get("windows_hello", {}))

            # Overall banner
            all_data = [data["defender"], data["firewall"],
                        data["bitlocker"], data["secure_boot_tpm"]]
            colors = [d.get("color", "amber") for d in all_data]
            if all(c == "green" for c in colors):
                overall, col = "Secure", "#27AE60"
            elif any(c == "red" for c in colors):
                overall, col = "Issues Detected", "#E74C3C"
            else:
                overall, col = "Warnings", "#E67E22"
            self._banner.setText(f"Security Status — {overall}")
            self._banner.setStyleSheet(f"font-weight: bold; color: {col};")

        def on_error(err):
            if not _widget_valid(self._banner):
                return
            self._progress.hide()
            emsg = str(err[1]) if isinstance(err, tuple) else str(err)
            self._error_banner.set_error(f"Failed to load security status: {emsg}")
            self._error_banner.show()
            self._banner.setText("Security Status — Error")

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

        QThreadPool.globalInstance().start(worker)

    # ── Tab 2: Controls ───────────────────────────────────────────────────

    def _build_controls_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Defender group ────────────────────────────────────────────────
        def_group = QGroupBox("Windows Defender Settings")
        def_layout = QVBoxLayout(def_group)

        self._ctrl_realtime = _ToggleCard(
            "Real-Time Protection", "\U0001f6e1",
            "Scans files and programs as they are accessed or run.")
        self._ctrl_realtime.configure(
            "defender_realtime", set_defender_realtime, set_defender_realtime)
        def_layout.addWidget(self._ctrl_realtime)

        self._ctrl_cloud = _ToggleCard(
            "Cloud-Delivered Protection", "\u2601",
            "Uses Microsoft cloud intelligence to provide faster threat detection.")
        self._ctrl_cloud.configure(
            "defender_cloud", lambda e: set_defender_cloud(e, 2),
            lambda e: set_defender_cloud(e, 2))
        def_layout.addWidget(self._ctrl_cloud)

        self._ctrl_sample = _ToggleCard(
            "Automatic Sample Submission", "\U0001f4e4",
            "Sends suspicious files automatically to Microsoft for analysis.")
        self._ctrl_sample.configure(
            "defender_samples", set_defender_sample_submission,
            set_defender_sample_submission)
        def_layout.addWidget(self._ctrl_sample)

        self._ctrl_pua = _ToggleCard(
            "PUA Protection", "\U0001f6ab",
            "Blocks Potentially Unwanted Applications (adware, bundleware, miners).")
        self._ctrl_pua.configure(
            "defender_pua", set_pua_protection, set_pua_protection)
        def_layout.addWidget(self._ctrl_pua)

        self._ctrl_cfa = _ToggleCard(
            "Controlled Folder Access", "\U0001f4c1",
            "Anti-ransomware: only trusted apps can modify protected folders.")
        self._ctrl_cfa.configure(
            "defender_cfa", set_controlled_folder_access,
            set_controlled_folder_access)
        def_layout.addWidget(self._ctrl_cfa)

        self._ctrl_tamper = _ToggleCard(
            "Tamper Protection", "\U0001f512",
            "Prevents malware from changing Defender security settings.")
        self._ctrl_tamper.configure(
            "defender_tamper", set_tamper_protection, set_tamper_protection)
        def_layout.addWidget(self._ctrl_tamper)

        self._ctrl_netprot = _ToggleCard(
            "Network Protection", "\U0001f310",
            "Blocks outbound connections to known malicious IPs and domains.")
        self._ctrl_netprot.configure(
            "defender_netprot", set_network_protection_defender,
            set_network_protection_defender)
        def_layout.addWidget(self._ctrl_netprot)

        layout.addWidget(def_group)

        # ── Firewall group ────────────────────────────────────────────────
        fw_group = QGroupBox("Windows Firewall Profiles")
        fw_layout = QVBoxLayout(fw_group)

        self._ctrl_fw_domain = _ToggleCard(
            "Domain Profile", "\U0001f310",
            "Firewall rules when connected to a corporate domain network.")
        self._ctrl_fw_domain.configure(
            "firewall_domain",
            lambda e: set_firewall_profile("Domain", e),
            lambda e: set_firewall_profile("Domain", e))
        fw_layout.addWidget(self._ctrl_fw_domain)

        self._ctrl_fw_private = _ToggleCard(
            "Private Profile", "\U0001f3e0",
            "Firewall rules for home or work private networks.")
        self._ctrl_fw_private.configure(
            "firewall_private",
            lambda e: set_firewall_profile("Private", e),
            lambda e: set_firewall_profile("Private", e))
        fw_layout.addWidget(self._ctrl_fw_private)

        self._ctrl_fw_public = _ToggleCard(
            "Public Profile", "\U0001f30d",
            "Firewall rules for public networks (airports, cafes).")
        self._ctrl_fw_public.configure(
            "firewall_public",
            lambda e: set_firewall_profile("Public", e),
            lambda e: set_firewall_profile("Public", e))
        fw_layout.addWidget(self._ctrl_fw_public)

        layout.addWidget(fw_group)

        # ── System group ──────────────────────────────────────────────────
        sys_group = QGroupBox("System Security")
        sys_layout = QVBoxLayout(sys_group)

        self._ctrl_smartscreen = _ToggleCard(
            "SmartScreen", "\U0001f4e7",
            "Checks downloaded files and apps against Microsoft reputation database.")
        self._ctrl_smartscreen.configure(
            "smartscreen", set_smartscreen, set_smartscreen)
        sys_layout.addWidget(self._ctrl_smartscreen)

        self._ctrl_lsass = _ToggleCard(
            "LSASS Protection (RunAsPPL)", "\U0001f6e1",
            "Runs LSASS as a protected process to prevent credential dumping. "
            "REBOOT REQUIRED after toggle.")
        self._ctrl_lsass.configure(
            "lsass_ppl", set_lsass_protection, set_lsass_protection)
        sys_layout.addWidget(self._ctrl_lsass)

        layout.addWidget(sys_group)

        # Quick actions
        actions_group = QGroupBox("Quick Actions")
        actions_layout = QHBoxLayout(actions_group)
        scan_btn = QPushButton("Quick Scan")
        scan_btn.setToolTip("Run Windows Defender Quick Scan")
        scan_btn.clicked.connect(self._do_quick_scan)
        update_btn = QPushButton("Update Definitions")
        update_btn.setToolTip("Update Defender signature definitions")
        update_btn.clicked.connect(self._do_update_defs)
        self._action_status_lbl = QLabel()
        self._action_status_lbl.setStyleSheet("color: gray; font-size: 12px;")
        actions_layout.addWidget(scan_btn)
        actions_layout.addWidget(update_btn)
        actions_layout.addWidget(self._action_status_lbl)
        actions_layout.addStretch()
        layout.addWidget(actions_group)

        layout.addStretch()
        scroll.setWidget(tab)

        # Collect toggle cards for lifecycle management
        self._toggle_cards = [
            self._ctrl_realtime, self._ctrl_cloud, self._ctrl_sample,
            self._ctrl_pua, self._ctrl_cfa, self._ctrl_tamper,
            self._ctrl_netprot,
            self._ctrl_fw_domain, self._ctrl_fw_private, self._ctrl_fw_public,
            self._ctrl_smartscreen, self._ctrl_lsass,
        ]
        return scroll

    def _refresh_controls(self):
        """Refresh all toggle card states from current system settings."""
        from modules.security_dashboard.security_reader import (
            check_pua_protection, check_controlled_folder_access,
            check_tamper_protection, check_cloud_protection,
            check_network_protection_defender, check_smartscreen,
            check_lsass_protection, check_firewall,
        )

        worker = COMWorker(lambda _w: {
            "pua": check_pua_protection(),
            "cfa": check_controlled_folder_access(),
            "tamper": check_tamper_protection(),
            "cloud": check_cloud_protection(),
            "netprot": check_network_protection_defender(),
            "smartscreen": check_smartscreen(),
            "lsass": check_lsass_protection(),
            "firewall": check_firewall(),
        })
        self._workers.append(worker)

        def on_result(data: dict):
            if not _widget_valid(self._tabs):
                return
            self._apply_control_data(data)

        def on_error(err):
            if not _widget_valid(self._tabs):
                return
            emsg = str(err[1]) if isinstance(err, tuple) else str(err)
            self._error_banner.set_error(f"Failed to load controls: {emsg}")
            self._error_banner.show()

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

        QThreadPool.globalInstance().start(worker)

    def _apply_control_data(self, data: dict):
        """Update toggle cards from a data dict."""
        def _apply(card, check_data, label):
            if not _widget_valid(card):
                return
            enabled = check_data.get("enabled")
            color = check_data.get("color", "amber")
            status = check_data.get("status", "Unknown")
            card.set_state(enabled, status, color)

        def _apply_fw(card, profile_name, fw_data):
            if not _widget_valid(card):
                return
            profiles = fw_data.get("profiles", {})
            enabled = profiles.get(profile_name, False)
            card.set_state(enabled, "On" if enabled else "Off",
                           "green" if enabled else "red")

        _apply(self._ctrl_pua, data["pua"], "PUA")
        _apply(self._ctrl_cfa, data["cfa"], "CFA")
        _apply(self._ctrl_tamper, data["tamper"], "Tamper")
        _apply(self._ctrl_netprot, data["netprot"], "NetworkProt")
        _apply(self._ctrl_smartscreen, data["smartscreen"], "SmartScreen")
        _apply(self._ctrl_lsass, data["lsass"], "LSASS")

        # Cloud protection — extract MAPS level
        cloud = data["cloud"]
        if _widget_valid(self._ctrl_cloud):
            c_enabled = cloud.get("enabled")
            c_color = cloud.get("color", "amber")
            c_status = cloud.get("status", "Unknown")
            self._ctrl_cloud.set_state(c_enabled, c_status, c_color)

        # Sample submission
        if _widget_valid(self._ctrl_sample):
            s_level = cloud.get("samples_level", 0)
            s_enabled = s_level >= 1
            s_labels = {0: "Never", 1: "Always prompt", 2: "Auto (safe)", 3: "Auto (all)"}
            s_status = s_labels.get(s_level, str(s_level))
            self._ctrl_sample.set_state(s_enabled, s_status,
                                        "green" if s_enabled else "red")

        # Real-time — derived from main defender check
        if _widget_valid(self._ctrl_realtime):
            from modules.security_dashboard.security_reader import check_defender
            d = check_defender()
            rt = d.get("real_time", False)
            self._ctrl_realtime.set_state(rt,
                                          "On" if rt else "Off",
                                          "green" if rt else "red")

        # Firewall profiles
        fw = data["firewall"]
        _apply_fw(self._ctrl_fw_domain, "Domain", fw)
        _apply_fw(self._ctrl_fw_private, "Private", fw)
        _apply_fw(self._ctrl_fw_public, "Public", fw)

    # ── Tab 3: Advanced ────────────────────────────────────────────────────

    def _build_advanced_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Defender Deep Scan Settings ──────────────────────────────────
        def_adv = QGroupBox("Defender — Deep Scan Settings")
        da_layout = QVBoxLayout(def_adv)

        self._ctrl_behav = _ToggleCard(
            "Behavior Monitoring", "\U0001f4ca",
            "Monitors program and system behaviors for suspicious activity patterns.")
        self._ctrl_behav.configure(
            "def_behav", set_defender_behavior_monitoring, set_defender_behavior_monitoring)
        da_layout.addWidget(self._ctrl_behav)

        self._ctrl_script = _ToggleCard(
            "Script Scanning", "\U0001f4dc",
            "Scans PowerShell, WSH, and other scripts before execution.")
        self._ctrl_script.configure(
            "def_script", set_defender_script_scanning, set_defender_script_scanning)
        da_layout.addWidget(self._ctrl_script)

        self._ctrl_ioav = _ToggleCard(
            "Downloaded Files Scanning (IOAV)", "\U0001f4e5",
            "Scans files as they are downloaded from the internet.")
        self._ctrl_ioav.configure(
            "def_ioav", set_defender_ioav, set_defender_ioav)
        da_layout.addWidget(self._ctrl_ioav)

        self._ctrl_archive = _ToggleCard(
            "Archive Scanning", "\U0001f4e6",
            "Scans inside compressed archives (ZIP, RAR, CAB).")
        self._ctrl_archive.configure(
            "def_archive", set_defender_archive_scanning, set_defender_archive_scanning)
        da_layout.addWidget(self._ctrl_archive)

        self._ctrl_removable = _ToggleCard(
            "Removable Drive Scanning", "\U0001f4be",
            "Scans files on USB drives and other removable media on access.")
        self._ctrl_removable.configure(
            "def_removable", set_defender_removable_drive_scanning,
            set_defender_removable_drive_scanning)
        da_layout.addWidget(self._ctrl_removable)

        self._ctrl_catchup = _ToggleCard(
            "Catch-Up Scans", "\U0001f504",
            "Runs quick/full scans automatically if a scheduled scan was missed.")
        self._ctrl_catchup.configure(
            "def_catchup", set_defender_catchup_scans, set_defender_catchup_scans)
        da_layout.addWidget(self._ctrl_catchup)

        layout.addWidget(def_adv)

        # ── Network Hardening ────────────────────────────────────────────
        net_group = QGroupBox("Network Hardening")
        net_layout = QVBoxLayout(net_group)

        self._ctrl_llmnr = _ToggleCard(
            "LLMNR (Multicast Name Resolution)", "\U0001f310",
            "Disables Link-Local Multicast Name Resolution to prevent MitM attacks. "
            "ON = enabled (insecure), OFF = disabled (secure).")
        self._ctrl_llmnr.configure(
            "llmnr", set_llmnr, set_llmnr)
        net_layout.addWidget(self._ctrl_llmnr)

        self._ctrl_wpad_toggle = _ToggleCard(
            "WPAD Auto-Discovery", "\U0001f50d",
            "Disables automatic proxy discovery to prevent proxy injection attacks.")
        self._ctrl_wpad_toggle.configure(
            "wpad", set_wpad, set_wpad)
        net_layout.addWidget(self._ctrl_wpad_toggle)

        layout.addWidget(net_group)

        # ── System Hardening ─────────────────────────────────────────────
        sys_hard = QGroupBox("System Hardening")
        sh_layout = QVBoxLayout(sys_hard)

        self._ctrl_wdigest = _ToggleCard(
            "WDigest Credential Caching", "\U0001f512",
            "Disables WDigest plaintext password caching in LSASS memory. "
            "OFF = secure (credentials not cached).")
        self._ctrl_wdigest.configure(
            "wdigest", set_wdigest_credential_caching, set_wdigest_credential_caching)
        sh_layout.addWidget(self._ctrl_wdigest)

        self._ctrl_pagefile = _ToggleCard(
            "Clear Pagefile at Shutdown", "\U0001f5d1",
            "Wipes the pagefile during clean shutdown to prevent data recovery. "
            "Adds ~30s to shutdown time.")
        self._ctrl_pagefile.configure(
            "pagefile", set_pagefile_clear, set_pagefile_clear)
        sh_layout.addWidget(self._ctrl_pagefile)

        self._ctrl_pslog = _ToggleCard(
            "PowerShell Script Block Logging", "\U0001f4dd",
            "Logs all PowerShell script blocks to the event log for forensic analysis.")
        self._ctrl_pslog.configure(
            "ps_log", set_ps_script_block_logging, set_ps_script_block_logging)
        sh_layout.addWidget(self._ctrl_pslog)

        layout.addWidget(sys_hard)
        layout.addStretch()
        scroll.setWidget(tab)

        # Collect cards
        self._advanced_cards = [
            self._ctrl_behav, self._ctrl_script, self._ctrl_ioav,
            self._ctrl_archive, self._ctrl_removable, self._ctrl_catchup,
            self._ctrl_llmnr, self._ctrl_wpad_toggle,
            self._ctrl_wdigest, self._ctrl_pagefile, self._ctrl_pslog,
        ]
        self._toggle_cards.extend(self._advanced_cards)
        return scroll

    def _refresh_advanced(self):
        """Load advanced tab toggle states."""
        from modules.security_dashboard.security_reader import (
            check_defender_behavior_monitoring, check_defender_script_scanning,
            check_defender_ioav, check_defender_archive_scanning,
            check_defender_removable_drive, check_defender_catchup_scan,
            check_llmnr, check_wpad, check_wdigest,
            check_pagefile_clear, check_ps_script_block_logging,
        )
        worker = COMWorker(lambda _w: {
            "behav": check_defender_behavior_monitoring(),
            "script": check_defender_script_scanning(),
            "ioav": check_defender_ioav(),
            "archive": check_defender_archive_scanning(),
            "removable": check_defender_removable_drive(),
            "catchup": check_defender_catchup_scan(),
            "llmnr": check_llmnr(),
            "wpad": check_wpad(),
            "wdigest": check_wdigest(),
            "pagefile": check_pagefile_clear(),
            "pslog": check_ps_script_block_logging(),
        })
        self._workers.append(worker)

        def on_result(data):
            if not _widget_valid(self._tabs):
                return
            def _apply(card, d):
                if _widget_valid(card):
                    card.set_state(d.get("enabled"), d.get("status", "?"), d.get("color", "amber"))
            _apply(self._ctrl_behav, data["behav"])
            _apply(self._ctrl_script, data["script"])
            _apply(self._ctrl_ioav, data["ioav"])
            _apply(self._ctrl_archive, data["archive"])
            _apply(self._ctrl_removable, data["removable"])
            _apply(self._ctrl_catchup, data["catchup"])
            _apply(self._ctrl_llmnr, data["llmnr"])
            _apply(self._ctrl_wpad_toggle, data["wpad"])
            _apply(self._ctrl_wdigest, data["wdigest"])
            _apply(self._ctrl_pagefile, data["pagefile"])
            _apply(self._ctrl_pslog, data["pslog"])

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(lambda e: None)
        QThreadPool.globalInstance().start(worker)

    # ── Tab 4: CVEs ───────────────────────────────────────────────────────

    def _build_cve_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        banner = QLabel("CVE Vulnerability Mitigations")
        f = banner.font(); f.setBold(True); pt = f.pointSize()
        if pt > 0: f.setPointSize(pt + 1)
        banner.setFont(f)
        layout.addWidget(banner)

        note = QLabel("Checks known CPU and Windows vulnerability mitigations via SpeculationControl module and registry.")
        note.setStyleSheet("color: #888; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._cve_overall_lbl = QLabel("Loading...")
        self._cve_overall_lbl.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px;")
        layout.addWidget(self._cve_overall_lbl)

        self._cve_progress = QProgressBar()
        self._cve_progress.setFixedHeight(3)
        self._cve_progress.setRange(0, 0)
        self._cve_progress.hide()
        layout.addWidget(self._cve_progress)

        # CVE grid
        self._cve_grid = QGridLayout()
        self._cve_grid.setSpacing(8)
        self._cve_cards: dict = {}
        cve_list = [
            ("spectre_v2", "Spectre v2 (BTI)", "CVE-2017-5715"),
            ("meltdown", "Meltdown", "CVE-2017-5754"),
            ("ssbd", "Spectre v4 / SSBD", "CVE-2018-3639"),
            ("l1tf", "L1TF / Foreshadow", "CVE-2018-3615"),
            ("mds", "MDS / Zombieload", "CVE-2018-12126"),
            ("printnightmare", "PrintNightmare", "CVE-2021-34527"),
            ("zerologon", "Zerologon", "CVE-2020-1472"),
            ("petitpotam", "PetitPotam", "CVE-2021-36942"),
            ("follina", "Follina (MSDT)", "CVE-2022-30190"),
            ("blacklotus", "BlackLotus", "CVE-2023-24932"),
            ("kerberos", "Kerberos Armoring", "CVE-2022-33679"),
            ("credential_guard", "Credential Guard VBS", "CVE-2022-22047"),
            ("ntlm_relay", "NTLM Relay Protection", "Various"),
            ("smb_ghost", "SMBGhost", "CVE-2020-0796"),
        ]
        for i, (key, name, cve) in enumerate(cve_list):
            row, col = divmod(i, 2)
            card = _StatusCard(f"{cve}\n{name}")
            card.setMinimumHeight(80)
            self._cve_grid.addWidget(card, row, col)
            self._cve_cards[key] = card
        layout.addLayout(self._cve_grid)
        layout.addStretch()
        scroll.setWidget(tab)
        return scroll

    def _refresh_cves(self):
        self._cve_progress.show()
        worker = COMWorker(lambda _w: {
            "spectre_v2": check_spectre_v2(),
            "meltdown": check_meltdown(),
            "ssbd": check_ssbd(),
            "l1tf": check_l1tf(),
            "mds": check_mds(),
            "printnightmare": check_printnightmare(),
            "zerologon": check_zerologon(),
            "petitpotam": check_petitpotam(),
            "follina": check_follina(),
            "blacklotus": check_blacklotus(),
            "kerberos": check_kerberos_armoring(),
            "credential_guard": check_credential_guard_vbs(),
            "ntlm_relay": check_ntlm_relay_protection(),
            "smb_ghost": check_smb_ghost(),
        })
        self._workers.append(worker)

        def on_result(data):
            if not _widget_valid(self._tabs): return
            self._cve_progress.hide()
            greens = ambers = reds = 0
            for key, card in self._cve_cards.items():
                d = data.get(key, {})
                if _widget_valid(card):
                    card.update_status(d)
                    c = d.get("color", "amber")
                    if c == "green": greens += 1
                    elif c == "red": reds += 1
                    else: ambers += 1
            if reds > 0:
                self._cve_overall_lbl.setText(f"{reds} vulnerable | {greens} mitigated | {ambers} unknown")
                self._cve_overall_lbl.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px; color: #E74C3C;")
            elif ambers > 0:
                self._cve_overall_lbl.setText(f"{greens} mitigated | {ambers} unknown — configure hardening policies")
                self._cve_overall_lbl.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px; color: #E67E22;")
            else:
                self._cve_overall_lbl.setText(f"All {greens} mitigations active")
                self._cve_overall_lbl.setStyleSheet("font-size: 13px; font-weight: bold; padding: 6px; color: #27AE60;")

        def on_error(err):
            if _widget_valid(self._tabs): return
            self._cve_progress.hide()

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(worker)

    # ── Tab 5: Security Events ────────────────────────────────────────────

    def _build_events_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        events_group = QGroupBox("Recent Security Events")
        events_layout = QVBoxLayout(events_group)
        self._events_progress = QProgressBar()
        self._events_progress.setFixedHeight(3)
        self._events_progress.setRange(0, 0)
        self._events_progress.hide()
        events_layout.addWidget(self._events_progress)

        self._events_table = QTableWidget()
        self._events_table.setColumnCount(4)
        self._events_table.setHorizontalHeaderLabels(
            ["Time", "Event ID", "Description", "Logon Info"])
        self._events_table.setColumnWidth(0, 160)
        self._events_table.setColumnWidth(1, 80)
        self._events_table.setColumnWidth(2, 320)
        self._events_table.setColumnWidth(3, 180)
        self._events_table.setAlternatingRowColors(True)
        self._events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._events_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._events_table.horizontalHeader().setStretchLastSection(True)
        self._events_table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0;
                           border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0;
                                   padding: 4px; border: none; }
        """)
        events_layout.addWidget(self._events_table)

        # Empty state
        self._events_empty = QLabel("No recent security events found.\n"
                                    "Click Refresh to load events from the Security log.")
        self._events_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._events_empty.setStyleSheet("color: #888; padding: 40px;")
        events_layout.addWidget(self._events_empty)
        self._events_empty.hide()

        layout.addWidget(events_group, 1)
        return tab

    def _load_events(self):
        """Load security events in background."""
        if not _widget_valid(self._events_progress):
            return
        self._events_progress.show()

        worker = Worker(lambda _w: get_security_events(30))
        self._workers.append(worker)

        def on_result(events: list):
            if not _widget_valid(self._events_table):
                return
            self._events_progress.hide()
            self._update_events_table(events)

        def on_error(err):
            if not _widget_valid(self._events_table):
                return
            self._events_progress.hide()
            emsg = str(err[1]) if isinstance(err, tuple) else str(err)
            self._error_banner.set_error(f"Failed to load events: {emsg}")
            self._error_banner.show()

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

        QThreadPool.globalInstance().start(worker)

    def _update_events_table(self, events: list):
        if not _widget_valid(self._events_table):
            return
        self._events_table.setRowCount(0)
        if not events:
            self._events_table.hide()
            self._events_empty.show()
            return
        self._events_table.show()
        self._events_empty.hide()

        for ev in events:
            row = self._events_table.rowCount()
            self._events_table.insertRow(row)
            self._events_table.setItem(row, 0, QTableWidgetItem(ev.get("time", "")))

            eid = ev.get("event_id", "")
            eid_item = QTableWidgetItem(eid)
            eid_color = "#E74C3C" if eid == "1102" else "#e0e0e0"
            eid_item.setForeground(QColor(eid_color))
            self._events_table.setItem(row, 1, eid_item)

            self._events_table.setItem(row, 2, QTableWidgetItem(
                ev.get("description", "")))

            # Logon type
            msg = ev.get("message", "")
            logon_info = ""
            m = re.search(r"LogonType:\s*(\d+)", msg)
            if m:
                logon_type = int(m.group(1))
                lt_map = {2: "Interactive", 3: "Network", 4: "Batch",
                          5: "Service", 7: "Unlock", 8: "Network Cleartext",
                          9: "New Credentials", 10: "Remote Interactive",
                          11: "Cached Interactive"}
                logon_info = f"LogonType {m.group(1)} ({lt_map.get(logon_type, '')})"
            self._events_table.setItem(row, 3, QTableWidgetItem(logon_info))

    # ── Quick Actions ─────────────────────────────────────────────────────

    def _do_quick_scan(self):
        self._action_status_lbl.setText("Quick scan running...")
        self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        def do_scan(worker):
            return run_quick_scan()

        def on_result(res):
            if not _widget_valid(self._action_status_lbl):
                return
            success = res.get("success", False)
            msg = res.get("message", "")
            if success:
                self._action_status_lbl.setText(f"Scan completed: {msg}")
                self._action_status_lbl.setStyleSheet("color: #27AE60; font-size: 12px;")
            else:
                self._action_status_lbl.setText(f"Scan finished: {msg[:150]}")
                self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        w = Worker(do_scan)
        w.signals.result.connect(on_result)
        w.signals.error.connect(
            lambda _: _on_label_error(self._action_status_lbl, "Error running scan."))
        self._workers.append(w)

        QThreadPool.globalInstance().start(w)

    def _do_update_defs(self):
        self._action_status_lbl.setText("Updating definitions...")
        self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        def do_update(worker):
            return run_update_definitions()

        def on_result(res):
            if not _widget_valid(self._action_status_lbl):
                return
            success = res.get("success", False)
            msg = res.get("message", "")
            if success:
                self._action_status_lbl.setText(f"Definitions updated: {msg}")
                self._action_status_lbl.setStyleSheet("color: #27AE60; font-size: 12px;")
                # Refresh signature state
                if self._loaded_controls:
                    self._refresh_controls()
            else:
                self._action_status_lbl.setText(f"Update: {msg[:150]}")
                self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        w = Worker(do_update)
        w.signals.result.connect(on_result)
        w.signals.error.connect(
            lambda _: _on_label_error(self._action_status_lbl, "Error updating definitions."))
        self._workers.append(w)

        QThreadPool.globalInstance().start(w)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        if not self._loaded_overview:
            self._loaded_overview = True
            self._refresh_overview()
        if not self._loaded_events:
            self._loaded_events = True
            self._load_events()

    def _on_tab_changed(self, index: int):
        """Lazy-load tabs when first selected."""
        if index == 1 and not self._loaded_controls:
            self._loaded_controls = True
            self._refresh_controls()
        elif index == 2 and not self._loaded_advanced:
            self._loaded_advanced = True
            self._refresh_advanced()
        elif index == 3 and not self._loaded_cves:
            self._loaded_cves = True
            self._refresh_cves()

    def _manual_refresh(self):
        """Called when user clicks Refresh button."""
        self._error_banner.clear()
        self._error_banner.hide()
        self._cancel_all_running_toggles()
        self._refresh_overview()
        if self._loaded_controls:
            self._refresh_controls()
        if self._loaded_advanced:
            self._refresh_advanced()
        if self._loaded_cves:
            self._refresh_cves()
        if self._loaded_events:
            self._load_events()

    def on_deactivate(self) -> None:
        self.cancel_all_workers()
        self._cancel_all_running_toggles()

    def on_stop(self) -> None:
        self.cancel_all_workers()
        self._cancel_all_running_toggles()

    def _cancel_all_running_toggles(self):
        """Cancel workers on individual toggle cards."""
        for card in self._toggle_cards:
            try:
                card.cancel()
            except Exception:
                logger.warning("Error cancelling toggle card %s", card, exc_info=True)


def _on_label_error(label, message: str):
    """Helper: show error on a QLabel if it still exists."""
    if _widget_valid(label):
        label.setText(message)
        label.setStyleSheet("color: #E74C3C; font-size: 12px;")


# ── Search Provider ────────────────────────────────────────────────────────

class SecuritySearchProvider(SearchProvider):
    """Search across security dashboard checks.

    Returns the current security posture so users can search for
    terms like "defender", "firewall", "bitlocker", etc.
    """

    module_name = "Security Dashboard"

    def search(self, query: SearchQuery) -> list:
        if not query.text:
            return []
        q = query.text.lower()
        results = []

        try:
            from modules.security_dashboard.security_reader import (
                check_defender, check_firewall, check_bitlocker,
                check_secure_boot_tpm, check_uac, check_smartscreen,
                check_hvci, check_credential_guard, check_lsass_protection,
                check_tamper_protection, check_pua_protection,
                check_controlled_folder_access, check_cloud_protection,
                check_network_protection_defender, check_rdp, check_smbv1,
            )
            checks = {
                "defender": ("Windows Defender", check_defender),
                "firewall": ("Windows Firewall", check_firewall),
                "bitlocker": ("BitLocker Drive Encryption", check_bitlocker),
                "secure boot": ("Secure Boot & TPM", check_secure_boot_tpm),
                "tpm": ("TPM Module", check_secure_boot_tpm),
                "uac": ("User Account Control", check_uac),
                "smartscreen": ("SmartScreen Filter", check_smartscreen),
                "hvci": ("HVCI / Memory Integrity", check_hvci),
                "memory integrity": ("Memory Integrity", check_hvci),
                "credential guard": ("Credential Guard", check_credential_guard),
                "lsass": ("LSASS Protection", check_lsass_protection),
                "tamper": ("Tamper Protection", check_tamper_protection),
                "pua": ("PUA Protection", check_pua_protection),
                "controlled folder": ("Controlled Folder Access",
                                       check_controlled_folder_access),
                "ransomware": ("Controlled Folder Access",
                               check_controlled_folder_access),
                "cloud": ("Cloud-Delivered Protection", check_cloud_protection),
                "network protection": ("Network Protection",
                                       check_network_protection_defender),
                "rdp": ("Remote Desktop", check_rdp),
                "remote desktop": ("Remote Desktop", check_rdp),
                "smbv1": ("SMBv1 Protocol", check_smbv1),
                "smb": ("SMBv1 Protocol", check_smbv1),
            }
            from datetime import datetime
            for term, (label, fn) in checks.items():
                if term in q or any(w in q for w in label.lower().split()):
                    try:
                        data = fn()
                        status = data.get("status", "Unknown")
                        color = data.get("color", "amber")
                        results.append(SearchResult(
                            timestamp=datetime.now(),
                            source="Security Dashboard",
                            type=f"Security Check ({color})",
                            summary=f"{label}: {status}",
                            detail=data.get("details", []),
                            relevance=0.9,
                        ))
                    except Exception:
                        logger.warning("Security search failed for '%s'", label, exc_info=True)
        except Exception:
            logger.warning("Security search provider failed", exc_info=True)
        return results[:20]

    def get_filterable_fields(self) -> list:
        return [
            FilterField("severity", "Status", ["green", "amber", "red"]),
        ]
