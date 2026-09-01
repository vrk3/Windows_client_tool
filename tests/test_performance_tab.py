"""The Performance tab and its graphs.

The graphs are pure QPainter, and the rule that matters is that every
coordinate reaching a PyQt6 draw call is an int: a float raises TypeError
inside `paintEvent`, which is a reimplemented Qt virtual, where the exception
goes to sys.excepthook and then qFatal(). Uncatchable; the window dies. So
these tests actually paint.
"""
import pytest
from PyQt6.QtGui import QImage, QPainter

from modules.dashboard.perf_graph import HISTORY, CoreGrid, PerfGraph
from modules.dashboard.performance_tab import PerformanceTab


def _paint(widget, width=400, height=200):
    """Render the widget for real. This is the test: a float coordinate
    would take the process down here rather than in front of the user."""
    widget.resize(width, height)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    return image


# ---- the graph ----------------------------------------------------------

def test_an_empty_graph_paints(qapp):
    """Before the first sample arrives, which is a real state."""
    _paint(PerfGraph())


def test_a_graph_with_one_sample_paints(qapp):
    graph = PerfGraph()
    graph.push(50.0)
    _paint(graph)


def test_a_full_graph_paints(qapp):
    graph = PerfGraph()
    for value in range(HISTORY):
        graph.push(value * 100.0 / HISTORY)
    _paint(graph)


def test_a_graph_with_gaps_paints(qapp):
    """A missing reading is a gap, and the run-splitting that draws it is
    the fiddliest part of the paint."""
    graph = PerfGraph()
    for index in range(HISTORY):
        graph.push(None if index % 5 == 0 else 40.0)
    _paint(graph)


def test_a_graph_of_only_gaps_paints(qapp):
    graph = PerfGraph()
    for _ in range(10):
        graph.push(None)
    _paint(graph)


def test_a_tiny_graph_paints(qapp):
    """A collapsed splitter gives a widget a width of a few pixels."""
    _paint(PerfGraph(), width=3, height=3)


def test_a_missing_sample_is_a_gap_not_a_zero(qapp):
    """A reading we do not have is not a reading of nothing. Drawing it as
    zero invents a dip that never happened."""
    graph = PerfGraph()
    graph.push(None)
    assert graph.history() == [None]
    assert graph.latest() is None


def test_the_latest_value_skips_over_gaps(qapp):
    graph = PerfGraph()
    graph.push(42.0)
    graph.push(None)
    assert graph.latest() == 42.0


def test_the_history_is_capped(qapp):
    """A graph left running for a day must not cost more than one left
    running for a minute."""
    graph = PerfGraph()
    for value in range(HISTORY * 3):
        graph.push(float(value))
    assert len(graph.history()) == HISTORY


def test_a_value_above_the_ceiling_is_clamped(qapp):
    """A rate measured across a short tick can exceed its ceiling; the
    polygon must stay inside the widget."""
    graph = PerfGraph(ceiling=100.0)
    graph.push(500.0)
    _paint(graph)


def test_a_negative_value_is_clamped(qapp):
    graph = PerfGraph()
    graph.push(-20.0)
    _paint(graph)


# ---- the per-core grid --------------------------------------------------

def test_an_empty_core_grid_paints(qapp):
    _paint(CoreGrid())


def test_a_core_grid_paints_for_a_real_core_count(qapp):
    grid = CoreGrid()
    for _ in range(10):
        grid.push([float(core * 3) for core in range(32)])
    _paint(grid, 600, 300)
    assert grid.cores() == 32


def test_a_core_grid_handles_a_single_core(qapp):
    grid = CoreGrid()
    grid.push([50.0])
    _paint(grid)
    assert grid.cores() == 1


def test_the_core_grid_resizes_when_the_core_count_changes(qapp):
    """Cores can be parked; the grid must not index off the end."""
    grid = CoreGrid()
    grid.push([1.0, 2.0, 3.0, 4.0])
    grid.push([1.0, 2.0])
    assert grid.cores() == 2
    _paint(grid)


def test_a_tiny_core_grid_paints(qapp):
    grid = CoreGrid()
    grid.push([float(core) for core in range(32)])
    _paint(grid, 4, 4)


# ---- the tab ------------------------------------------------------------

@pytest.fixture
def tab(qapp):
    widget = PerformanceTab()
    widget._load_static()
    widget.refresh()   # first reading has no rate
    widget.refresh()
    yield widget
    widget.stop()
    widget.deleteLater()


def test_the_tab_offers_cpu_and_memory(tab):
    labels = [tab.chooser.item(row).text()
              for row in range(tab.chooser.count())]
    assert "CPU" in labels and "Memory" in labels


def test_choosing_a_panel_switches_to_it(tab):
    tab.chooser.setCurrentRow(1)
    assert tab.panels.currentIndex() == 1


def test_the_cpu_panel_names_the_processor(tab):
    assert tab.cpu_subtitle.text()
    assert "—" not in tab.cpu_subtitle.text()


def test_the_processor_facts_are_filled_in(tab):
    for name in ("Base speed", "Cores", "Logical processors", "L3 cache"):
        assert tab._cpu_facts[name].text() != "—", f"{name} is missing"


def test_the_cpu_utilisation_is_measured(tab):
    assert tab._cpu_values["Utilisation"].text().endswith("%")


def test_the_first_cpu_reading_is_a_gap_not_a_zero(qapp):
    """One reading is not a rate. A zero here puts a dip at the start of
    every graph the tab ever draws."""
    widget = PerformanceTab()
    try:
        widget.refresh()
        assert widget.cpu_graph.history() == [None]
    finally:
        widget.stop()


def test_the_core_grid_fills_with_one_plot_per_core(tab):
    import os

    assert tab.core_grid.cores() == (os.cpu_count() or 1)


def test_the_memory_figures_are_filled_in(tab):
    for name in ("In use", "Available", "Committed", "Cached"):
        assert tab._memory_values[name].text() != "—", f"{name} is missing"


def test_the_memory_panel_paints(tab):
    tab.chooser.setCurrentRow(1)
    _paint(tab, 900, 600)


def test_the_cpu_panel_paints(tab):
    tab.chooser.setCurrentRow(0)
    _paint(tab, 900, 600)


def test_the_process_thread_and_handle_counts_are_shown(tab):
    for name in ("Processes", "Threads", "Handles"):
        assert tab._cpu_values[name].text() not in ("—", "")


def test_uptime_is_shown_as_a_duration(tab):
    assert tab._cpu_values["Up time"].text().count(":") == 3


def test_a_failed_reading_does_not_kill_the_timer(tab, monkeypatch):
    """One hiccup must not leave the tab permanently dead."""
    monkeypatch.setattr(
        "modules.dashboard.performance_tab.processor_times",
        lambda: (_ for _ in ()).throw(OSError("boom")))

    tab.refresh()   # must not raise

    monkeypatch.undo()
    tab.refresh()
    assert tab._cpu_values["Utilisation"].text().endswith("%")


def test_stopping_cancels_everything(qapp):
    widget = PerformanceTab()
    widget.refresh()
    widget.stop()
    assert widget._workers == []


def test_memory_speed_stays_in_megahertz(qapp):
    """DDR5 runs at 4800 MHz and every spec sheet, BIOS screen and Task
    Manager panel quotes it that way. Promoting it to GHz the way a
    processor clock is promoted gives "4.80 GHz", which reads as the CPU's
    speed."""
    from modules.dashboard.performance_tab import _memory_speed, _speed

    assert _memory_speed(4800) == "4,800 MHz"
    assert _speed(4800) == "4.80 GHz", "the CPU formatter should still promote"


def test_the_memory_speed_shown_is_not_in_gigahertz(tab):
    shown = tab._memory_facts["Speed"].text()
    if shown == "—":
        pytest.skip("WMI did not report a memory speed")
    assert "GHz" not in shown
    assert "MHz" in shown


# ---- disk and network panels --------------------------------------------

def test_the_tab_offers_disk_and_network(tab):
    labels = [tab.chooser.item(row).text()
              for row in range(tab.chooser.count())]
    assert "Disk" in labels and "Network" in labels


def test_a_graph_appears_for_every_physical_disk(tab):
    from modules.dashboard.procengine.ioinfo import disk_counters

    assert len(tab._disk_rows) == len(disk_counters())


def test_each_disk_caption_reports_its_activity(tab):
    for _graph, caption in tab._disk_rows.values():
        assert "active" in caption.text()
        assert "queue" in caption.text()


def test_only_interfaces_that_are_up_get_a_graph(tab):
    """A machine has a dozen tunnel and loopback adapters; a graph each
    would bury the one that matters."""
    from modules.dashboard.procengine.ioinfo import interface_counters

    assert 0 < len(tab._network_rows) < len(interface_counters())


def test_a_network_graph_is_scaled_against_its_link_speed(tab):
    """A 2.5 Gb/s card and a 100 Mb/s card must not draw the same picture
    for the same traffic."""
    graphs = [graph for graph, _caption in tab._network_rows.values()]
    assert any(graph._ceiling > 1.0 for graph in graphs)


def test_the_first_disk_reading_is_not_drawn_as_zero(qapp):
    widget = PerformanceTab()
    try:
        widget.refresh()
        for graph, _caption in widget._disk_rows.values():
            assert all(value is None for value in graph.history())
    finally:
        widget.stop()


def test_an_unmeasured_rate_shows_a_dash_not_zero_bytes(qapp):
    from modules.dashboard.performance_tab import _rate

    assert _rate(None) == "—"
    assert _rate(0) == "0 B/s"


def test_the_disk_panel_paints(tab):
    tab.chooser.setCurrentRow(2)
    _paint(tab, 900, 600)


def test_the_network_panel_paints(tab):
    tab.chooser.setCurrentRow(3)
    _paint(tab, 900, 600)


# ---- the GPU panel ------------------------------------------------------

def test_the_tab_offers_a_gpu_panel(tab):
    labels = [tab.chooser.item(row).text()
              for row in range(tab.chooser.count())]
    assert "GPU" in labels


def test_a_graph_appears_for_every_hardware_adapter(tab):
    assert tab._gpu_rows, "no GPU graph was built"


def test_the_software_adapter_gets_no_graph(tab):
    """WARP is present on every Windows machine and never does any work.
    A permanently flat graph labelled with its name is a question, not an
    answer, and Task Manager does not list it either."""
    software = {facts.luid for facts in tab._gpu_facts.values()
                if facts.software}
    assert software, "this machine has no software adapter to exclude"
    assert not (software & set(tab._gpu_rows))


def test_each_adapter_reports_its_utilisation(tab):
    for row in tab._gpu_rows.values():
        assert row["utilisation"].text().startswith("Utilisation")


def test_each_adapter_reports_its_memory_against_the_limit(tab):
    for row in tab._gpu_rows.values():
        text = row["memory"].text()
        assert "Dedicated" in text and "shared" in text
        assert " of " in text, f"no limit shown in {text!r}"


def test_the_gpu_panel_paints(tab):
    tab.chooser.setCurrentRow(4)
    _paint(tab, 900, 700)


def test_the_first_gpu_reading_is_not_drawn_as_zero(qapp):
    """The memory counters answer at once but utilisation is a percentage
    over an interval, so the first tick has memory and no load. Drawing
    that as 0% would claim an idle GPU nobody measured."""
    widget = PerformanceTab()
    try:
        widget._load_static()
        widget.refresh()
        for row in widget._gpu_rows.values():
            assert row["graph"].history() == [None]
            assert row["utilisation"].text().endswith("—")
    finally:
        widget.stop()


def test_stopping_closes_the_gpu_query(qapp):
    """The PDH query lives in the performance-counter service, not in this
    process, so an abandoned one outlives the tab that opened it."""
    widget = PerformanceTab()
    widget._load_static()
    widget.refresh()
    assert widget._gpu is not None
    widget.stop()
    assert widget._gpu is None


def test_an_adapter_the_registry_cannot_name_still_gets_a_graph(qapp):
    """The DirectX key is written when DirectX first initialises an
    adapter, so a live one can be missing from it. Dropping the graph
    would hide a working GPU; the LUID is shown instead."""
    from modules.dashboard.performance_tab import _adapter_name

    assert _adapter_name(0x15725, None) == "Adapter 0x15725"


def test_a_missing_directx_version_says_why(qapp):
    """This machine's integrated adapter records no feature level at all.
    A bare dash there reads as a broken panel."""
    from modules.dashboard.performance_tab import _adapter_detail
    from modules.dashboard.procengine.gpuinfo import AdapterFacts

    detail = _adapter_detail(AdapterFacts(
        luid=1, name="Card", driver_version="1.2.3.4",
        unavailable={"directx_version": "the adapter records no level"}))
    assert "DirectX version unavailable" in detail
    assert "the adapter records no level" in detail


def test_gpu_memory_without_a_known_limit_shows_the_figure_alone(qapp):
    from modules.dashboard.performance_tab import _of_limit

    assert _of_limit(None, 100) == "—"
    assert _of_limit(1024, None) == "1.0 KB"
    assert " of " in _of_limit(1024, 4096)


def test_an_idle_engine_and_a_silent_one_read_differently(qapp):
    """Rendering the panel caught these saying the same thing: the
    integrated adapter showed "Utilisation 0%" beside "No engine is
    reporting work", which cannot both be true. Engines reporting zero is
    a measurement; no engines at all is the absence of one."""
    from modules.dashboard.performance_tab import PerformanceTab
    from modules.dashboard.procengine.gpuinfo import AdapterUsage, EngineLoad

    widget = PerformanceTab()
    try:
        idle = AdapterUsage(luid=1, engines=(EngineLoad("3D", 0.0),
                                             EngineLoad("Copy", 0.0)))
        widget._show_adapter(idle, None)
        assert widget._gpu_rows[1]["engines"].text() == "All 2 engines idle"
        assert widget._gpu_rows[1]["utilisation"].text().endswith("0%")

        silent = AdapterUsage(luid=2, engines=())
        widget._show_adapter(silent, None)
        assert "No engine" in widget._gpu_rows[2]["engines"].text()
        assert widget._gpu_rows[2]["utilisation"].text().endswith("—")
    finally:
        widget.stop()
