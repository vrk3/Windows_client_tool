import json
import subprocess
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QProgressBar, QLineEdit,
    QComboBox, QMessageBox,
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker

CREATE_NO_WINDOW = 0x08000000

_COLS = ["Display Name", "Direction", "Action", "Enabled", "Profile", "Group"]

_PS_CMD = (
    "Get-NetFirewallRule | Select-Object DisplayName,"
    "@{N='Direction';E={$_.Direction.ToString()}},"
    "@{N='Action';E={$_.Action.ToString()}},"
    "@{N='Enabled';E={$_.Enabled.ToString()}},"
    "@{N='Profile';E={$_.Profile.ToString()}},"
    "Group | ConvertTo-Json -Compress -Depth 1"
)


def get_firewall_rules() -> List[Dict]:
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_CMD],
        capture_output=True, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    raw = proc.stdout.strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    rules = []
    for r in data:
        rules.append({
            "Display Name": r.get("DisplayName") or "",
            "Direction":    r.get("Direction") or "",
            "Action":       r.get("Action") or "",
            "Enabled":      r.get("Enabled") or "",
            "Profile":      r.get("Profile") or "",
            "Group":        r.get("Group") or "",
        })
    return rules


def set_rule_enabled(display_name: str, enabled: bool) -> None:
    state = "True" if enabled else "False"
    cmd = f'Set-NetFirewallRule -DisplayName "{display_name}" -Enabled {state}'
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        creationflags=CREATE_NO_WINDOW, check=True,
    )


class FirewallRulesModule(BaseModule):
    name = "Firewall Rules"
    icon = "🛡"
    description = "View and toggle Windows Firewall inbound/outbound rules"
    requires_admin = True
    group = ModuleGroup.MANAGE

    def create_widget(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(8, 8, 8, 8)

        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._enable_btn = QPushButton("Enable Rule")
        self._disable_btn = QPushButton("Disable Rule")
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter by name...")
        self._filter_edit.setMaximumWidth(220)
        self._dir_combo = QComboBox()
        self._dir_combo.addItems(["All", "Inbound", "Outbound"])
        self._enabled_combo = QComboBox()
        self._enabled_combo.addItems(["All", "Enabled", "Disabled"])
        self._status_label = QLabel("Click Refresh to load.")
        for btn in (self._enable_btn, self._disable_btn):
            btn.setEnabled(False)
        for w in (self._refresh_btn, self._enable_btn, self._disable_btn):
            toolbar.addWidget(w)
        toolbar.addWidget(QLabel("Filter:"))
        toolbar.addWidget(self._filter_edit)
        toolbar.addWidget(self._dir_combo)
        toolbar.addWidget(self._enabled_combo)
        toolbar.addStretch()
        toolbar.addWidget(self._status_label)
        layout.addLayout(toolbar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(_COLS)):
            self._table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        layout.addWidget(self._table, 1)

        self._all_rules: List[Dict] = []
        self._outer = outer

        self._refresh_btn.clicked.connect(self._do_refresh)
        self._filter_edit.textChanged.connect(self._apply_filter)
        self._dir_combo.currentTextChanged.connect(self._apply_filter)
        self._enabled_combo.currentTextChanged.connect(self._apply_filter)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._enable_btn.clicked.connect(lambda: self._do_toggle(True))
        self._disable_btn.clicked.connect(lambda: self._do_toggle(False))

        return outer

    def _do_refresh(self):
        self._refresh_btn.setEnabled(False)
        self._enable_btn.setEnabled(False)
        self._disable_btn.setEnabled(False)
        self._status_label.setText("Loading firewall rules...")
        self._progress.show()
        worker = Worker(lambda _w: get_firewall_rules())
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_result(self, rules: List[Dict]):
        self._all_rules = rules
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._apply_filter()

    def _on_error(self, err: str):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status_label.setText(f"Error: {err}")

    def _apply_filter(self):
        text = self._filter_edit.text().lower()
        dir_f = self._dir_combo.currentText()
        ena_f = self._enabled_combo.currentText()
        rows = []
        for r in self._all_rules:
            if text and text not in r["Display Name"].lower():
                continue
            if dir_f != "All" and r["Direction"] != dir_f:
                continue
            if ena_f == "Enabled" and r["Enabled"] != "True":
                continue
            if ena_f == "Disabled" and r["Enabled"] != "False":
                continue
            rows.append(r)

        self._table.setRowCount(len(rows))
        for r, rule in enumerate(rows):
            for c, col in enumerate(_COLS):
                item = QTableWidgetItem(rule.get(col, ""))
                if col == "Action":
                    item.setForeground(
                        QColor("#2ecc71") if rule["Action"] == "Allow" else QColor("#e74c3c")
                    )
                if col == "Direction":
                    item.setForeground(
                        QColor("#3498db") if rule["Direction"] == "Inbound" else QColor("#9b59b6")
                    )
                item.setData(Qt.ItemDataRole.UserRole, rule["Display Name"])
                self._table.setItem(r, c, item)
        self._status_label.setText(f"{len(rows)} / {len(self._all_rules)} rule(s)")

    def _on_selection_changed(self):
        has = bool(self._table.selectedItems())
        self._enable_btn.setEnabled(has)
        self._disable_btn.setEnabled(has)

    def _get_selected_name(self) -> Optional[str]:
        items = self._table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _do_toggle(self, enable: bool):
        name = self._get_selected_name()
        if not name:
            return
        self._refresh_btn.setEnabled(False)
        verb = "Enabling" if enable else "Disabling"
        self._status_label.setText(f"{verb} rule...")

        def _on_err(e):
            QMessageBox.warning(self._outer, "Error", f"Failed to update rule:\n{e}")
            self._do_refresh()

        worker = Worker(lambda _w: set_rule_enabled(name, enable))
        worker.signals.result.connect(lambda _: self._do_refresh())
        worker.signals.error.connect(_on_err)
        QThreadPool.globalInstance().start(worker)

    def on_activate(self):
        if not getattr(self, "_loaded", False):
            self._loaded = True
            self._do_refresh()

    def on_start(self, app): self.app = app
    def on_stop(self): self.cancel_all_workers()
    def on_deactivate(self): pass
