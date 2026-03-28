# src/modules/network_diagnostics/network_module.py
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThreadPool
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QScrollArea,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QComboBox,
    QCheckBox,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QListWidget,
    QSizePolicy,
    QAbstractItemView,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.network_diagnostics import network_tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper: common port-to-service names
# ---------------------------------------------------------------------------
_WELL_KNOWN_PORTS = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    445: "SMB",
    3306: "MySQL",
    3389: "RDP",
    5900: "VNC",
    8080: "HTTP-Alt",
    8443: "HTTPS-Alt",
}


# ---------------------------------------------------------------------------
# _ToolCard — collapsible card
# ---------------------------------------------------------------------------
class _ToolCard(QFrame):
    """A collapsible card widget: header toggle button + content area."""

    def __init__(self, title: str, content: QWidget, expanded: bool = True, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        self._toggle_btn = QPushButton()
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(expanded)
        self._toggle_btn.setStyleSheet(
            "QPushButton { text-align: left; padding: 6px 10px; font-weight: bold; border: none; background: #2d2d2d; }"
            "QPushButton:hover { background: #3a3a3a; }"
        )
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        # Content
        self._content = content
        self._content.setVisible(expanded)
        layout.addWidget(self._content)

        self._set_title(title, expanded)

    def _set_title(self, title: str, expanded: bool) -> None:
        arrow = "▼" if expanded else "▶"
        self._toggle_btn.setText(f"  {arrow}  {title}")

    def _on_toggle(self, checked: bool) -> None:
        self._content.setVisible(checked)
        arrow = "▼" if checked else "▶"
        text = self._toggle_btn.text()
        # Replace arrow character at start
        import re
        new_text = re.sub(r"[▼▶]", arrow, text)
        self._toggle_btn.setText(new_text)


# ---------------------------------------------------------------------------
# Individual card builders
# ---------------------------------------------------------------------------

def _build_ping_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    # Input row
    row = QHBoxLayout()
    row.addWidget(QLabel("Host:"))
    host_edit = QLineEdit("8.8.8.8")
    host_edit.setPlaceholderText("hostname or IP")
    row.addWidget(host_edit, 1)
    row.addWidget(QLabel("Count:"))
    count_spin = QSpinBox()
    count_spin.setRange(1, 10)
    count_spin.setValue(4)
    row.addWidget(count_spin)
    ping_btn = QPushButton("Ping")
    row.addWidget(ping_btn)
    layout.addLayout(row)

    # Results
    result_box = QPlainTextEdit()
    result_box.setReadOnly(True)
    result_box.setMinimumHeight(140)
    result_box.setPlaceholderText("Ping results will appear here…")
    layout.addWidget(result_box)

    def _run_ping() -> None:
        host = host_edit.text().strip()
        if not host:
            result_box.setPlainText("Please enter a host.")
            return
        count = count_spin.value()
        ping_btn.setEnabled(False)
        result_box.setPlainText("Running ping…")

        worker = Worker(lambda _w: network_tools.ping(host, count))
        worker.signals.result.connect(lambda txt: result_box.setPlainText(txt))
        worker.signals.error.connect(lambda e: result_box.setPlainText(f"Error: {e}"))
        worker.signals.result.connect(lambda _: ping_btn.setEnabled(True))
        worker.signals.error.connect(lambda _: ping_btn.setEnabled(True))
        QThreadPool.globalInstance().start(worker)

    ping_btn.clicked.connect(_run_ping)

    card = _ToolCard("Ping", content, expanded=True)
    return card


def _build_traceroute_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    # Input row
    row = QHBoxLayout()
    row.addWidget(QLabel("Host:"))
    host_edit = QLineEdit("8.8.8.8")
    host_edit.setPlaceholderText("hostname or IP")
    row.addWidget(host_edit, 1)
    trace_btn = QPushButton("Trace")
    row.addWidget(trace_btn)
    layout.addLayout(row)

    status_label = QLabel("")
    layout.addWidget(status_label)

    # Results table
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["Hop", "IP", "Time"])
    table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setMinimumHeight(160)
    layout.addWidget(table)

    def _run_trace() -> None:
        host = host_edit.text().strip()
        if not host:
            status_label.setText("Please enter a host.")
            return
        trace_btn.setEnabled(False)
        table.setRowCount(0)
        status_label.setText("Tracing route… (this may take up to 30s)")

        worker = Worker(lambda _w: network_tools.traceroute(host))

        def _on_result(hops):
            table.setRowCount(0)
            for hop_num, ip, time_str in hops:
                row_idx = table.rowCount()
                table.insertRow(row_idx)
                table.setItem(row_idx, 0, QTableWidgetItem(str(hop_num)))
                table.setItem(row_idx, 1, QTableWidgetItem(ip))
                table.setItem(row_idx, 2, QTableWidgetItem(time_str))
            status_label.setText(f"Done — {len(hops)} hops.")
            trace_btn.setEnabled(True)

        worker.signals.result.connect(_on_result)
        worker.signals.error.connect(lambda e: (status_label.setText(f"Error: {e}"), trace_btn.setEnabled(True)))
        QThreadPool.globalInstance().start(worker)

    trace_btn.clicked.connect(_run_trace)

    return _ToolCard("Traceroute", content, expanded=False)


def _build_dns_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    row = QHBoxLayout()
    row.addWidget(QLabel("Host:"))
    host_edit = QLineEdit("example.com")
    host_edit.setPlaceholderText("hostname")
    row.addWidget(host_edit, 1)
    row.addWidget(QLabel("Type:"))
    type_combo = QComboBox()
    type_combo.addItems(["A", "AAAA", "MX", "NS", "PTR", "TXT", "ANY"])
    row.addWidget(type_combo)
    lookup_btn = QPushButton("Lookup")
    row.addWidget(lookup_btn)
    layout.addLayout(row)

    result_box = QPlainTextEdit()
    result_box.setReadOnly(True)
    result_box.setMinimumHeight(120)
    result_box.setPlaceholderText("DNS results will appear here…")
    layout.addWidget(result_box)

    def _run_dns() -> None:
        host = host_edit.text().strip()
        if not host:
            result_box.setPlainText("Please enter a host.")
            return
        rtype = type_combo.currentText()
        lookup_btn.setEnabled(False)
        result_box.setPlainText("Looking up…")

        worker = Worker(lambda _w: network_tools.dns_lookup(host, rtype))
        worker.signals.result.connect(lambda txt: result_box.setPlainText(txt))
        worker.signals.error.connect(lambda e: result_box.setPlainText(f"Error: {e}"))
        worker.signals.result.connect(lambda _: lookup_btn.setEnabled(True))
        worker.signals.error.connect(lambda _: lookup_btn.setEnabled(True))
        QThreadPool.globalInstance().start(worker)

    lookup_btn.clicked.connect(_run_dns)

    return _ToolCard("DNS Lookup", content, expanded=False)


def _build_port_scanner_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    # Row 1: host + port range
    row1 = QHBoxLayout()
    row1.addWidget(QLabel("Host:"))
    host_edit = QLineEdit("127.0.0.1")
    host_edit.setPlaceholderText("hostname or IP")
    row1.addWidget(host_edit, 1)
    row1.addWidget(QLabel("Ports:"))
    start_spin = QSpinBox()
    start_spin.setRange(1, 65535)
    start_spin.setValue(1)
    row1.addWidget(start_spin)
    row1.addWidget(QLabel("–"))
    end_spin = QSpinBox()
    end_spin.setRange(1, 65535)
    end_spin.setValue(1024)
    row1.addWidget(end_spin)
    layout.addLayout(row1)

    # Row 2: buttons + progress
    row2 = QHBoxLayout()
    scan_btn = QPushButton("Scan")
    stop_btn = QPushButton("Stop")
    stop_btn.setEnabled(False)
    row2.addWidget(scan_btn)
    row2.addWidget(stop_btn)
    progress_bar = QProgressBar()
    progress_bar.setRange(0, 100)
    progress_bar.setValue(0)
    progress_bar.setTextVisible(True)
    row2.addWidget(progress_bar, 1)
    layout.addLayout(row2)

    status_label = QLabel("")
    layout.addWidget(status_label)

    # Results table — open ports only
    table = QTableWidget(0, 3)
    table.setHorizontalHeaderLabels(["Port", "Status", "Service"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setMinimumHeight(140)
    layout.addWidget(table)

    # Cancellation flag — mutable list so lambda can write it
    _cancelled = [False]

    def _validate_range() -> bool:
        start = start_spin.value()
        end = end_spin.value()
        if end < start:
            status_label.setText("End port must be >= start port.")
            return False
        if (end - start + 1) > 10_000:
            status_label.setText("Range capped at 10,000 ports.")
            end_spin.setValue(start + 9999)
        return True

    def _run_scan() -> None:
        if not _validate_range():
            return
        host = host_edit.text().strip()
        if not host:
            status_label.setText("Please enter a host.")
            return
        start = start_spin.value()
        end = end_spin.value()
        total = end - start + 1

        _cancelled[0] = False
        table.setRowCount(0)
        progress_bar.setValue(0)
        scan_btn.setEnabled(False)
        stop_btn.setEnabled(True)
        status_label.setText(f"Scanning {total} ports…")

        # We use a simple result-based approach; progress updates happen
        # via a callback that marshals to the UI thread through a stored ref.
        # Because the callback runs in a thread pool thread we use a
        # thread-safe approach: store latest progress in a list and use
        # a QTimer to poll it from the main thread.
        _progress_state = [0, total]

        def _on_progress(scanned: int, ttl: int) -> None:
            _progress_state[0] = scanned
            _progress_state[1] = ttl

        def _worker_fn(_w):
            return network_tools.scan_ports(
                host, start, end,
                on_progress=_on_progress,
                is_cancelled=lambda: _cancelled[0],
            )

        progress_timer = QTimer()
        progress_timer.setInterval(200)

        def _update_progress() -> None:
            scanned, ttl = _progress_state
            if ttl > 0:
                pct = int(scanned * 100 / ttl)
                progress_bar.setValue(pct)

        progress_timer.timeout.connect(_update_progress)
        progress_timer.start()

        worker = Worker(_worker_fn)

        def _on_result(open_ports) -> None:
            progress_timer.stop()
            progress_bar.setValue(100)
            table.setRowCount(0)
            for port, state in open_ports:
                service = _WELL_KNOWN_PORTS.get(port, "")
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(str(port)))
                table.setItem(r, 1, QTableWidgetItem(state))
                table.setItem(r, 2, QTableWidgetItem(service))
            cancelled_msg = " (cancelled)" if _cancelled[0] else ""
            status_label.setText(f"Found {len(open_ports)} open port(s){cancelled_msg}.")
            scan_btn.setEnabled(True)
            stop_btn.setEnabled(False)

        def _on_error(e: str) -> None:
            progress_timer.stop()
            status_label.setText(f"Error: {e}")
            scan_btn.setEnabled(True)
            stop_btn.setEnabled(False)

        worker.signals.result.connect(_on_result)
        worker.signals.error.connect(_on_error)
        QThreadPool.globalInstance().start(worker)

    def _stop_scan() -> None:
        _cancelled[0] = True
        status_label.setText("Cancelling…")
        stop_btn.setEnabled(False)

    scan_btn.clicked.connect(_run_scan)
    stop_btn.clicked.connect(_stop_scan)

    return _ToolCard("Port Scanner", content, expanded=False)


def _build_connections_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    # Toolbar
    toolbar = QHBoxLayout()
    refresh_btn = QPushButton("Refresh")
    auto_cb = QCheckBox("Auto-refresh (5s)")
    toolbar.addWidget(refresh_btn)
    toolbar.addWidget(auto_cb)
    toolbar.addStretch()
    conn_count_label = QLabel("")
    toolbar.addWidget(conn_count_label)
    layout.addLayout(toolbar)

    # Table
    cols = ["Local Address", "Remote Address", "Status", "PID", "Process"]
    table = QTableWidget(0, len(cols))
    table.setHorizontalHeaderLabels(cols)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setMinimumHeight(180)
    layout.addWidget(table)

    def _populate_table(conns) -> None:
        table.setRowCount(0)
        for c in conns:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(c["local"]))
            table.setItem(r, 1, QTableWidgetItem(c["remote"]))
            table.setItem(r, 2, QTableWidgetItem(c["status"]))
            table.setItem(r, 3, QTableWidgetItem(c["pid"]))
            table.setItem(r, 4, QTableWidgetItem(c["process"]))
        conn_count_label.setText(f"{len(conns)} connection(s)")

    def _refresh() -> None:
        worker = Worker(lambda _w: network_tools.get_connections())
        worker.signals.result.connect(_populate_table)
        worker.signals.error.connect(lambda e: conn_count_label.setText(f"Error: {e}"))
        QThreadPool.globalInstance().start(worker)

    # Auto-refresh timer
    auto_timer = QTimer()
    auto_timer.setInterval(5000)
    auto_timer.timeout.connect(_refresh)

    def _toggle_auto(state) -> None:
        if auto_cb.isChecked():
            auto_timer.start()
        else:
            auto_timer.stop()

    auto_cb.stateChanged.connect(_toggle_auto)
    refresh_btn.clicked.connect(_refresh)

    # Initial load
    _refresh()

    return _ToolCard("Active Connections", content, expanded=False)


def _build_wifi_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    top_row = QHBoxLayout()
    load_btn = QPushButton("Load Profiles")
    top_row.addWidget(load_btn)
    top_row.addStretch()
    layout.addLayout(top_row)

    splitter_layout = QHBoxLayout()

    profile_list = QListWidget()
    profile_list.setMinimumHeight(140)
    profile_list.setMaximumWidth(220)
    splitter_layout.addWidget(profile_list)

    detail_box = QPlainTextEdit()
    detail_box.setReadOnly(True)
    detail_box.setPlaceholderText("Select a profile to see details…")
    splitter_layout.addWidget(detail_box, 1)

    layout.addLayout(splitter_layout)

    def _load_profiles() -> None:
        load_btn.setEnabled(False)
        profile_list.clear()
        detail_box.setPlainText("Loading…")

        worker = Worker(lambda _w: network_tools.get_wifi_profiles())

        def _on_profiles(profiles) -> None:
            profile_list.clear()
            for p in profiles:
                profile_list.addItem(p)
            detail_box.setPlainText(f"Loaded {len(profiles)} profile(s). Click one to see details.")
            load_btn.setEnabled(True)

        worker.signals.result.connect(_on_profiles)
        worker.signals.error.connect(lambda e: (detail_box.setPlainText(f"Error: {e}"), load_btn.setEnabled(True)))
        QThreadPool.globalInstance().start(worker)

    def _show_profile_detail(item) -> None:
        name = item.text()
        detail_box.setPlainText("Loading details…")
        worker = Worker(lambda _w: network_tools.get_wifi_profile_detail(name))
        worker.signals.result.connect(lambda txt: detail_box.setPlainText(txt or "(no details returned)"))
        worker.signals.error.connect(lambda e: detail_box.setPlainText(f"Error: {e}"))
        QThreadPool.globalInstance().start(worker)

    load_btn.clicked.connect(_load_profiles)
    profile_list.itemClicked.connect(_show_profile_detail)

    return _ToolCard("WiFi Profiles", content, expanded=False)


def _build_adapter_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)

    toolbar = QHBoxLayout()
    refresh_btn = QPushButton("Refresh")
    toolbar.addWidget(refresh_btn)
    toolbar.addStretch()
    layout.addLayout(toolbar)

    cols = ["Name", "IP", "MAC", "Netmask", "Gateway", "DNS", "Speed", "Up"]
    table = QTableWidget(0, len(cols))
    table.setHorizontalHeaderLabels(cols)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setMinimumHeight(140)
    layout.addWidget(table)

    def _refresh() -> None:
        refresh_btn.setEnabled(False)
        worker = Worker(lambda _w: network_tools.get_adapter_info())

        def _populate(adapters) -> None:
            table.setRowCount(0)
            for a in adapters:
                r = table.rowCount()
                table.insertRow(r)
                for col_idx, key in enumerate(cols):
                    table.setItem(r, col_idx, QTableWidgetItem(a.get(key, "")))
            refresh_btn.setEnabled(True)

        worker.signals.result.connect(_populate)
        worker.signals.error.connect(lambda e: (logger.error("Adapter info error: %s", e), refresh_btn.setEnabled(True)))
        QThreadPool.globalInstance().start(worker)

    refresh_btn.clicked.connect(_refresh)
    _refresh()

    return _ToolCard("Adapter Info", content, expanded=False)


# ---------------------------------------------------------------------------
# NetworkDiagnosticsModule
# ---------------------------------------------------------------------------
class NetworkDiagnosticsModule(BaseModule):
    name = "network_diagnostics"
    icon = "🌐"
    description = "Network diagnostic tools"
    requires_admin = False
    group = ModuleGroup.SYSTEM

    def __init__(self) -> None:
        super().__init__()
        self._widget: Optional[QWidget] = None

    # ------------------------------------------------------------------
    # BaseModule interface
    # ------------------------------------------------------------------
    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def create_widget(self) -> QWidget:
        # Outer container
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Title
        title = QLabel("Network Diagnostics")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px;")
        outer_layout.addWidget(title)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(8, 8, 8, 8)
        inner_layout.setSpacing(8)

        # Add all tool cards
        inner_layout.addWidget(_build_ping_card())
        inner_layout.addWidget(_build_traceroute_card())
        inner_layout.addWidget(_build_dns_card())
        inner_layout.addWidget(_build_port_scanner_card())
        inner_layout.addWidget(_build_connections_card())
        inner_layout.addWidget(_build_wifi_card())
        inner_layout.addWidget(_build_adapter_card())

        # Push cards to the top
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        outer_layout.addWidget(scroll, 1)

        self._widget = outer
        return outer
