"""Process Explorer's System Information window.

Its graphs are the same pure-QPainter widgets the Performance tab uses, so
these tests actually paint: a float coordinate reaching a PyQt6 draw call
raises inside `paintEvent`, a Qt virtual, where the exception goes to
`sys.excepthook` and then `qFatal()`. Uncatchable, and the window dies.
"""
import pytest
from PyQt6.QtGui import QImage, QPainter

from modules.dashboard.system_information import (
    SystemInformationDialog, _delta, _per_second, _rate,
)


def _paint(widget, width=760, height=720):
    widget.resize(width, height)
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    widget.render(painter)
    painter.end()
    return image


@pytest.fixture
def window(qapp):
    dialog = SystemInformationDialog()
    dialog.refresh()   # the first reading of anything has no rate
    dialog.refresh()
    yield dialog
    dialog.stop()
    dialog.deleteLater()


# ---- the tabs -----------------------------------------------------------

def test_it_offers_the_five_tabs(window):
    labels = [window.tabs.tabText(index)
              for index in range(window.tabs.count())]
    assert labels == ["Summary", "CPU", "Memory", "I/O", "GPU"]


def test_every_tab_paints(window):
    for index in range(window.tabs.count()):
        window.tabs.setCurrentIndex(index)
        _paint(window)


# ---- the readings -------------------------------------------------------

def test_the_summary_graphs_all_have_a_reading(window):
    for name, (_graph, reading) in window.summary_graphs.items():
        assert reading.text() != "—", f"{name} reported nothing"


def test_the_cpu_totals_are_filled_in(window):
    for name in ("Processes", "Threads", "Handles", "Up time"):
        assert window._values[f"cpu.{name}"].text() != "—", name


def test_context_switches_and_system_calls_are_measured(window):
    """Two readings in, both should be real -- these are the figures the
    window exists to show, and they are the ones at the far end of the
    undocumented struct."""
    for name in ("Context switches", "System calls"):
        text = window._values[f"cpu.{name}"].text()
        assert text.endswith("/s") and text != "—", f"{name} is {text!r}"


def test_the_memory_figures_are_filled_in(window):
    for name in ("Current", "Limit", "Peak", "Total", "Available", "Cached"):
        assert window._values[f"commit.{name}"].text() != "—", name


def test_the_kernel_figures_are_filled_in(window):
    for name in ("Paged pool", "Non-paged pool", "Paged allocations",
                 "Non-paged allocations", "Free system PTEs"):
        assert window._values[f"kernel.{name}"].text() != "—", name


def test_the_io_figures_are_filled_in(window):
    for name in ("Reads", "Read bytes", "Writes", "Write bytes",
                 "Other", "Other bytes"):
        assert window._values[f"io.{name}"].text() != "—", name


def test_the_gpu_tab_graphs_the_adapters(window):
    assert window._gpu_rows, "no adapter was graphed"


# ---- the first reading is a gap, not a zero -----------------------------

def test_the_first_reading_draws_no_rate(qapp):
    """Every counter behind this window is cumulative since boot, so one
    reading is not a rate. A zero here would say the machine is doing
    nothing at the exact moment someone opened the window to find out."""
    dialog = SystemInformationDialog()
    try:
        dialog.refresh()
        assert dialog.cpu_graph.history() == [None]
        assert dialog.io_graph.history() == [None]
        assert dialog._values["cpu.Context switches"].text() == "—"
        assert dialog._values["cpu.System calls"].text() == "—"
    finally:
        dialog.stop()


def test_a_failed_reading_does_not_kill_the_timer(window, monkeypatch):
    """One bad tick must not leave the window permanently dead."""
    import modules.dashboard.system_information as module

    def boom():
        raise OSError("the counters went away")

    monkeypatch.setattr(module, "processor_times", boom)
    window.refresh()          # must not raise
    monkeypatch.undo()
    window.refresh()
    assert window._values["cpu.Processes"].text() != "—"


def test_stopping_closes_the_gpu_query(qapp):
    """The PDH query lives in the performance-counter service, so an
    abandoned one outlives the window that opened it."""
    dialog = SystemInformationDialog()
    dialog.refresh()
    assert dialog._gpu is not None
    dialog.stop()
    assert dialog._gpu is None


# ---- formatting ---------------------------------------------------------

def test_an_unmeasured_rate_is_a_dash_not_a_zero():
    assert _per_second(None) == "—"
    assert _per_second(0) == "0/s"
    assert _per_second(23851.4) == "23,851/s"
    assert _rate(None) == "—"


def test_outstanding_pool_allocations_lead_the_pair():
    """Process Explorer shows allocations and frees; the number anyone
    reads is the difference."""
    assert _delta(1000, 400).startswith("600")
    assert "1,000 / 400" in _delta(1000, 400)


def test_untracked_pool_allocations_are_not_reported_as_zero():
    """Caught by reading the rendered panel, not by a test. A machine
    carrying 1.2 GB of paged pool has not made zero pool allocations --
    the two figures contradict each other, which is how you know the
    kernel is not maintaining the counter. Windows says the same: its own
    `\\Memory\\Pool Paged Allocs` reads 0 beside a `Pool Paged Bytes` of
    1.34 GB. As "0" it reads as a measurement."""
    assert _delta(0, 0) == "not tracked by this Windows build"


def test_the_pool_allocation_counters_really_are_untracked_here():
    """Pins the machine fact the wording above rests on, so that if a
    future Windows starts maintaining these, the panel stops lying in the
    other direction and someone is told."""
    from modules.dashboard.procengine.sysinfo import system_counters

    counters = system_counters()
    assert counters.paged_pool_pages > 0, "the paged pool is not empty"
    assert counters.paged_pool_allocs == 0 and counters.paged_pool_frees == 0


def test_the_pool_allocations_row_says_it_is_untracked(window):
    assert window._values["kernel.Paged allocations"].text() == \
        "not tracked by this Windows build"
