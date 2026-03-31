import json
import subprocess
from datetime import datetime

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                              QPushButton, QLabel, QFrame, QProgressBar, QSizePolicy,
                              QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
                              QGroupBox, QFormLayout)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor, QFont

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker, COMWorker
from modules.security_dashboard.security_reader import get_all_security_status

COLOR_MAP = {
    "green": "#27AE60",
    "amber": "#E67E22",
    "red": "#E74C3C",
}


class _StatusCard(QFrame):
    """A coloured status card with title, status badge, and detail rows."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)

        self._title_lbl = QLabel(title)
        font = self._title_lbl.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self._title_lbl.setFont(font)
        layout.addWidget(self._title_lbl)

        self._status_lbl = QLabel("Loading...")
        self._status_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self._status_lbl)

        self._details_layout = QVBoxLayout()
        layout.addLayout(self._details_layout)
        layout.addStretch()

    def update_status(self, data: dict):
        color = COLOR_MAP.get(data.get("color", "amber"), "#888888")
        status = data.get("status", "Unknown")
        self._status_lbl.setText(status)
        self._status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color};")
        self.setStyleSheet(f"QFrame {{ border-left: 4px solid {color}; }}")

        # Clear detail rows
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


class SecurityDashboardModule(BaseModule):
    name = "Security Dashboard"
    icon = "🛡️"
    description = "Windows security status overview"
    requires_admin = True
    group = ModuleGroup.SYSTEM

    def create_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header_row = QHBoxLayout()
        self._banner = QLabel("Security Status")
        font = self._banner.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self._banner.setFont(font)
        refresh_btn = QPushButton("Refresh")
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        header_row.addWidget(self._banner, 1)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)
        layout.addWidget(self._progress)

        # Tab widget
        tabs = QTabWidget()
        tabs.addTab(self._build_overview_tab(refresh_btn), "Overview")
        tabs.addTab(self._build_defender_deep_dive_tab(), "Defender Deep Dive")
        layout.addWidget(tabs, 1)

        def do_refresh():
            refresh_btn.setEnabled(False)
            self._progress.show()
            self._banner.setText("Security Status — Loading...")

            worker = COMWorker(lambda _w: get_all_security_status())

            def on_result(data: dict):
                refresh_btn.setEnabled(True)
                self._progress.hide()
                self._defender_card.update_status(data["defender"])
                self._firewall_card.update_status(data["firewall"])
                self._bitlocker_card.update_status(data["bitlocker"])
                self._boot_card.update_status(data["secure_boot_tpm"])
                # Overall banner
                colors = [d.get("color", "amber") for d in data.values()]
                if all(c == "green" for c in colors):
                    overall = "✅ Secure"
                    col = "#27AE60"
                elif any(c == "red" for c in colors):
                    overall = "❌ Issues Detected"
                    col = "#E74C3C"
                else:
                    overall = "⚠ Warnings"
                    col = "#E67E22"
                self._banner.setText(f"Security Status — {overall}")
                self._banner.setStyleSheet(f"color: {col};")

            def on_error(err):
                refresh_btn.setEnabled(True)
                self._progress.hide()
                self._banner.setText(f"Error: {err}")

            worker.signals.result.connect(on_result)
            worker.signals.error.connect(on_error)
            QThreadPool.globalInstance().start(worker)

        refresh_btn.clicked.connect(do_refresh)
        self._security_load_fn = do_refresh
        return w

    # ── Overview tab ────────────────────────────────────────────────────────

    def _build_overview_tab(self, refresh_btn) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        grid = QGridLayout()
        grid.setSpacing(12)
        self._defender_card = _StatusCard("🛡 Windows Defender")
        self._firewall_card = _StatusCard("🔥 Firewall")
        self._bitlocker_card = _StatusCard("💾 BitLocker")
        self._boot_card = _StatusCard("🔐 Secure Boot & TPM")
        grid.addWidget(self._defender_card, 0, 0)
        grid.addWidget(self._firewall_card, 0, 1)
        grid.addWidget(self._bitlocker_card, 1, 0)
        grid.addWidget(self._boot_card, 1, 1)
        layout.addLayout(grid)
        layout.addStretch()
        return tab

    # ── Defender Deep Dive tab ──────────────────────────────────────────────

    def _build_defender_deep_dive_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        # ── Top row: Signature info + Exploit Protection ──────────────────
        top_row = QHBoxLayout()

        # Signature Age card
        sig_card = QFrame()
        sig_card.setFrameShape(QFrame.Shape.StyledPanel)
        sig_card.setMinimumHeight(130)
        sig_layout = QVBoxLayout(sig_card)
        sig_title = QLabel("🛡 Signature Definitions")
        f = sig_title.font()
        f.setBold(True)
        sig_title.setFont(f)
        sig_layout.addWidget(sig_title)
        self._sig_status_lbl = QLabel("Loading...")
        self._sig_status_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        sig_layout.addWidget(self._sig_status_lbl)
        self._sig_details_lbl = QLabel()
        self._sig_details_lbl.setStyleSheet("color: gray; font-size: 12px;")
        sig_layout.addWidget(self._sig_details_lbl)
        sig_layout.addStretch()
        top_row.addWidget(sig_card, 1)

        # Exploit Protection card
        ep_card = QFrame()
        ep_card.setFrameShape(QFrame.Shape.StyledPanel)
        ep_card.setMinimumHeight(130)
        ep_layout = QVBoxLayout(ep_card)
        ep_title = QLabel("🔧 Exploit Protection")
        ep_title.setFont(f)
        ep_layout.addWidget(ep_title)
        self._ep_status_lbl = QLabel("Loading...")
        self._ep_status_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        ep_layout.addWidget(self._ep_status_lbl)
        self._ep_details_lbl = QLabel()
        self._ep_details_lbl.setStyleSheet("color: gray; font-size: 12px;")
        ep_layout.addWidget(self._ep_details_lbl)
        ep_layout.addStretch()
        top_row.addWidget(ep_card, 1)

        layout.addLayout(top_row)

        # ── Quick Actions ─────────────────────────────────────────────────
        actions_group = QGroupBox("Defender Quick Actions")
        actions_layout = QHBoxLayout(actions_group)
        self._quick_scan_btn = QPushButton("⚡ Quick Scan")
        self._quick_scan_btn.setToolTip("Run Windows Defender Quick Scan")
        self._quick_scan_btn.clicked.connect(self._do_quick_scan)
        self._update_defs_btn = QPushButton("🔄 Update Definitions")
        self._update_defs_btn.setToolTip("Update Windows Defender signature definitions")
        self._update_defs_btn.clicked.connect(self._do_update_definitions)
        self._action_status_lbl = QLabel()
        self._action_status_lbl.setStyleSheet("color: gray; font-size: 12px;")
        actions_layout.addWidget(self._quick_scan_btn)
        actions_layout.addWidget(self._update_defs_btn)
        actions_layout.addWidget(self._action_status_lbl)
        actions_layout.addStretch()
        layout.addWidget(actions_group)

        # ── Recent Security Events ────────────────────────────────────────
        events_group = QGroupBox("Recent Security Events")
        events_layout = QVBoxLayout(events_group)
        self._events_progress = QProgressBar()
        self._events_progress.setFixedHeight(3)
        self._events_progress.setRange(0, 0)
        self._events_progress.hide()
        events_layout.addWidget(self._events_progress)

        self._events_table = QTableWidget()
        self._events_table.setColumnCount(4)
        self._events_table.setHorizontalHeaderLabels(["Time", "Event ID", "Description", "Logon Info"])
        self._events_table.setColumnWidth(0, 160)
        self._events_table.setColumnWidth(1, 80)
        self._events_table.setColumnWidth(2, 300)
        self._events_table.setColumnWidth(3, 200)
        self._events_table.setAlternatingRowColors(True)
        self._events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._events_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._events_table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0; border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0; padding: 4px; border: none; }
        """)
        events_layout.addWidget(self._events_table)
        layout.addWidget(events_group, 1)

        # Load data for this tab
        self._load_defender_deep_dive()
        return tab

    def _load_defender_deep_dive(self):
        """Load signature info, exploit protection, and security events."""
        self._events_progress.show()

        # ── Signature age ─────────────────────────────────────────────────
        def load_sig(worker):
            try:
                result = subprocess.run([
                    "powershell", "-Command",
                    "Get-MpComputerStatus | Select-Object AntivirusSignatureLastUpdated, "
                    "AntivirusSignatureAge, AntivirusEnabled, AntivirusSignatureVersion | "
                    "ConvertTo-Json -Compress"
                ], capture_output=True, text=True, timeout=30)
                if result.stdout.strip():
                    return json.loads(result.stdout)
                return None
            except Exception:
                return None

        # ── Exploit protection ────────────────────────────────────────────
        def load_ep(worker):
            try:
                result = subprocess.run([
                    "powershell", "-Command",
                    "Get-ProcessMitigation -Policy | Select-Object -First 20 | "
                    "Format-Table -AutoSize"
                ], capture_output=True, text=True, timeout=30, errors="replace")
                return result.stdout.strip()
            except Exception:
                return None

        # ── Security events ──────────────────────────────────────────────
        def load_events(worker):
            try:
                result = subprocess.run([
                    "wevtutil", "qe", "Security", "/c:30", "/f:text", "/rd:true"
                ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
                return self._parse_security_events(result.stdout)
            except Exception:
                return []

        def on_sig_result(sig_data):
            self._update_sig_card(sig_data)

        def on_ep_result(ep_text):
            self._update_ep_card(ep_text)

        def on_events_result(events):
            self._events_progress.hide()
            self._update_events_table(events)

        w_sig = Worker(load_sig)
        w_sig.signals.result.connect(on_sig_result)
        QThreadPool.globalInstance().start(w_sig)

        w_ep = Worker(load_ep)
        w_ep.signals.result.connect(on_ep_result)
        QThreadPool.globalInstance().start(w_ep)

        w_events = Worker(load_events)
        w_events.signals.result.connect(on_events_result)
        QThreadPool.globalInstance().start(w_events)

    def _update_sig_card(self, data):
        if data is None:
            self._sig_status_lbl.setText("Unavailable")
            self._sig_status_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #888;")
            self._sig_details_lbl.setText("Could not retrieve signature info")
            return

        enabled = data.get("AntivirusEnabled", False)
        age_hours = data.get("AntivirusSignatureAge", -1)
        last_updated = data.get("AntivirusSignatureLastUpdated", "")
        version = data.get("AntivirusSignatureVersion", "Unknown")

        if enabled:
            color = "#27AE60"
            status = "✅ Enabled"
        else:
            color = "#E74C3C"
            status = "❌ Disabled"

        self._sig_status_lbl.setText(f"{status} — v{version}")
        self._sig_status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color};")

        if age_hours >= 0:
            if age_hours < 24:
                age_str = f"{age_hours} hours old"
                age_color = "#27AE60"
            elif age_hours < 168:
                age_str = f"{age_hours} hours old (outdated)"
                age_color = "#E67E22"
            else:
                age_str = f"{age_hours} hours old (stale)"
                age_color = "#E74C3C"
        else:
            age_str = "Unknown"
            age_color = "#888"

        if last_updated:
            try:
                dt = datetime.strptime(last_updated[:19], "%Y-%m-%dT%H:%M:%S")
                last_updated = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass
        self._sig_details_lbl.setText(
            f"<span style='color:{age_color}'>Definitions: {age_str}</span><br>"
            f"Last updated: {last_updated or 'N/A'}"
        )

    def _update_ep_card(self, text):
        if text is None or not text:
            self._ep_status_lbl.setText("Unavailable")
            self._ep_status_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #888;")
            self._ep_details_lbl.setText("Could not retrieve Exploit Protection settings")
            return

        # Count mitigations by scanning for "ON" keywords
        on_count = text.upper().count(" ON")
        off_count = text.upper().count(" OFF")
        total = on_count + off_count
        mitigated = on_count

        if total == 0:
            color = "#888"
            status = "Unknown"
        elif mitigated / total > 0.7:
            color = "#27AE60"
            status = f"✅ {mitigated} mitigations active"
        elif mitigated / total > 0.3:
            color = "#E67E22"
            status = f"⚠ {mitigated}/{total} mitigations active"
        else:
            color = "#E74C3C"
            status = f"❌ Only {mitigated}/{total} mitigations active"

        self._ep_status_lbl.setText(status)
        self._ep_status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color};")
        # Show a preview of the table
        preview = text[:400].replace("\n", " | ")
        self._ep_details_lbl.setText(preview + ("..." if len(text) > 400 else ""))

    def _parse_security_events(self, output: str) -> list:
        """Parse wevtutil Security log text output into structured records."""
        events = []
        current = {}
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("Event["):
                if current:
                    events.append(current)
                current = {}
            elif line.startswith("EventID:"):
                current["event_id"] = line.split(":", 1)[1].strip()
            elif line.startswith("TimeCreated:"):
                tc = line.split(":", 1)[1].strip()
                try:
                    # Format: SystemTime=2026-03-31T...
                    tc = tc.replace("SystemTime=", "")
                    dt = datetime.fromisoformat(tc[:19])
                    current["time"] = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    current["time"] = tc[:16]
            elif line.startswith("Message:"):
                current["message"] = line.split(":", 1)[1].strip()
                # Extract brief description
                msg = current["message"]
                if "logon" in msg.lower() and "4624" in msg:
                    current["description"] = "Logon success"
                elif "logon" in msg.lower() and "4625" in msg:
                    current["description"] = "Logon failure"
                elif "logoff" in msg.lower() and "4634" in msg:
                    current["description"] = "Logoff"
                elif "explicit credentials" in msg.lower() or "4648" in msg:
                    current["description"] = "Explicit credentials logon"
                elif "registry" in msg.lower() and "4657" in msg:
                    current["description"] = "Registry value modified"
                else:
                    current["description"] = msg[:80] if len(msg) > 80 else msg
        if current:
            events.append(current)

        # Filter to known event IDs for relevance
        known_ids = {"4624", "4625", "4634", "4648", "4657"}
        filtered = [e for e in events if e.get("event_id") in known_ids]
        return filtered[:20]

    def _update_events_table(self, events: list):
        self._events_table.setRowCount(0)
        for ev in events:
            row = self._events_table.rowCount()
            self._events_table.insertRow(row)
            self._events_table.setItem(row, 0, QTableWidgetItem(ev.get("time", "")))
            self._events_table.setItem(row, 1, QTableWidgetItem(ev.get("event_id", "")))
            self._events_table.setItem(row, 2, QTableWidgetItem(ev.get("description", "")))
            # Logon type info from message
            msg = ev.get("message", "")
            logon_info = ""
            if "LogonType:" in msg:
                import re
                m = re.search(r"LogonType:\s*(\d+)", msg)
                if m:
                    logon_info = f"LogonType {m.group(1)}"
            self._events_table.setItem(row, 3, QTableWidgetItem(logon_info))

    def _do_quick_scan(self):
        self._quick_scan_btn.setEnabled(False)
        self._action_status_lbl.setText("Quick scan running...")
        self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        def do_scan(worker):
            result = subprocess.run([
                "C:\\Program Files\\Windows Defender\\MpCmdRun.exe",
                "-Scan", "-ScanType", "1"
            ], capture_output=True, text=True, timeout=600)
            return result.returncode == 0, result.stdout + result.stderr

        def on_result(res):
            success, output = res
            self._quick_scan_btn.setEnabled(True)
            if success:
                self._action_status_lbl.setText("✅ Quick scan completed successfully.")
                self._action_status_lbl.setStyleSheet("color: #27AE60; font-size: 12px;")
            else:
                snippet = output[:200].replace("\n", " ")
                self._action_status_lbl.setText(f"⚠ Scan finished (code may differ): {snippet}")
                self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        w = Worker(do_scan)
        w.signals.result.connect(on_result)
        w.signals.error.connect(lambda _: (self._quick_scan_btn.setEnabled(True),
                                           self._action_status_lbl.setText("Error running scan.")))
        QThreadPool.globalInstance().start(w)

    def _do_update_definitions(self):
        self._update_defs_btn.setEnabled(False)
        self._action_status_lbl.setText("Updating definitions...")

        def do_update(worker):
            result = subprocess.run([
                "C:\\Program Files\\Windows Defender\\MpCmdRun.exe",
                "-SignatureUpdate"
            ], capture_output=True, text=True, timeout=120)
            return result.returncode == 0, result.stdout + result.stderr

        def on_result(res):
            success, output = res
            self._update_defs_btn.setEnabled(True)
            if success:
                self._action_status_lbl.setText("✅ Definitions updated successfully.")
                self._action_status_lbl.setStyleSheet("color: #27AE60; font-size: 12px;")
                # Refresh signature card
                self._load_defender_deep_dive()
            else:
                self._action_status_lbl.setText("⚠ Update may have succeeded (check Defender UI).")
                self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        w = Worker(do_update)
        w.signals.result.connect(on_result)
        w.signals.error.connect(lambda _: (self._update_defs_btn.setEnabled(True),
                                           self._action_status_lbl.setText("Error updating definitions.")))
        QThreadPool.globalInstance().start(w)

    def on_activate(self) -> None:
        if not getattr(self, "_security_loaded", False) and hasattr(self, "_security_load_fn"):
            self._security_loaded = True
            self._security_load_fn()

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
