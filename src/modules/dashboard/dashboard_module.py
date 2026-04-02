"""Dashboard module displaying live system metrics.

Provides real-time monitoring of:
- CPU usage (total + per-core)
- Memory usage (RAM + swap)
- Disk usage (per volume)
- Network I/O (sent/recv)
- System uptime

Refresh interval: 3 seconds (configurable)
"""

import os
import platform
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup

try:
    import psutil

    def _fmt_bytes(bytes_count: int) -> str:
        """Convert bytes to human readable string."""
        if bytes_count == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        unit_index = 0
        while bytes_count >= 1024 and unit_index < len(units) - 1:
            bytes_count /= 1024
            unit_index += 1
        return f"{bytes_count:.1f} {units[unit_index]}"

    def _fmt_percent(percent: float, name="") -> str:
        """Format percentage with optional label."""
        if name:
            return f"{name}: {percent:.1f}%"
        return f"{percent:.1f}%"

    _PSUTIL = True
except ImportError:

    def _fmt_bytes(bytes_count: int) -> str:
        return str(bytes_count)

    def _fmt_percent(percent: float, name="") -> str:
        return str(percent)

    _PSUTIL = False


# ---------------------------------------------------------------------------
# Small reusable card widget
# ---------------------------------------------------------------------------


class _Card(QFrame):
    """Reusable card widget for dashboard metrics.

    Attributes:
        title: Card title text (auto-formatted)
    """

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Raised)
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(12, 10, 12, 10)
        vbox.setSpacing(4)
        title_lbl = QLabel(title)
        font = title_lbl.font()
        font.setBold(True)
        _pt = font.pointSize()
        if _pt > 0:
            font.setPointSize(_pt - 1)
        title_lbl.setFont(font)
        title_lbl.setStyleSheet("color: gray;")
        vbox.addWidget(title_lbl)
        self._body = QVBoxLayout()
        self._body.setSpacing(6)
        vbox.addLayout(self._body)

    def body(self) -> QVBoxLayout:
        return self._body


class _StatBar(QWidget):
    """Label + progress bar + value label in one row."""

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(0, 0, 0, 0)
        self._name = QLabel(label)
        self._name.setFixedWidth(110)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setFixedHeight(14)
        self._bar.setTextVisible(False)
        self._val = QLabel("—")
        self._val.setFixedWidth(60)
        self._val.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        hbox.addWidget(self._name)
        hbox.addWidget(self._bar, stretch=1)
        hbox.addWidget(self._val)

    def update(self, pct: float, text: str) -> None:
        self._bar.setValue(int(pct))
        # Color the bar based on usage level
        if pct >= 90:
            color = "#e06c75"
        elif pct >= 70:
            color = "#e5c07b"
        else:
            color = "#98c379"
        self._bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; border-radius: 2px; }}"
        )
        self._val.setText(text)


# ---------------------------------------------------------------------------
# Dashboard widget
# ---------------------------------------------------------------------------


class _DashboardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._refresh)
        self._setup_ui()
        self._refresh()
        self._timer.start()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(12)
        grid.setContentsMargins(12, 12, 12, 12)

        # --- System Info card (row 0, col 0-1) ---
        self._sys_card = _Card("System Information")
        self._os_lbl = QLabel("—")
        self._host_lbl = QLabel("—")
        self._cpu_name_lbl = QLabel("—")
        self._uptime_lbl = QLabel("—")
        self._boot_lbl = QLabel("—")
        for lbl in (
            self._os_lbl,
            self._host_lbl,
            self._cpu_name_lbl,
            self._uptime_lbl,
            self._boot_lbl,
        ):
            lbl.setWordWrap(True)
            self._sys_card.body().addWidget(lbl)
        grid.addWidget(self._sys_card, 0, 0, 1, 2)

        # --- CPU card (row 1, col 0) ---
        self._cpu_card = _Card("CPU")
        self._cpu_total = _StatBar("Total")
        self._cpu_card.body().addWidget(self._cpu_total)
        self._cpu_per_bars: list[_StatBar] = []
        grid.addWidget(self._cpu_card, 1, 0)

        # --- Memory card (row 1, col 1) ---
        self._mem_card = _Card("Memory")
        self._ram_bar = _StatBar("RAM")
        self._swap_bar = _StatBar("Swap / Page")
        self._mem_card.body().addWidget(self._ram_bar)
        self._mem_card.body().addWidget(self._swap_bar)
        self._mem_detail = QLabel("—")
        self._mem_detail.setStyleSheet("color: gray; font-size: 11px;")
        self._mem_card.body().addWidget(self._mem_detail)
        grid.addWidget(self._mem_card, 1, 1)

        # --- Disk card (row 2, col 0-1) ---
        self._disk_card = _Card("Disk Usage")
        self._disk_bars: dict[str, _StatBar] = {}
        grid.addWidget(self._disk_card, 2, 0, 1, 2)

        # --- Network card (row 3, col 0-1) ---
        self._net_card = _Card("Network (cumulative)")
        self._net_sent = QLabel("Sent: —")
        self._net_recv = QLabel("Received: —")
        self._net_card.body().addWidget(self._net_sent)
        self._net_card.body().addWidget(self._net_recv)
        grid.addWidget(self._net_card, 3, 0, 1, 2)

        grid.setRowStretch(4, 1)
        scroll.setWidget(inner)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _refresh(self) -> None:
        if not _PSUTIL:
            return
        self._refresh_system()
        self._refresh_cpu()
        self._refresh_memory()
        self._refresh_disk()
        self._refresh_network()

    def _refresh_system(self) -> None:
        self._os_lbl.setText(
            f"OS: {platform.system()} {platform.release()} ({platform.version()[:40]})"
        )
        self._host_lbl.setText(f"Host: {platform.node()}")
        cpu = (
            platform.processor()
            or psutil.cpu_freq()
            and f"{psutil.cpu_freq().current:.0f} MHz"
        )
        self._cpu_name_lbl.setText(f"CPU: {cpu or '—'}")
        boot_ts = psutil.boot_time()
        boot_dt = datetime.fromtimestamp(boot_ts)
        uptime = datetime.now() - boot_dt
        h, rem = divmod(int(uptime.total_seconds()), 3600)
        m = rem // 60
        self._uptime_lbl.setText(f"Uptime: {h}h {m}m")
        self._boot_lbl.setText(f"Last boot: {boot_dt.strftime('%Y-%m-%d  %H:%M')}")

    def _refresh_cpu(self) -> None:
        total = psutil.cpu_percent(interval=None)
        self._cpu_total.update(total, f"{total:.1f}%")
        per = psutil.cpu_percent(percpu=True, interval=None)
        # Add per-core bars lazily
        while len(self._cpu_per_bars) < len(per):
            idx = len(self._cpu_per_bars)
            bar = _StatBar(f"Core {idx}")
            self._cpu_per_bars.append(bar)
            self._cpu_card.body().addWidget(bar)
        for i, pct in enumerate(per):
            self._cpu_per_bars[i].update(pct, f"{pct:.0f}%")

    def _refresh_memory(self) -> None:
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        self._ram_bar.update(
            vm.percent, f"{vm.percent:.0f}%  ({_fmt(vm.used)}/{_fmt(vm.total)})"
        )
        self._swap_bar.update(
            sw.percent, f"{sw.percent:.0f}%  ({_fmt(sw.used)}/{_fmt(sw.total)})"
        )
        self._mem_detail.setText(
            f"Available: {_fmt(vm.available)}   Free: {_fmt(vm.free)}"
        )

    def _refresh_disk(self) -> None:
        try:
            parts = psutil.disk_partitions(all=False)
        except Exception:
            return
        seen: set[str] = set()
        for p in parts:
            try:
                usage = psutil.disk_usage(p.mountpoint)
            except Exception:
                continue
            label = f"{p.device}  [{p.fstype}]"
            seen.add(label)
            if label not in self._disk_bars:
                bar = _StatBar(p.device[:20])
                self._disk_bars[label] = bar
                self._disk_card.body().addWidget(bar)
            self._disk_bars[label].update(
                usage.percent,
                f"{usage.percent:.0f}%  ({_fmt(usage.used)}/{_fmt(usage.total)})",
            )

    def _refresh_network(self) -> None:
        io = psutil.net_io_counters()
        self._net_sent.setText(f"Sent:       {_fmt(io.bytes_sent)}")
        self._net_recv.setText(f"Received:  {_fmt(io.bytes_recv)}")

    def stop_timer(self) -> None:
        self._timer.stop()


def _fmt(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------


class DashboardModule(BaseModule):
    name = "Dashboard"
    icon = "🏠"
    description = "Live system overview — CPU, memory, disk, network, uptime"
    requires_admin = False
    group = ModuleGroup.OVERVIEW

    def __init__(self):
        super().__init__()
        self._widget: _DashboardWidget | None = None

    def create_widget(self) -> QWidget:
        if not _PSUTIL:
            lbl = QLabel(
                "psutil is not installed.\n\n"
                "Run:  pip install psutil\n\nThen restart the application."
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setWordWrap(True)
            return lbl
        self._widget = _DashboardWidget()
        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        if self._widget:
            self._widget.stop_timer()

    def on_activate(self) -> None:
        if self._widget:
            self._widget._timer.start()

    def on_deactivate(self) -> None:
        if self._widget:
            self._widget._timer.stop()

    def get_status_info(self) -> str:
        return "Dashboard"
