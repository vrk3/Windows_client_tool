"""Firewall Rules Manager — view and manage Windows Firewall rules via netsh."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QProgressBar, QLineEdit,
    QComboBox, QMessageBox, QInputDialog, QFileDialog,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker


@dataclass
class FirewallRule:
    name: str
    enabled: str
    direction: str
    action: str
    protocol: str
    local_port: str
    remote_port: str
    program: str
    profile: str


_COLS = [
    "Name", "Enabled", "Direction", "Action",
    "Protocol", "Local Port", "Remote Port", "Program", "Profile",
]
_COL_WIDTHS = [200, 60, 70, 70, 70, 80, 80, 150, 80]


# ------------------------------------------------------------------
# netsh data fetching / manipulation
# ------------------------------------------------------------------

def fetch_firewall_rules() -> List[FirewallRule]:
    """Parse output of 'netsh advfirewall firewall show rule all'."""
    proc = subprocess.run(
        ["netsh", "advfirewall", "firewall", "show", "rule", "all"],
        capture_output=True, text=True, timeout=120,
    )
    raw = proc.stdout
    return _parse_rules(raw)


def _parse_rules(raw: str) -> List[FirewallRule]:
    """Split netsh output into FirewallRule dataclass instances."""
    rules: List[FirewallRule] = []
    # Rules are separated by blank lines; each block starts with Rule Name:
    blocks = re.split(r"\n\s*\n", raw)

    for block in blocks:
        lines = block.strip().split("\n")
        if not lines:
            continue

        data: dict = {}
        for line in lines:
            if not line.strip():
                continue
            # Format: "  Field Name:        value"
            m = re.match(r"^\s*(Rule Name|Enabled|Direction|Action|Protocol|Local Port|Remote Port|Program|Profile):\s*(.*)$", line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                data[key] = val

        if data.get("Rule Name"):
            rules.append(FirewallRule(
                name=data.get("Rule Name", ""),
                enabled=data.get("Enabled", ""),
                direction=data.get("Direction", ""),
                action=data.get("Action", ""),
                protocol=data.get("Protocol", ""),
                local_port=data.get("Local Port", ""),
                remote_port=data.get("Remote Port", ""),
                program=data.get("Program", ""),
                profile=data.get("Profile", ""),
            ))
    return rules


def netsh_set_rule_enabled(name: str, enable: bool) -> None:
    state = "yes" if enable else "no"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "set", "rule",
         f"name={name}", "new", f"enable={state}"],
        check=True, capture_output=True, text=True,
    )


def netsh_delete_rule(name: str) -> None:
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "delete", "rule",
         f"name={name}"],
        check=True, capture_output=True, text=True,
    )


def netsh_block_program(exe_path: str) -> None:
    rule_name = f"Block {Path(exe_path).stem}"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "add", "rule",
         f"name={rule_name}",
         "dir=out", "action=block",
         f"program={exe_path}", "enable=yes"],
        check=True, capture_output=True, text=True,
    )


def netsh_open_port(port: int, direction: str = "in") -> None:
    name = f"Allow {direction.title()} Port {port}"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "add", "rule",
         f"name={name}",
         f"dir={direction}", "action=allow",
         f"localport={port}", "protocol=tcp", "enable=yes"],
        check=True, capture_output=True, text=True,
    )


def netsh_export_rules(path: str) -> None:
    subprocess.run(
        ["netsh", "advfirewall", "export", f'"{path}"'],
        check=True, capture_output=True, text=True,
    )


def netsh_import_rules(path: str) -> None:
    subprocess.run(
        ["netsh", "advfirewall", "import", f'"{path}"'],
        check=True, capture_output=True, text=True,
    )


# ------------------------------------------------------------------
# Module
# ------------------------------------------------------------------

class FirewallManagerModule(BaseModule):
    name = "Firewall Rules"
    icon = "🛡️"
    description = "View and manage Windows Firewall rules"
    group = ModuleGroup.MANAGE
    requires_admin = True

    def create_widget(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(8, 8, 8, 8)

        # ---- Toolbar ----
        toolbar = QHBoxLayout()

        self._refresh_btn = QPushButton("Refresh")
        self._block_btn = QPushButton("Block Program")
        self._open_port_btn = QPushButton("Open Port")
        self._delete_btn = QPushButton("Delete Rule")
        self._export_btn = QPushButton("Export Rules")
        self._import_btn = QPushButton("Import Rules")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Search name or program...")
        self._search_edit.setMaximumWidth(220)

        self._dir_combo = QComboBox()
        self._dir_combo.addItems(["All", "Inbound", "Outbound"])

        self._action_combo = QComboBox()
        self._action_combo.addItems(["All", "Allow", "Block"])

        self._profile_combo = QComboBox()
        self._profile_combo.addItems(["All", "Domain", "Private", "Public"])

        self._delete_btn.setEnabled(False)

        for btn in (self._refresh_btn, self._block_btn, self._open_port_btn,
                    self._delete_btn, self._export_btn, self._import_btn):
            toolbar.addWidget(btn)
        toolbar.addWidget(QLabel("Direction:"))
        toolbar.addWidget(self._dir_combo)
        toolbar.addWidget(QLabel("Action:"))
        toolbar.addWidget(self._action_combo)
        toolbar.addWidget(QLabel("Profile:"))
        toolbar.addWidget(self._profile_combo)
        toolbar.addWidget(self._search_edit)
        layout.addLayout(toolbar)

        # ---- Progress ----
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # ---- Table ----
        self._table = QTableWidget(0, len(_COLS))
        self._table.setHorizontalHeaderLabels(_COLS)
        self._table.setSortingEnabled(True)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        for i, width in enumerate(_COL_WIDTHS[:-1]):
            self._table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.ResizeMode.Fixed)
            self._table.setColumnWidth(i, width)
        self._table.horizontalHeader().setSectionResizeMode(
            len(_COLS) - 1, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self._table, 1)

        # ---- Status bar ----
        self._status_lbl = QLabel("Click Refresh to load firewall rules.")
        self._status_lbl.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(self._status_lbl)

        self._all_rules: List[FirewallRule] = []
        self._outer = outer

        # ---- Signal connections ----
        self._refresh_btn.clicked.connect(self._do_refresh)
        self._block_btn.clicked.connect(self._block_program)
        self._open_port_btn.clicked.connect(self._open_port)
        self._delete_btn.clicked.connect(self._delete_rule)
        self._export_btn.clicked.connect(self._export_rules)
        self._import_btn.clicked.connect(self._import_rules)
        self._search_edit.textChanged.connect(self._apply_filter)
        self._dir_combo.currentTextChanged.connect(self._apply_filter)
        self._action_combo.currentTextChanged.connect(self._apply_filter)
        self._profile_combo.currentTextChanged.connect(self._apply_filter)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.itemDoubleClicked.connect(self._on_double_click)

        return outer

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _do_refresh(self) -> None:
        self._set_buttons_enabled(False)
        self._progress.show()
        self._status_lbl.setText("Loading firewall rules...")

        def work(_w):
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_rules_loaded(self, rules: List[FirewallRule]) -> None:
        self._all_rules = rules
        self._progress.hide()
        self._set_buttons_enabled(True)
        self._apply_filter()
        self._status_lbl.setText(f"{len(rules)} firewall rule(s) loaded.")

    def _on_error(self, err: str) -> None:
        self._progress.hide()
        self._set_buttons_enabled(True)
        self._status_lbl.setText(f"Error: {err}")
        QMessageBox.warning(self._outer, "Error", f"Failed to load rules:\n{err}")

    def _block_program(self) -> None:
        exe_path, _ = QFileDialog.getOpenFileName(
            self._outer, "Select Program to Block",
            "", "Executables (*.exe);;All Files (*)",
        )
        if not exe_path:
            return

        reply = QMessageBox.question(
            self._outer, "Confirm Block",
            f"Block outbound traffic for:\n{exe_path}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._progress.show()
        self._status_lbl.setText(f"Creating block rule for {Path(exe_path).stem}...")

        def work(_w):
            netsh_block_program(exe_path)
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _open_port(self) -> None:
        port, ok = QInputDialog.getInt(
            self._outer, "Open Port",
            "Port number (1-65535):", 80, 1, 65535,
        )
        if not ok:
            return

        reply = QMessageBox.question(
            self._outer, "Confirm Open Port",
            f"Allow inbound TCP traffic on port {port}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._progress.show()
        self._status_lbl.setText(f"Opening port {port}...")

        def work(_w):
            netsh_open_port(port)
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _delete_rule(self) -> None:
        name = self._get_selected_name()
        if not name:
            return

        reply = QMessageBox.warning(
            self._outer, "Delete Rule",
            f"Delete firewall rule:\n{name}?\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._progress.show()
        self._status_lbl.setText(f"Deleting rule '{name}'...")

        def work(_w):
            netsh_delete_rule(name)
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_double_click(self, item: QTableWidgetItem) -> None:
        """Toggle enabled/disabled state on double-click."""
        row = item.row()
        name_item = self._table.item(row, 0)
        if not name_item:
            return
        name = name_item.text()
        enabled_item = self._table.item(row, 1)
        current_state = enabled_item.text() if enabled_item else ""

        # Infer desired state: if currently True (enabled), disable; else enable
        new_state = current_state != "Yes"

        self._status_lbl.setText(f"Setting rule '{name}' to {'enabled' if new_state else 'disabled'}...")

        def work(_w):
            netsh_set_rule_enabled(name, new_state)
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _export_rules(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self._outer, "Export Firewall Rules",
            "rules.wfw", "Windows Firewall Rules (*.wfw)",
        )
        if not path:
            return

        self._progress.show()
        self._status_lbl.setText("Exporting rules...")

        def work(_w):
            netsh_export_rules(path)
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QMessageBox.information(
            self._outer, "Export Complete",
            f"Rules exported to:\n{path}",
        )

        def on_export_result(rules):
            self._progress.hide()
            self._status_lbl.setText(f"Rules exported successfully ({len(rules)} rules loaded).")

        worker.signals.result.connect(on_export_result)
        QThreadPool.globalInstance().start(worker)

    def _import_rules(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._outer, "Import Firewall Rules",
            "", "Windows Firewall Rules (*.wfw);;All Files (*)",
        )
        if not path:
            return

        reply = QMessageBox.question(
            self._outer, "Confirm Import",
            f"Import firewall rules from:\n{path}\n\nExisting rules with the same names will be overwritten.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._progress.show()
        self._status_lbl.setText("Importing rules...")

        def work(_w):
            netsh_import_rules(path)
            return fetch_firewall_rules()

        worker = Worker(work)
        worker.signals.result.connect(self._on_rules_loaded)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    # ------------------------------------------------------------------
    # Filtering / table population
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        search = self._search_edit.text().lower()
        dir_f = self._dir_combo.currentText()
        action_f = self._action_combo.currentText()
        profile_f = self._profile_combo.currentText()

        visible = []
        for r in self._all_rules:
            if search and search not in r.name.lower() and search not in r.program.lower():
                continue
            if dir_f != "All" and r.direction != dir_f:
                continue
            if action_f != "All" and r.action != action_f:
                continue
            if profile_f != "All" and profile_f not in r.profile:
                continue
            visible.append(r)

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(visible))
        for row, rule in enumerate(visible):
            vals = [
                rule.name, rule.enabled, rule.direction, rule.action,
                rule.protocol, rule.local_port, rule.remote_port,
                rule.program, rule.profile,
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                # Colour coding
                if rule.action == "Allow":
                    item.setForeground(QColor("#2ecc71"))
                elif rule.action == "Block":
                    item.setForeground(QColor("#e74c3c"))
                if rule.enabled == "No":
                    item.setForeground(QColor("#888888"))
                self._table.setItem(row, col, item)
        self._table.setSortingEnabled(True)

        total = len(self._all_rules)
        self._status_lbl.setText(
            f"Showing {len(visible)} / {total} rule(s)"
            + (f" (filtered)" if total != len(visible) else "")
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        has_selection = bool(self._table.selectedItems())
        self._delete_btn.setEnabled(has_selection)

    def _get_selected_name(self) -> Optional[str]:
        items = self._table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        name_item = self._table.item(row, 0)
        return name_item.text() if name_item else None

    def _set_buttons_enabled(self, enabled: bool) -> None:
        self._refresh_btn.setEnabled(enabled)
        self._block_btn.setEnabled(enabled)
        self._open_port_btn.setEnabled(enabled)
        self._export_btn.setEnabled(enabled)
        self._import_btn.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_start(self, app=None) -> None:
        self.app = app

    def on_activate(self) -> None:
        if not getattr(self, "_loaded", False):
            self._loaded = True
            self._do_refresh()

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def on_deactivate(self) -> None:
        pass
