"""Task Manager's Performance tab.

A list of what the machine has down the left, the chosen one's graph and
figures on the right. CPU and Memory to begin with; disk, network and GPU
slot into the same frame.

The refresh runs on the UI thread on purpose, unlike the process tabs. Its
whole cost is two syscalls -- `NtQuerySystemInformation` for the per-core
times and `GetPerformanceInfo` for memory -- both of which return in
microseconds. Handing that to a worker would cost more in signal marshalling
than it saves, and it would let two readings land out of order, which a graph
notices.
"""
import logging
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                             QListWidget, QListWidgetItem, QStackedWidget,
                             QVBoxLayout, QWidget)

from core.semantic_colors import semantic

from .perf_graph import CoreGrid, PerfGraph
from .procengine.columns import fmt_bytes
from .procengine.cpuinfo import (core_loads, cpu_static, processor_times,
                                 uptime_seconds)
from .procengine.ioinfo import (disk_counters, disk_rates,
                                interface_counters, interface_rates)
from .procengine.meminfo import memory_modules, memory_status

logger = logging.getLogger(__name__)

REFRESH_MS = 1000


class PerformanceTab(QWidget):
    """The Performance tab. A QWidget, so it owns its own timer and teardown."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._workers: list = []
        self._app = None
        self._previous_cores = None
        self._previous_disks = None
        self._previous_nics = None
        self._static = None
        self._setup_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    # ---- construction ---------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        self.chooser = QListWidget(self)
        self.chooser.setFixedWidth(190)
        self.chooser.currentRowChanged.connect(self._show_panel)
        layout.addWidget(self.chooser)

        self.panels = QStackedWidget(self)
        layout.addWidget(self.panels, 1)

        self._add_cpu_panel()
        self._add_memory_panel()
        self._add_disk_panel()
        self._add_network_panel()
        self.chooser.setCurrentRow(0)

    def _add_cpu_panel(self) -> None:
        panel = QWidget(self)
        column = QVBoxLayout(panel)

        self.cpu_title = QLabel("CPU", panel)
        self.cpu_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        column.addWidget(self.cpu_title)
        self.cpu_subtitle = QLabel("", panel)
        self.cpu_subtitle.setStyleSheet(
            f"color: {semantic('info')};")
        column.addWidget(self.cpu_subtitle)

        self.cpu_graph = PerfGraph(semantic("info"), 100.0, panel)
        column.addWidget(self.cpu_graph, 2)

        self.core_label = QLabel("Logical processors", panel)
        column.addWidget(self.core_label)
        self.core_grid = CoreGrid(panel)
        column.addWidget(self.core_grid, 3)

        self.cpu_figures = QGridLayout()
        self._cpu_values = {}
        for index, name in enumerate(
                ("Utilisation", "Speed", "Processes", "Threads",
                 "Handles", "Up time")):
            self.cpu_figures.addWidget(
                _caption(name, panel), 0, index)
            value = QLabel("—", panel)
            value.setStyleSheet("font-size: 15px;")
            self._cpu_values[name] = value
            self.cpu_figures.addWidget(value, 1, index)
        column.addLayout(self.cpu_figures)

        self.cpu_facts = QFormLayout()
        self._cpu_facts = {}
        for name in ("Base speed", "Sockets", "Cores", "Logical processors",
                     "L1 cache", "L2 cache", "L3 cache", "Virtualisation"):
            value = QLabel("—", panel)
            self._cpu_facts[name] = value
            self.cpu_facts.addRow(_caption(name, panel), value)
        column.addLayout(self.cpu_facts)

        self.panels.addWidget(panel)
        self.chooser.addItem(QListWidgetItem("CPU"))

    def _add_memory_panel(self) -> None:
        panel = QWidget(self)
        column = QVBoxLayout(panel)

        self.memory_title = QLabel("Memory", panel)
        self.memory_title.setStyleSheet("font-size: 18px; font-weight: 600;")
        column.addWidget(self.memory_title)
        self.memory_subtitle = QLabel("", panel)
        self.memory_subtitle.setStyleSheet(f"color: {semantic('success')};")
        column.addWidget(self.memory_subtitle)

        self.memory_graph = PerfGraph(semantic("success"), 100.0, panel)
        column.addWidget(self.memory_graph, 3)

        self.memory_figures = QGridLayout()
        self._memory_values = {}
        for index, name in enumerate(
                ("In use", "Available", "Committed", "Cached",
                 "Paged pool", "Non-paged pool")):
            self.memory_figures.addWidget(_caption(name, panel), 0, index)
            value = QLabel("—", panel)
            value.setStyleSheet("font-size: 15px;")
            self._memory_values[name] = value
            self.memory_figures.addWidget(value, 1, index)
        column.addLayout(self.memory_figures)

        self.memory_facts = QFormLayout()
        self._memory_facts = {}
        for name in ("Speed", "Slots used", "Form factor",
                     "Hardware reserved"):
            value = QLabel("—", panel)
            self._memory_facts[name] = value
            self.memory_facts.addRow(_caption(name, panel), value)
        column.addLayout(self.memory_facts)

        self.panels.addWidget(panel)
        self.chooser.addItem(QListWidgetItem("Memory"))

    def _add_disk_panel(self) -> None:
        """One graph for every physical disk, stacked.

        Task Manager gives each disk its own entry in the chooser. Stacking
        them in one panel says the same thing in less clicking, and this
        machine has seven.
        """
        panel = QWidget(self)
        column = QVBoxLayout(panel)
        title = QLabel("Disk", panel)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        column.addWidget(title)

        self.disk_area = QVBoxLayout()
        column.addLayout(self.disk_area, 1)
        column.addStretch(0)
        #: index -> (graph, caption). Built on the first reading, because
        #: how many disks there are is not known until then.
        self._disk_rows = {}

        self.panels.addWidget(panel)
        self.chooser.addItem(QListWidgetItem("Disk"))

    def _add_network_panel(self) -> None:
        panel = QWidget(self)
        column = QVBoxLayout(panel)
        title = QLabel("Network", panel)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        column.addWidget(title)

        self.network_area = QVBoxLayout()
        column.addLayout(self.network_area, 1)
        column.addStretch(0)
        self._network_rows = {}

        self.panels.addWidget(panel)
        self.chooser.addItem(QListWidgetItem("Network"))

    # ---- lifecycle ------------------------------------------------------

    def set_app(self, app) -> None:
        self._app = app

    def start(self) -> None:
        self._load_static()
        self.refresh()
        self._timer.start(REFRESH_MS)

    def stop(self) -> None:
        self._timer.stop()
        self.cancel_all()

    def cancel_all(self) -> None:
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()

    def _show_panel(self, row: int) -> None:
        self.panels.setCurrentIndex(max(0, row))

    # ---- the slow facts, read once --------------------------------------

    def _load_static(self) -> None:
        """Processor and DIMM facts. Read once: none of it changes, and the
        DIMM list is a WMI query that must never touch a per-second path."""
        if self._static is not None:
            return
        self._static = cpu_static()
        static = self._static
        self.cpu_title.setText("CPU")
        self.cpu_subtitle.setText(static.name or "Processor")
        self._set_fact("Base speed", _speed(static.base_speed_mhz))
        self._set_fact("Sockets", _count(static.sockets))
        self._set_fact("Cores", _count(static.cores))
        self._set_fact("Logical processors", _count(static.logical))
        self._set_fact("L1 cache", _bytes_or_dash(static.l1_cache))
        self._set_fact("L2 cache", _bytes_or_dash(static.l2_cache))
        self._set_fact("L3 cache", _bytes_or_dash(static.l3_cache))
        self._set_fact("Virtualisation", _enabled(static.virtualisation))

        modules = memory_modules()
        if modules:
            speeds = {module.speed_mhz for module in modules
                      if module.speed_mhz}
            forms = {module.form_factor for module in modules
                     if module.form_factor}
            # NOT `_speed`: that promotes anything over 1000 to GHz, which
            # is right for a processor and wrong for memory. 4800 MHz RAM
            # rendered as "4.80 GHz" is a figure nobody quotes.
            self._memory_facts["Speed"].setText(
                _memory_speed(max(speeds)) if speeds else "—")
            self._memory_facts["Slots used"].setText(str(len(modules)))
            self._memory_facts["Form factor"].setText(
                ", ".join(sorted(forms)) if forms else "—")

    def _set_fact(self, name: str, text: str) -> None:
        self._cpu_facts[name].setText(text)

    # ---- the live half --------------------------------------------------

    def refresh(self) -> None:
        try:
            self._refresh_cpu()
            self._refresh_memory()
            self._refresh_disks()
            self._refresh_network()
        except OSError as error:
            # A failed reading must not kill the timer, or the tab goes
            # permanently dead after one hiccup.
            logger.warning("Performance refresh failed: %s", error)

    def _refresh_disks(self) -> None:
        current = disk_counters()
        if self._previous_disks is None:
            self._previous_disks = current
            return
        rates = disk_rates(self._previous_disks, current)
        self._previous_disks = current
        for rate in rates:
            graph, caption = self._disk_row(rate.index)
            graph.push(rate.active_percent)
            caption.setText(
                f"Disk {rate.index}   ·   active "
                f"{_percent(rate.active_percent)}   ·   "
                f"read {_rate(rate.read_bps)}   ·   "
                f"write {_rate(rate.write_bps)}   ·   "
                f"queue {rate.queue_depth}")

    def _disk_row(self, index: int):
        row = self._disk_rows.get(index)
        if row is None:
            caption = QLabel("", self)
            caption.setStyleSheet("font-size: 11px;")
            graph = PerfGraph(semantic("warning"), 100.0, self)
            graph.setMinimumHeight(56)
            self.disk_area.addWidget(caption)
            self.disk_area.addWidget(graph)
            row = (graph, caption)
            self._disk_rows[index] = row
        return row

    def _refresh_network(self) -> None:
        current = interface_counters()
        if self._previous_nics is None:
            self._previous_nics = current
            return
        rates = interface_rates(self._previous_nics, current)
        self._previous_nics = current
        for rate in rates:
            # Only the interfaces that are actually up. A machine has a
            # dozen tunnel and loopback adapters and a graph each would
            # bury the one that matters.
            if not rate.up or rate.loopback:
                continue
            graph, caption = self._network_row(rate.name)
            total = (rate.send_bps or 0) + (rate.receive_bps or 0)
            graph.push(None if rate.send_bps is None else total)
            # Scaled to the busiest moment in the visible window, not to the
            # link speed. Against a 2.5 Gb/s link, ordinary traffic of a few
            # kilobytes a second is a flat line on the floor -- the graph
            # would only ever move during a file transfer. Task Manager
            # rescales the same way, which is why its axis label changes.
            graph.set_ceiling(_ceiling_for(graph))
            caption.setText(
                f"{rate.name}   ·   send {_rate(rate.send_bps)}   ·   "
                f"receive {_rate(rate.receive_bps)}   ·   "
                f"link {_link(rate.speed_bps)}")

    def _network_row(self, name: str):
        row = self._network_rows.get(name)
        if row is None:
            caption = QLabel("", self)
            caption.setStyleSheet("font-size: 11px;")
            graph = PerfGraph(semantic("info"), 1.0, self)
            graph.setMinimumHeight(56)
            self.network_area.addWidget(caption)
            self.network_area.addWidget(graph)
            row = (graph, caption)
            self._network_rows[name] = row
        return row

    def _refresh_cpu(self) -> None:
        current = processor_times()
        if self._previous_cores is None:
            # One reading is not a rate. Record the gap rather than drawing
            # a zero, which would put a dip at the start of every graph.
            self._previous_cores = current
            self.cpu_graph.push(None)
            return

        loads = core_loads(self._previous_cores, current)
        self._previous_cores = current
        if not loads:
            return
        average = sum(load.total for load in loads) / len(loads)
        self.cpu_graph.push(average)
        self.core_grid.push([load.total for load in loads])
        self.core_label.setText(f"{len(loads)} logical processors")

        self._cpu_values["Utilisation"].setText(f"{average:.0f}%")
        static = self._static
        self._cpu_values["Speed"].setText(
            _speed(static.base_speed_mhz) if static else "—")
        self._cpu_values["Up time"].setText(_uptime(uptime_seconds()))

    def _refresh_memory(self) -> None:
        status = memory_status()
        self.memory_graph.push(status.used_percent)
        self.memory_subtitle.setText(
            f"{fmt_bytes(status.installed or status.total)} "
            f"{self._memory_facts['Form factor'].text()}".strip())

        self._memory_values["In use"].setText(fmt_bytes(status.in_use))
        self._memory_values["Available"].setText(fmt_bytes(status.available))
        self._memory_values["Committed"].setText(
            f"{fmt_bytes(status.committed)} / {fmt_bytes(status.commit_limit)}")
        self._memory_values["Cached"].setText(fmt_bytes(status.cached))
        self._memory_values["Paged pool"].setText(
            fmt_bytes(status.kernel_paged))
        self._memory_values["Non-paged pool"].setText(
            fmt_bytes(status.kernel_nonpaged))
        self._memory_facts["Hardware reserved"].setText(
            _bytes_or_dash(status.hardware_reserved))

        # These come from the same call, and the CPU panel shows them.
        self._cpu_values["Processes"].setText(f"{status.processes:,}")
        self._cpu_values["Threads"].setText(f"{status.threads:,}")
        self._cpu_values["Handles"].setText(f"{status.handles:,}")


def _caption(text: str, parent) -> QLabel:
    label = QLabel(text, parent)
    label.setStyleSheet("font-size: 11px;")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft)
    return label


def _speed(mhz: Optional[int]) -> str:
    if not mhz:
        return "—"
    if mhz >= 1000:
        return f"{mhz / 1000:.2f} GHz"
    return f"{mhz} MHz"


def _memory_speed(mhz: Optional[int]) -> str:
    """Memory speed stays in MHz however large it gets.

    DDR5 runs at 4800 MHz and up, and every spec sheet, BIOS screen and
    Task Manager panel quotes that number in MHz. Promoting it to GHz the
    way a processor clock is promoted produces "4.80 GHz", which is both
    unfamiliar and easily misread as the CPU's speed.
    """
    return "—" if not mhz else f"{mhz:,} MHz"


def _count(value: Optional[int]) -> str:
    return "—" if value is None else str(value)


def _bytes_or_dash(value: Optional[int]) -> str:
    return "—" if value is None else fmt_bytes(value)


def _enabled(value: Optional[bool]) -> str:
    if value is None:
        return "—"
    return "Enabled" if value else "Disabled"


def _ceiling_for(graph) -> float:
    """The graph's own peak, with a floor so a silent link is not scaled
    against zero."""
    seen = [value for value in graph.history() if value]
    return max(seen) * 1.15 if seen else 1024.0


def _percent(value: Optional[float]) -> str:
    return "—" if value is None else f"{value:.0f}%"


def _rate(value: Optional[float]) -> str:
    """Bytes per second, or a dash when it has not been measured yet.

    Not "0 B/s": the first reading of any device has no rate, and claiming
    zero there says the device is idle when we simply have not looked twice.
    """
    if value is None:
        return "—"
    return f"{fmt_bytes(value)}/s"


def _link(speed_bps: Optional[int]) -> str:
    if not speed_bps:
        return "—"
    if speed_bps >= 1_000_000_000:
        return f"{speed_bps / 1_000_000_000:.1f} Gb/s"
    return f"{speed_bps / 1_000_000:.0f} Mb/s"


def _uptime(seconds: float) -> str:
    total = int(seconds)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{days}:{hours:02d}:{minutes:02d}:{secs:02d}"
