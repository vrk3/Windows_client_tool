import logging
from collections import deque
from datetime import datetime

from PyQt6.QtWidgets import QVBoxLayout, QWidget, QTabWidget, QLabel

logger = logging.getLogger(__name__)

try:
    import pyqtgraph as pg
    HAS_PYQTGRAPH = True
except ImportError:
    HAS_PYQTGRAPH = False
    logger.warning("pyqtgraph not installed — charts disabled")


class RealTimeChart(QWidget):
    """A single real-time line chart with a rolling window."""

    MAX_POINTS = 300  # 5 minutes at 1s interval

    def __init__(self, title: str, y_label: str, y_range: tuple = None, parent=None):
        super().__init__(parent)
        self._title = title
        self._data = deque(maxlen=self.MAX_POINTS)
        self._times = deque(maxlen=self.MAX_POINTS)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if HAS_PYQTGRAPH:
            self._plot_widget = pg.PlotWidget(title=title)
            self._plot_widget.setLabel("left", y_label)
            self._plot_widget.setLabel("bottom", "Time (s)")
            self._plot_widget.showGrid(x=True, y=True, alpha=0.3)
            if y_range:
                self._plot_widget.setYRange(*y_range)
            self._curve = self._plot_widget.plot(pen=pg.mkPen(color="#007acc", width=2))
            layout.addWidget(self._plot_widget)
        else:
            layout.addWidget(QLabel(f"{title}\n(Install pyqtgraph for charts)"))
            self._plot_widget = None
            self._curve = None

    def add_point(self, value: float) -> None:
        self._data.append(value)
        self._times.append(len(self._data))
        if self._curve:
            self._curve.setData(list(self._times), list(self._data))


class PerfMonDashboard(QWidget):
    """Dashboard with multiple real-time charts in tabs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)

        # Create charts
        self.cpu_chart = RealTimeChart("CPU Usage", "%", y_range=(0, 100))
        self._tabs.addTab(self.cpu_chart, "CPU")

        self.memory_chart = RealTimeChart("Memory Usage", "%", y_range=(0, 100))
        self._tabs.addTab(self.memory_chart, "Memory")

        self.disk_chart = RealTimeChart("Disk Usage", "%", y_range=(0, 100))
        self._tabs.addTab(self.disk_chart, "Disk")

        self.net_chart = RealTimeChart("Network I/O", "KB/s")
        self._tabs.addTab(self.net_chart, "Network")

    def update_from_snapshot(self, snapshot: dict) -> None:
        """Update all charts from a performance snapshot."""
        if "cpu_total" in snapshot:
            self.cpu_chart.add_point(snapshot["cpu_total"])
        if "memory_percent" in snapshot:
            self.memory_chart.add_point(snapshot["memory_percent"])
        if "disk_percent" in snapshot:
            self.disk_chart.add_point(snapshot["disk_percent"])
