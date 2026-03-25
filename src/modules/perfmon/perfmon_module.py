import logging
import os
from datetime import datetime
from typing import Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget, QHBoxLayout

from core.base_module import BaseModule
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
    icon = "perfmon"
    description = "Real-time performance monitoring with historical graphs and alerts"
    requires_admin = False

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

        # Summary row
        self._summary_label = QLabel("Collecting data...")
        self._summary_label.setStyleSheet("font-size: 13px; padding: 4px;")
        layout.addWidget(self._summary_label)

        # Dashboard with charts
        self._dashboard = PerfMonDashboard()
        layout.addWidget(self._dashboard)

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
        if self._timer is None:
            # Seed cpu_percent so first real reading isn't 0
            import psutil
            psutil.cpu_percent(interval=None)

            self._timer = QTimer()
            self._timer.setInterval(1000)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    def on_deactivate(self) -> None:
        # Keep timer running for data collection even when tab is not active
        pass

    def on_stop(self) -> None:
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
