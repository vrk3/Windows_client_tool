import logging
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QLabel, QVBoxLayout, QWidget, QHBoxLayout,
    QTabWidget, QGridLayout, QProgressBar, QTableWidget, QTableWidgetItem,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider
from core.types import LogEntry
from modules.perfmon.perfmon_collector import PerfMonStore, collect_snapshot
from modules.perfmon.perfmon_charts import PerfMonDashboard
from modules.perfmon.perfmon_alerts import AlertRule
from modules.perfmon.perfmon_search_provider import PerfMonSearchProvider

logger = logging.getLogger(__name__)

DEFAULT_ALERTS = [
    AlertRule(counter="cpu_total", operator=">", threshold=90, duration_sec=300),
    AlertRule(counter="memory_percent", operator=">", threshold=85, duration_sec=60),
]


class PerfMonModule(BaseModule):
    name = "PerfMon"
    icon = "📈"
    description = "Real-time performance monitoring with historical graphs and alerts"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._dashboard: Optional[PerfMonDashboard] = None
        self._timer: Optional[QTimer] = None
        self._store: Optional[PerfMonStore] = None
        self._alerts: list = list(DEFAULT_ALERTS)
        self._search_provider = PerfMonSearchProvider()
        self._summary_label: Optional[QLabel] = None
        self._prev_net_sent: float = 0
        self._prev_net_recv: float = 0
        self._store_counter: int = 0

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3c3c3c; border-radius: 4px; background: #252525; }
            QTabBar::tab { background: #2d2d2d; color: #b0b0b0; padding: 6px 12px; margin-right: 2px; border: 1px solid #3c3c3c; border-bottom: none; border-radius: 4px 4px 0 0; }
            QTabBar::tab:selected { background: #252525; color: #e0e0e0; font-weight: bold; }
            QTabBar::tab:hover { background: #3c3c3c; }
        """)

        # --- Dashboard tab (existing charts view) ---
        dash_widget = QWidget()
        dash_layout = QVBoxLayout(dash_widget)
        dash_layout.setContentsMargins(4, 4, 4, 4)

        self._summary_label = QLabel("Collecting data...")
        self._summary_label.setStyleSheet("font-size: 13px; padding: 4px;")
        dash_layout.addWidget(self._summary_label)

        self._dashboard = PerfMonDashboard()
        dash_layout.addWidget(self._dashboard)

        self._tabs.addTab(dash_widget, "Charts")

        # --- Live Monitor tab ---
        live_widget = QWidget()
        live_layout = QGridLayout(live_widget)
        live_layout.setSpacing(10)
        live_layout.setContentsMargins(10, 10, 10, 10)

        bar_style = """
            QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; background: #2d2d2d; color: #e0e0e0; }
            QProgressBar::chunk { border-radius: 3px; }
        """

        # CPU bar
        cpu_label = QLabel("CPU Usage")
        cpu_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        self._cpu_bar = QProgressBar()
        self._cpu_bar.setRange(0, 100)
        self._cpu_bar.setFormat("%p%")
        self._cpu_bar.setStyleSheet(bar_style)

        # Memory bar
        mem_label = QLabel("Memory Usage")
        mem_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        self._mem_bar = QProgressBar()
        self._mem_bar.setRange(0, 100)
        self._mem_bar.setFormat("%p%")
        self._mem_bar.setStyleSheet(bar_style)

        # Disk I/O bar
        disk_label = QLabel("Disk I/O")
        disk_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        self._disk_bar = QProgressBar()
        self._disk_bar.setRange(0, 100)
        self._disk_bar.setFormat("0 MB/s")
        self._disk_bar.setStyleSheet(bar_style)

        # Network I/O bar
        net_label = QLabel("Network I/O")
        net_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        self._net_bar = QProgressBar()
        self._net_bar.setRange(0, 100)
        self._net_bar.setFormat("0 KB/s")
        self._net_bar.setStyleSheet(bar_style)

        # Place bars in 2x2 grid
        live_layout.addWidget(cpu_label, 0, 0)
        live_layout.addWidget(self._cpu_bar, 1, 0)
        live_layout.addWidget(mem_label, 0, 1)
        live_layout.addWidget(self._mem_bar, 1, 1)
        live_layout.addWidget(disk_label, 2, 0)
        live_layout.addWidget(self._disk_bar, 3, 0)
        live_layout.addWidget(net_label, 2, 1)
        live_layout.addWidget(self._net_bar, 3, 1)

        # Top processes table
        proc_label = QLabel("Top Processes by CPU")
        proc_label.setStyleSheet("font-weight: bold; color: #e0e0e0;")
        live_layout.addWidget(proc_label, 4, 0, 1, 2)

        self._proc_table = QTableWidget()
        self._proc_table.setColumnCount(3)
        self._proc_table.setHorizontalHeaderLabels(["Process", "CPU %", "Memory MB"])
        self._proc_table.setRowCount(10)
        self._proc_table.setColumnWidth(0, 200)
        self._proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._proc_table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0; border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 2px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0; padding: 4px; border: none; }
        """)
        live_layout.addWidget(self._proc_table, 5, 0, 1, 2)

        self._tabs.addTab(live_widget, "Live Monitor")

        # Live monitor state
        self._live_timer = QTimer()
        self._live_timer.timeout.connect(self._update_live_monitor)
        self._live_prev_disk = None
        self._live_prev_net = None

        layout.addWidget(self._tabs)
        return self._widget

    def on_start(self, app) -> None:
        self.app = app
        # Initialize SQLite store
        app_data = getattr(app, "_app_data_dir", ".")
        db_path = os.path.join(app_data, "perfmon.db")
        try:
            self._store = PerfMonStore(db_path)
            self._store.cleanup_old(days=7)
        except Exception as e:
            logger.error("Failed to init PerfMon store: %s", e)

        # Load alert config
        if app.config:
            alert_configs = app.config.get("modules.perfmon.alerts", None)
            if alert_configs and isinstance(alert_configs, list):
                self._alerts = []
                for ac in alert_configs:
                    self._alerts.append(AlertRule(
                        counter=ac.get("counter", "cpu_total"),
                        operator=ac.get("operator", ">"),
                        threshold=ac.get("threshold", 90),
                        duration_sec=ac.get("duration_sec", 300),
                        enabled=ac.get("enabled", True),
                    ))

    def on_activate(self) -> None:
        # Start live monitor timer (every 2 seconds)
        if hasattr(self, '_live_timer'):
            self._live_timer.start(2000)

        if self._timer is None:
            # Seed cpu_percent so first real reading isn't 0
            import psutil
            psutil.cpu_percent(interval=None)

            self._timer = QTimer()
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    def on_deactivate(self) -> None:
        if hasattr(self, '_live_timer') and self._live_timer is not None:
            self._live_timer.stop()
            self._live_timer.deleteLater()
            self._live_timer = None

        if self._timer:
            self._timer.stop()
            self._timer.deleteLater()
            self._timer = None

    def on_stop(self) -> None:
        if hasattr(self, '_live_timer') and self._live_timer is not None:
            self._live_timer.stop()
            self._live_timer.deleteLater()
            self._live_timer = None
        if self._timer:
            self._timer.stop()
            self._timer = None
        if self._store:
            self._store.close()
        self.cancel_all_workers()

    def get_toolbar_actions(self) -> list:
        actions = []
        reset = QAction("Reset Charts", None)
        reset.triggered.connect(self._reset_charts)
        actions.append(reset)
        return actions

    def get_status_info(self) -> str:
        return "PerfMon — Real-time monitoring"

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._search_provider

    def get_refresh_interval(self) -> Optional[int]:
        return 5000  # 5 seconds

    def refresh_data(self) -> None:
        self._reset_charts()

    def _tick(self) -> None:
        try:
            snapshot = collect_snapshot()
        except Exception as e:
            logger.error("PerfMon collect failed: %s", e)
            return

        # Calculate network rate (bytes/sec -> KB/s)
        net_sent = snapshot.get("net_sent_bytes", 0)
        net_recv = snapshot.get("net_recv_bytes", 0)
        if self._prev_net_sent > 0:
            sent_rate = (net_sent - self._prev_net_sent) / 1024
            recv_rate = (net_recv - self._prev_net_recv) / 1024
            snapshot["net_rate_kbs"] = sent_rate + recv_rate
        else:
            snapshot["net_rate_kbs"] = 0
        self._prev_net_sent = net_sent
        self._prev_net_recv = net_recv

        # Update charts
        if self._dashboard:
            self._dashboard.update_from_snapshot(snapshot)
            if "net_rate_kbs" in snapshot:
                self._dashboard.net_chart.add_point(snapshot["net_rate_kbs"])

        # Update summary label
        if self._summary_label:
            cpu = snapshot.get("cpu_total", 0)
            mem = snapshot.get("memory_percent", 0)
            disk = snapshot.get("disk_percent", 0)
            self._summary_label.setText(
                f"CPU: {cpu:.1f}%  |  Memory: {mem:.1f}%  |  Disk: {disk:.1f}%  |  Net: {snapshot.get('net_rate_kbs', 0):.1f} KB/s"
            )

        # Store to SQLite every 60 ticks (1 minute)
        self._store_counter += 1
        if self._store and self._store_counter >= 60:
            self._store_counter = 0
            try:
                self._store.store_snapshot(snapshot)
            except Exception as e:
                logger.error("PerfMon store failed: %s", e)

        # Check alerts
        for rule in self._alerts:
            value = snapshot.get(rule.counter, 0)
            alert_msg = rule.check(value)
            if alert_msg:
                self._fire_alert(alert_msg, snapshot)

    def _fire_alert(self, message: str, snapshot: dict) -> None:
        logger.warning("PerfMon Alert: %s", message)
        entry = LogEntry(
            timestamp=datetime.now(),
            source="PerfMon",
            level="Warning",
            message=message,
            raw=dict(snapshot),
        )
        self._search_provider.add_alert(entry)

        # Publish to event bus
        if self.app and hasattr(self.app, "event_bus"):
            from core.events import MODULE_ERROR
            self.app.event_bus.publish(MODULE_ERROR, {
                "module": "PerfMon",
                "message": message,
            })

    def _reset_charts(self) -> None:
        if self._dashboard:
            for chart in [
                self._dashboard.cpu_chart,
                self._dashboard.memory_chart,
                self._dashboard.disk_chart,
                self._dashboard.net_chart,
            ]:
                chart._data.clear()
                chart._times.clear()
                if chart._curve:
                    chart._curve.setData([], [])

    def _update_live_monitor(self) -> None:
        try:
            import psutil

            # CPU
            cpu = int(psutil.cpu_percent())
            self._cpu_bar.setValue(cpu)
            color = "#00cc44" if cpu < 60 else "#ff8800" if cpu < 85 else "#cc2222"
            self._cpu_bar.setStyleSheet(f"""
                QProgressBar {{ border: 1px solid #555; border-radius: 4px; text-align: center; background: #2d2d2d; color: #e0e0e0; }}
                QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}
            """)

            # Memory
            mem = psutil.virtual_memory()
            mem_pct = int(mem.percent)
            self._mem_bar.setValue(mem_pct)
            color = "#00cc44" if mem_pct < 60 else "#ff8800" if mem_pct < 85 else "#cc2222"
            self._mem_bar.setStyleSheet(f"""
                QProgressBar {{ border: 1px solid #555; border-radius: 4px; text-align: center; background: #2d2d2d; color: #e0e0e0; }}
                QProgressBar::chunk {{ background: {color}; border-radius: 3px; }}
            """)
            self._mem_bar.setFormat(f"{mem.used / 1024**3:.1f} / {mem.total / 1024**3:.1f} GB")

            # Disk I/O delta
            disk = psutil.disk_io_counters()
            if self._live_prev_disk:
                disk_read_mb = (disk.read_bytes - self._live_prev_disk.read_bytes) / 1024 / 1024
                disk_write_mb = (disk.write_bytes - self._live_prev_disk.write_bytes) / 1024 / 1024
                total_mb = disk_read_mb + disk_write_mb
                self._disk_bar.setFormat(f"R:{disk_read_mb:.1f} W:{disk_write_mb:.1f} MB/s")
                self._disk_bar.setValue(min(int(total_mb), 100))
            self._live_prev_disk = disk

            # Network I/O delta
            net = psutil.net_io_counters()
            if self._live_prev_net:
                net_sent_kb = (net.bytes_sent - self._live_prev_net.bytes_sent) / 1024
                net_recv_kb = (net.bytes_recv - self._live_prev_net.bytes_recv) / 1024
                total_kb = net_sent_kb + net_recv_kb
                self._net_bar.setFormat(f"U:{net_sent_kb:.0f} D:{net_recv_kb:.0f} KB/s")
                self._net_bar.setValue(min(int(total_kb), 100))
            self._live_prev_net = net

            # Top processes by CPU
            procs = []
            for p in psutil.process_iter(['name', 'cpu_percent', 'memory_info']):
                try:
                    name = p.info['name']
                    cpu_pct = p.info['cpu_percent'] or 0
                    mem_mb = (p.info['memory_info'].rss or 0) / 1024 / 1024
                    procs.append((name, cpu_pct, mem_mb))
                except (OSError, psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            procs.sort(key=lambda x: -x[1])
            for i in range(10):
                if i < len(procs):
                    name, cpu_pct, mem_mb = procs[i]
                    self._proc_table.setItem(i, 0, QTableWidgetItem(name))
                    self._proc_table.setItem(i, 1, QTableWidgetItem(f"{cpu_pct:.1f}"))
                    self._proc_table.setItem(i, 2, QTableWidgetItem(f"{mem_mb:.0f}"))
                else:
                    for col in range(3):
                        self._proc_table.setItem(i, col, QTableWidgetItem(""))
        except Exception as e:
            logger.debug("Live monitor update failed: %s", e)
