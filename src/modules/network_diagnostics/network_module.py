# src/modules/network_diagnostics/network_module.py
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, QThreadPool
from PyQt6 import sip
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
    QStackedWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.network_diagnostics import network_tools

logger = logging.getLogger(__name__)

_widget_valid = lambda w: not sip.isdeleted(w)

# Module-level registry of canceller functions for network tool workers
_worker_cancellers: list = []

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
        self._worker: Optional[Worker] = None

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
    card: Optional[_ToolCard] = None  # defined early so closures can capture it

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
        nonlocal card
        host = host_edit.text().strip()
        if not host:
            result_box.setPlainText("Please enter a host.")
            return
        count = count_spin.value()
        ping_btn.setEnabled(False)
        result_box.setPlainText("Running ping…")
        worker = Worker(lambda _w: network_tools.ping(host, count))
        card._worker = worker
        worker.signals.result.connect(lambda txt: result_box.setPlainText(txt) if _widget_valid(result_box) else None)
        worker.signals.error.connect(lambda e: result_box.setPlainText(f"Error: {e}") if _widget_valid(result_box) else None)
        worker.signals.result.connect(lambda _: ping_btn.setEnabled(True) if _widget_valid(ping_btn) else None)
        worker.signals.error.connect(lambda _: ping_btn.setEnabled(True) if _widget_valid(ping_btn) else None)
        _worker_cancellers.append(lambda: card._worker.cancel() if card._worker else None)
        QThreadPool.globalInstance().start(worker)

    ping_btn.clicked.connect(_run_ping)

    card = _ToolCard("Ping", content, expanded=True)
    return card


def _build_traceroute_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)
    card: Optional[_ToolCard] = None  # defined early so closures can capture it

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
        nonlocal card
        host = host_edit.text().strip()
        if not host:
            status_label.setText("Please enter a host.")
            return
        trace_btn.setEnabled(False)
        table.setRowCount(0)
        status_label.setText("Tracing route… (this may take up to 30s)")

        card._worker = Worker(lambda _w: network_tools.traceroute(host))

        def _on_result(hops):
            if not _widget_valid(table): return
            table.setRowCount(0)
            for hop_num, ip, time_str in hops:
                row_idx = table.rowCount()
                table.insertRow(row_idx)
                table.setItem(row_idx, 0, QTableWidgetItem(str(hop_num)))
                table.setItem(row_idx, 1, QTableWidgetItem(ip))
                table.setItem(row_idx, 2, QTableWidgetItem(time_str))
            if _widget_valid(status_label):
                status_label.setText(f"Done — {len(hops)} hops.")
            if _widget_valid(trace_btn):
                trace_btn.setEnabled(True)

        card._worker.signals.result.connect(_on_result)
        card._worker.signals.error.connect(lambda e: (status_label.setText(f"Error: {e}") if _widget_valid(status_label) else None, trace_btn.setEnabled(True) if _widget_valid(trace_btn) else None))
        _worker_cancellers.append(lambda: card._worker.cancel() if card._worker else None)
        QThreadPool.globalInstance().start(card._worker)

    trace_btn.clicked.connect(_run_trace)

    card = _ToolCard("Traceroute", content, expanded=False)
    return card


def _build_dns_card() -> _ToolCard:
    content = QWidget()
    layout = QVBoxLayout(content)
    layout.setContentsMargins(8, 8, 8, 8)
    card: Optional[_ToolCard] = None

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
        nonlocal card
        host = host_edit.text().strip()
        if not host:
            result_box.setPlainText("Please enter a host.")
            return
        rtype = type_combo.currentText()
        lookup_btn.setEnabled(False)
        result_box.setPlainText("Looking up…")

        card._worker = Worker(lambda _w: network_tools.dns_lookup(host, rtype))
        card._worker.signals.result.connect(lambda txt: result_box.setPlainText(txt) if _widget_valid(result_box) else None)
        card._worker.signals.error.connect(lambda e: result_box.setPlainText(f"Error: {e}") if _widget_valid(result_box) else None)
        card._worker.signals.result.connect(lambda _: lookup_btn.setEnabled(True) if _widget_valid(lookup_btn) else None)
        card._worker.signals.error.connect(lambda _: lookup_btn.setEnabled(True) if _widget_valid(lookup_btn) else None)
        _worker_cancellers.append(lambda: card._worker.cancel() if card._worker else None)
        QThreadPool.globalInstance().start(card._worker)

    lookup_btn.clicked.connect(_run_dns)

    card = _ToolCard("DNS Lookup", content, expanded=False)
    return card


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

    # Empty state overlay for table
    table_stack = QStackedWidget()
    table_stack.addWidget(table)
    empty_label = QLabel("No open ports found")
    empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_label.setStyleSheet("color: #888; font-size: 13px;")
    empty_label.setMinimumHeight(140)
    table_stack.addWidget(empty_label)
    layout.addWidget(table_stack)

    # Cancellation flag — mutable list so lambda can write it
    _cancelled = [False]
    progress_timer: Optional[QTimer] = None

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
        nonlocal progress_timer
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
        table_stack.setCurrentIndex(0)
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
        card._progress_timer = progress_timer

        worker = Worker(_worker_fn)

        def _on_result(open_ports) -> None:
            if not _widget_valid(table): return
            progress_timer.stop()
            if _widget_valid(progress_bar):
                progress_bar.setValue(100)
            table.setRowCount(0)
            for port, state in open_ports:
                service = _WELL_KNOWN_PORTS.get(port, "")
                r = table.rowCount()
                table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(str(port)))
                table.setItem(r, 1, QTableWidgetItem(state))
                table.setItem(r, 2, QTableWidgetItem(service))
            if _widget_valid(table_stack):
                table_stack.setCurrentIndex(0 if open_ports else 1)
            cancelled_msg = " (cancelled)" if _cancelled[0] else ""
            if _widget_valid(status_label):
                status_label.setText(f"Found {len(open_ports)} open port(s){cancelled_msg}.")
            if _widget_valid(scan_btn):
                scan_btn.setEnabled(True)
            if _widget_valid(stop_btn):
                stop_btn.setEnabled(False)

        def _on_error(e: str) -> None:
            progress_timer.stop()
            if _widget_valid(status_label):
                status_label.setText(f"Error: {e}")
            if _widget_valid(scan_btn):
                scan_btn.setEnabled(True)
            if _widget_valid(stop_btn):
                stop_btn.setEnabled(False)

        worker.signals.result.connect(_on_result)
        worker.signals.error.connect(_on_error)
        QThreadPool.globalInstance().start(worker)

    def _stop_scan() -> None:
        nonlocal progress_timer
        _cancelled[0] = True
        if progress_timer is not None:
            progress_timer.stop()
        status_label.setText("Cancelling…")
        stop_btn.setEnabled(False)

    scan_btn.clicked.connect(_run_scan)
    stop_btn.clicked.connect(_stop_scan)

    card = _ToolCard("Port Scanner", content, expanded=False)
    return card


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
        if not _widget_valid(table): return
        table.setRowCount(0)
        for c in conns:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(c["local"]))
            table.setItem(r, 1, QTableWidgetItem(c["remote"]))
            table.setItem(r, 2, QTableWidgetItem(c["status"]))
            table.setItem(r, 3, QTableWidgetItem(c["pid"]))
            table.setItem(r, 4, QTableWidgetItem(c["process"]))
        if _widget_valid(conn_count_label):
            conn_count_label.setText(f"{len(conns)} connection(s)")

    def _refresh() -> None:
        worker = Worker(lambda _w: network_tools.get_connections())
        worker.signals.result.connect(_populate_table)
        worker.signals.error.connect(lambda e: conn_count_label.setText(f"Error: {e}") if _widget_valid(conn_count_label) else None)
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

    card = _ToolCard("Active Connections", content, expanded=False)
    card._auto_timer = auto_timer
    return card


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
            if not _widget_valid(table): return
            table.setRowCount(0)
            for a in adapters:
                r = table.rowCount()
                table.insertRow(r)
                for col_idx, key in enumerate(cols):
                    table.setItem(r, col_idx, QTableWidgetItem(a.get(key, "")))
            if _widget_valid(refresh_btn):
                refresh_btn.setEnabled(True)

        worker.signals.result.connect(_populate)
        worker.signals.error.connect(lambda e: (logger.error("Adapter info error: %s", e), refresh_btn.setEnabled(True) if _widget_valid(refresh_btn) else None))
        QThreadPool.globalInstance().start(worker)

    refresh_btn.clicked.connect(_refresh)
    _refresh()

    return _ToolCard("Adapter Info", content, expanded=False)


# ---------------------------------------------------------------------------
# NetworkDiagnosticsModule
# ---------------------------------------------------------------------------
class NetworkDiagnosticsModule(BaseModule):
    name = "Network Diagnostics"
    icon = "🌐"
    description = "Network diagnostic tools"
    requires_admin = False
    group = ModuleGroup.SYSTEM

    def __init__(self) -> None:
        global _worker_cancellers
        super().__init__()
        _worker_cancellers.clear()
        self._widget: Optional[QWidget] = None

    # ------------------------------------------------------------------
    # BaseModule interface
    # ------------------------------------------------------------------
    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self._cancel_all_cards()
        self.cancel_all_workers()

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        self._cancel_all_cards()

    def get_refresh_interval(self) -> int:
        return 15_000

    def refresh_data(self) -> None:
        # Refresh the connections card if present
        if not hasattr(self, "_cards"):
            return
        for card in self._cards:
            if card is not None and hasattr(card, "_auto_timer"):
                card._auto_timer.stop()
                card._auto_timer.start()

    def _cancel_all_cards(self) -> None:
        global _worker_cancellers
        if not hasattr(self, "_cards"):
            return
        _worker_cancellers.clear()
        for card in self._cards:
            if card is None:
                continue
            if hasattr(card, "_worker") and card._worker is not None:
                card._worker.cancel()
            if hasattr(card, "_auto_timer") and card._auto_timer is not None:
                card._auto_timer.stop()
            if hasattr(card, "_progress_timer") and card._progress_timer is not None:
                card._progress_timer.stop()

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
        cards: list = []
        cards.append(_build_ping_card())
        cards.append(_build_traceroute_card())
        cards.append(_build_dns_card())
        cards.append(_build_port_scanner_card())
        cards.append(_build_connections_card())
        cards.append(_build_wifi_card())
        cards.append(_build_adapter_card())
        for c in cards:
            inner_layout.addWidget(c)

        # Push cards to the top
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        outer_layout.addWidget(scroll, 1)

        self._cards = cards
        self._widget = outer
        return outer
