import re
import subprocess
from typing import List, Dict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QProgressBar, QTabWidget,
    QFrame,
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker

CREATE_NO_WINDOW = 0x08000000

_NET_COLS = ["SSID", "Signal %", "Channel", "Band", "Security", "Authentication", "BSSID"]
_IFACE_COLS = ["Property", "Value"]


def _run_netsh(*args) -> str:
    result = subprocess.run(
        ["netsh", "wlan"] + list(args),
        capture_output=True, text=True, errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    return result.stdout


def _channel_to_band(ch: str) -> str:
    try:
        n = int(ch)
        return "2.4 GHz" if n <= 14 else "5 GHz"
    except ValueError:
        return ""


def parse_networks() -> List[Dict]:
    """Parse 'netsh wlan show networks mode=bssid' output into a list of dicts."""
    output = _run_netsh("show", "networks", "mode=bssid")
    networks: List[Dict] = []
    current_net: Dict = {}
    current_bssid: Dict = {}

    def _flush_bssid():
        if current_bssid and current_net:
            entry = dict(current_net)
            entry.update(current_bssid)
            ch = entry.get("Channel", "")
            entry["Band"] = _channel_to_band(ch)
            networks.append(entry)

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        # New SSID block
        m = re.match(r"SSID\s+\d+\s*:\s*(.*)", line)
        if m:
            _flush_bssid()
            current_bssid = {}
            current_net = {"SSID": m.group(1).strip()}
            continue

        # SSID-level fields
        m = re.match(r"Authentication\s*:\s*(.*)", line)
        if m and current_net and "BSSID" not in current_bssid:
            current_net["Authentication"] = m.group(1).strip()
            continue
        m = re.match(r"Encryption\s*:\s*(.*)", line)
        if m and current_net and "BSSID" not in current_bssid:
            current_net["Security"] = m.group(1).strip()
            continue

        # BSSID line — start a new BSSID entry
        m = re.match(r"BSSID\s+\d+\s*:\s*(.*)", line)
        if m:
            _flush_bssid()
            current_bssid = {"BSSID": m.group(1).strip()}
            continue

        # BSSID-level fields
        m = re.match(r"Signal\s*:\s*(\d+)%", line)
        if m:
            current_bssid["Signal %"] = int(m.group(1))
            continue
        m = re.match(r"Channel\s*:\s*(\d+)", line)
        if m:
            current_bssid["Channel"] = m.group(1)
            continue

    _flush_bssid()
    return sorted(networks, key=lambda n: n.get("Signal %", 0), reverse=True)


def parse_interfaces() -> List[Dict]:
    """Parse 'netsh wlan show interfaces' for current connection details."""
    output = _run_netsh("show", "interfaces")
    interfaces = []
    current: Dict = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            if current:
                interfaces.append(current)
                current = {}
            continue
        if ":" in line:
            key, _, val = line.partition(":")
            current[key.strip()] = val.strip()
    if current:
        interfaces.append(current)
    return interfaces


def build_channel_map(networks: List[Dict]) -> Dict[str, Dict[int, int]]:
    """Return {band: {channel: count}} for channel congestion display."""
    result = {"2.4 GHz": {}, "5 GHz": {}}
    for n in networks:
        band = n.get("Band", "")
        ch_str = n.get("Channel", "")
        if band in result and ch_str:
            try:
                ch = int(ch_str)
                result[band][ch] = result[band].get(ch, 0) + 1
            except ValueError:
                pass
    return result


def _scan_all() -> Dict:
    networks = parse_networks()
    interfaces = parse_interfaces()
    channel_map = build_channel_map(networks)
    return {"networks": networks, "interfaces": interfaces, "channel_map": channel_map}


def _make_table(cols) -> QTableWidget:
    t = QTableWidget(0, len(cols))
    t.setHorizontalHeaderLabels(cols)
    t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for i in range(1, len(cols)):
        t.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    return t


class WifiAnalyzerModule(BaseModule):
    name = "Wi-Fi Analyzer"
    icon = "📶"
    description = "Visible Wi-Fi networks, signal strength, and channel congestion"
    requires_admin = False
    group = ModuleGroup.TOOLS

    def create_widget(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(8, 8, 8, 8)

        toolbar = QHBoxLayout()
        self._scan_btn = QPushButton("Scan")
        self._status_label = QLabel("Click Scan to discover networks.")
        toolbar.addWidget(self._scan_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status_label)
        layout.addLayout(toolbar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        # Networks tab
        self._net_table = _make_table(_NET_COLS)
        tabs.addTab(self._net_table, "Networks")

        # Current connection tab
        self._iface_table = _make_table(_IFACE_COLS)
        tabs.addTab(self._iface_table, "Current Connection")

        # Channel map tab
        self._channel_widget = QWidget()
        ch_layout = QVBoxLayout(self._channel_widget)
        self._ch_label_24 = QLabel()
        self._ch_label_24.setWordWrap(True)
        self._ch_label_5 = QLabel()
        self._ch_label_5.setWordWrap(True)
        ch_layout.addWidget(QLabel("2.4 GHz channels (1–14):"))
        ch_layout.addWidget(self._ch_label_24)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        ch_layout.addWidget(sep)
        ch_layout.addWidget(QLabel("5 GHz channels:"))
        ch_layout.addWidget(self._ch_label_5)
        ch_layout.addStretch()
        tabs.addTab(self._channel_widget, "Channel Map")

        self._scan_btn.clicked.connect(self._do_scan)
        self._wifi_tabs = tabs
        return outer

    def _do_scan(self):
        self._scan_btn.setEnabled(False)
        self._status_label.setText("Scanning...")
        self._progress.show()
        worker = Worker(lambda _w: _scan_all())
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_result(self, data: Dict):
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        networks = data["networks"]
        interfaces = data["interfaces"]
        channel_map = data["channel_map"]

        # Networks table
        self._net_table.setRowCount(len(networks))
        for r, net in enumerate(networks):
            sig = net.get("Signal %", 0)
            color = QColor("#2ecc71") if sig >= 70 else QColor("#f39c12") if sig >= 40 else QColor("#e74c3c")
            for c, col in enumerate(_NET_COLS):
                val = str(net.get(col, ""))
                item = QTableWidgetItem(val)
                if col == "Signal %":
                    item.setForeground(color)
                self._net_table.setItem(r, c, item)

        # Current connection
        iface_rows = []
        for iface in interfaces:
            for k, v in iface.items():
                iface_rows.append((k, v))
        self._iface_table.setRowCount(len(iface_rows))
        for r, (k, v) in enumerate(iface_rows):
            self._iface_table.setItem(r, 0, QTableWidgetItem(k))
            self._iface_table.setItem(r, 1, QTableWidgetItem(v))

        # Channel map
        def _fmt_band(band_map: Dict[int, int]) -> str:
            if not band_map:
                return "No networks detected."
            parts = [f"Ch {ch}: {'█' * count} ({count})" for ch, count in sorted(band_map.items())]
            return "\n".join(parts)

        self._ch_label_24.setText(_fmt_band(channel_map.get("2.4 GHz", {})))
        self._ch_label_5.setText(_fmt_band(channel_map.get("5 GHz", {})))

        self._status_label.setText(f"{len(networks)} network(s) found.")

    def _on_error(self, err: str):
        self._scan_btn.setEnabled(True)
        self._progress.hide()
        self._status_label.setText(f"Error: {err}")

    def on_activate(self):
        if not getattr(self, "_loaded", False):
            self._loaded = True
            self._do_scan()

    def on_start(self, app): self.app = app
    def on_stop(self): self.cancel_all_workers()
    def on_deactivate(self): pass
