import logging
logger = logging.getLogger(__name__)

import os, datetime, subprocess, winreg
import psutil
from typing import List, Tuple, Optional

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QHeaderView, QLabel,
    QLineEdit, QComboBox, QCheckBox, QPlainTextEdit, QSizePolicy, QGridLayout)
from PyQt6.QtCore import Qt

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker

CREATE_NO_WINDOW = 0x08000000
HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
DNS_PRESETS = {
    "Google": ("8.8.8.8", "8.8.4.4"),
    "Cloudflare": ("1.1.1.1", "1.0.0.1"),
    "Quad9": ("9.9.9.9", "149.112.112.112"),
    "OpenDNS": ("208.67.222.222", "208.67.220.220"),
    "Custom": ("", ""),
}


def _backup_file(src_path: str) -> str:
    backup_dir = os.path.join(os.environ.get("APPDATA", ""), "WindowsTweaker", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = os.path.basename(src_path)
    dest = os.path.join(backup_dir, f"{os.path.splitext(name)[0]}_{ts}{os.path.splitext(name)[1]}.bak")
    import shutil
    shutil.copy2(src_path, dest)
    return dest


def parse_hosts() -> List[Tuple[str, str, str]]:
    """Returns list of (ip, hostname, comment). Comment-only lines: ("", "", comment_text)."""
    rows = []
    try:
        with open(HOSTS_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n\r")
                if line.strip().startswith("#") or not line.strip():
                    rows.append(("", "", line.lstrip("# ").strip()))
                else:
                    parts = line.split("#", 1)
                    comment = parts[1].strip() if len(parts) > 1 else ""
                    tokens = parts[0].split()
                    if len(tokens) >= 2:
                        rows.append((tokens[0], tokens[1], comment))
    except Exception:
        pass
    return rows


def save_hosts(rows: List[Tuple[str, str, str]]):
    _backup_file(HOSTS_PATH)
    lines = []
    for ip, hostname, comment in rows:
        if not ip and not hostname:
            lines.append(f"# {comment}" if comment else "")
        elif comment:
            lines.append(f"{ip}\t{hostname}\t# {comment}")
        else:
            lines.append(f"{ip}\t{hostname}")
    with open(HOSTS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_cmd_stream(cmd: List[str], output_cb) -> int:
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace",
                                 creationflags=CREATE_NO_WINDOW)
        for line in proc.stdout:
            output_cb(line.rstrip())
        proc.wait()
        return proc.returncode
    except Exception as e:
        output_cb(f"Error: {e}")
        return -1


class NetExtrasModule(BaseModule):
    name = "Network Extras"
    icon = "🔌"
    description = "HOSTS editor, DNS switcher, proxy, quick network actions"
    requires_admin = True
    group = ModuleGroup.TOOLS

    def __init__(self):
        super().__init__()
        self._workers: list = []

    def create_widget(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._make_hosts_tab(), "HOSTS Editor")
        tabs.addTab(self._make_dns_tab(), "DNS Switcher")
        tabs.addTab(self._make_proxy_tab(), "Proxy Settings")
        tabs.addTab(self._make_quick_tab(), "Quick Actions")
        return tabs

    def _make_hosts_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        toolbar = QHBoxLayout()
        load_btn = QPushButton("Load")
        add_btn = QPushButton("Add Row")
        del_btn = QPushButton("Delete Row")
        save_btn = QPushButton("Save")
        status = QLabel("Click Load.")
        toolbar.addWidget(load_btn)
        toolbar.addWidget(add_btn)
        toolbar.addWidget(del_btn)
        toolbar.addWidget(save_btn)
        toolbar.addStretch()
        toolbar.addWidget(status)
        layout.addLayout(toolbar)

        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["IP", "Hostname", "Comment"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table, 1)

        def load():
            rows = parse_hosts()
            table.setRowCount(len(rows))
            for r, (ip, hostname, comment) in enumerate(rows):
                table.setItem(r, 0, QTableWidgetItem(ip))
                table.setItem(r, 1, QTableWidgetItem(hostname))
                table.setItem(r, 2, QTableWidgetItem(comment))
            status.setText(f"{len(rows)} entries.")

        def add_row():
            r = table.rowCount()
            table.insertRow(r)

        def del_row():
            rows = {i.row() for i in table.selectedIndexes()}
            for r in sorted(rows, reverse=True):
                table.removeRow(r)

        def save():
            rows = []
            for r in range(table.rowCount()):
                ip = (table.item(r, 0) or QTableWidgetItem("")).text()
                host = (table.item(r, 1) or QTableWidgetItem("")).text()
                comment = (table.item(r, 2) or QTableWidgetItem("")).text()
                rows.append((ip, host, comment))
            try:
                save_hosts(rows)
                status.setText("Saved.")
            except Exception as e:
                status.setText(f"Error: {e}")

        load_btn.clicked.connect(load)
        add_btn.clicked.connect(add_row)
        del_btn.clicked.connect(del_row)
        save_btn.clicked.connect(save)
        return w

    def _make_dns_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        form = QHBoxLayout()
        adapter_combo = QComboBox()
        preset_combo = QComboBox()
        primary_edit = QLineEdit()
        secondary_edit = QLineEdit()
        apply_btn = QPushButton("Apply DNS")
        dhcp_btn = QPushButton("Restore DHCP")
        status = QLabel("")

        # Populate adapters
        try:
            stats = psutil.net_if_stats()
            for name, st in stats.items():
                if st.isup:
                    adapter_combo.addItem(name)
        except Exception:
            pass

        # Populate presets
        for name in DNS_PRESETS:
            preset_combo.addItem(name)

        def on_preset_changed(text):
            if text in DNS_PRESETS:
                p, s = DNS_PRESETS[text]
                primary_edit.setText(p)
                secondary_edit.setText(s)
                primary_edit.setReadOnly(text != "Custom")
                secondary_edit.setReadOnly(text != "Custom")

        preset_combo.currentTextChanged.connect(on_preset_changed)
        on_preset_changed(preset_combo.currentText())

        form.addWidget(QLabel("Adapter:"))
        form.addWidget(adapter_combo)
        form.addWidget(QLabel("Preset:"))
        form.addWidget(preset_combo)
        form.addWidget(QLabel("Primary:"))
        form.addWidget(primary_edit)
        form.addWidget(QLabel("Secondary:"))
        form.addWidget(secondary_edit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(dhcp_btn)
        btn_row.addStretch()
        btn_row.addWidget(status)
        layout.addLayout(btn_row)
        layout.addStretch()

        def apply_dns():
            adapter = adapter_combo.currentText()
            primary = primary_edit.text().strip()
            secondary = secondary_edit.text().strip()
            if not adapter or not primary:
                status.setText("Select adapter and enter DNS.")
                return
            try:
                subprocess.run(["netsh", "interface", "ip", "set", "dns",
                                adapter, "static", primary],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                if secondary:
                    subprocess.run(["netsh", "interface", "ip", "add", "dns",
                                    adapter, secondary, "index=2"],
                                   capture_output=True, creationflags=CREATE_NO_WINDOW)
                status.setText(f"DNS set for {adapter}.")
            except Exception as e:
                status.setText(f"Error: {e}")

        def restore_dhcp():
            adapter = adapter_combo.currentText()
            try:
                subprocess.run(["netsh", "interface", "ip", "set", "dns",
                                adapter, "dhcp"],
                               capture_output=True, creationflags=CREATE_NO_WINDOW)
                status.setText(f"DHCP restored for {adapter}.")
            except Exception as e:
                status.setText(f"Error: {e}")

        apply_btn.clicked.connect(apply_dns)
        dhcp_btn.clicked.connect(restore_dhcp)
        return w

    def _make_proxy_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        PROXY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

        enable_cb = QCheckBox("Enable Proxy")
        server_edit = QLineEdit()
        server_edit.setPlaceholderText("host:port")
        override_edit = QLineEdit()
        override_edit.setPlaceholderText("e.g. localhost;127.*;*.local")
        load_btn = QPushButton("Load")
        save_btn = QPushButton("Save")
        status = QLabel("")

        layout.addWidget(enable_cb)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Proxy Server:"))
        row1.addWidget(server_edit, 1)
        layout.addLayout(row1)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Bypass (override):"))
        row2.addWidget(override_edit, 1)
        layout.addLayout(row2)
        btn_row = QHBoxLayout()
        btn_row.addWidget(load_btn)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        btn_row.addWidget(status)
        layout.addLayout(btn_row)
        layout.addStretch()

        def load():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_KEY) as k:
                    def rv(name, default=""):
                        try: return winreg.QueryValueEx(k, name)[0]
                        except Exception: return default
                    enable_cb.setChecked(bool(rv("ProxyEnable", 0)))
                    server_edit.setText(str(rv("ProxyServer", "")))
                    override_edit.setText(str(rv("ProxyOverride", "")))
                status.setText("Loaded.")
            except Exception as e:
                status.setText(f"Error: {e}")

        def save():
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PROXY_KEY,
                                    0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, "ProxyEnable", 0, winreg.REG_DWORD, int(enable_cb.isChecked()))
                    winreg.SetValueEx(k, "ProxyServer", 0, winreg.REG_SZ, server_edit.text())
                    winreg.SetValueEx(k, "ProxyOverride", 0, winreg.REG_SZ, override_edit.text())
                status.setText("Saved.")
            except Exception as e:
                status.setText(f"Error: {e}")

        load_btn.clicked.connect(load)
        save_btn.clicked.connect(save)
        return w

    def _make_quick_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        log = QPlainTextEdit()
        log.setReadOnly(True)

        grid = QGridLayout()
        actions = [
            ("Flush DNS", ["ipconfig", "/flushdns"]),
            ("Reset Winsock", ["netsh", "winsock", "reset"]),
            ("IP Release", ["ipconfig", "/release"]),
            ("IP Renew", ["ipconfig", "/renew"]),
            ("Reset TCP/IP", ["netsh", "int", "ip", "reset"]),
        ]
        for i, (label, cmd) in enumerate(actions):
            btn = QPushButton(label)
            btn_cmd = cmd[:]  # capture
            btn.clicked.connect(lambda _, c=btn_cmd: _run_action(c))
            grid.addWidget(btn, i // 3, i % 3)

        def _run_action(cmd):
            log.appendPlainText(f"\n> {' '.join(cmd)}")
            worker = Worker(lambda _w: run_cmd_stream(cmd, lambda l: log.appendPlainText(l)))
            worker.signals.result.connect(lambda _: log.appendPlainText("Done."))
            worker.signals.error.connect(lambda e: log.appendPlainText(f"Error: {e}"))
            self._workers.append(worker)
            self.thread_pool.start(worker)

        layout.addLayout(grid)
        layout.addWidget(log, 1)
        return w

    def on_start(self, app=None): pass
    def on_stop(self) -> None:
        self.cancel_all_workers()
    def on_activate(self): pass
    def on_deactivate(self) -> None:
        self.cancel_all_workers()
