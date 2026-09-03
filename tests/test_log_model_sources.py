"""The Source column and Source filter, and the re-merge path behind them.

With several logs open at once, "which file said this" becomes a question the
table has to answer -- and one you have to be able to filter on, because the
whole point of merging is that you can then narrow back down.
"""
from datetime import datetime


from core.types import LogEntry
from modules.log_viewer.log_model import (
    LogModel, MESSAGE, SOURCE,
)


def _entry(message, log="cbs.log", level="Info", source="CBS", minute=0):
    return LogEntry(timestamp=datetime(2026, 8, 27, 10, minute, 0),
                    source=source, level=level, message=message,
                    raw={"thread": "1", "log": log})


def _model(entries=(), cap=None):
    model = LogModel(cap=cap) if cap else LogModel()
    model.append(list(entries))
    return model


def _messages(model):
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


# ---- the column ---------------------------------------------------------

def test_the_source_column_shows_the_file_a_record_came_from(qapp):
    model = _model([_entry("hello", log="dism.log")])
    assert model.data(model.index(0, SOURCE)) == "dism.log"


def test_a_record_with_no_log_leaves_the_column_empty(qapp):
    """A single log opened on its own is not tagged, and the pane hides the
    column entirely in that case."""
    entry = _entry("hello")
    entry.raw.pop("log")
    model = _model([entry])
    assert model.data(model.index(0, SOURCE)) == ""


def test_the_source_column_does_not_displace_the_component(qapp):
    """`entry.source` is the COMPONENT. The two are different questions and
    both get their own column."""
    from modules.log_viewer.log_model import COMPONENT
    model = _model([_entry("hello", log="dism.log", source="CSI")])
    assert model.data(model.index(0, COMPONENT)) == "CSI"
    assert model.data(model.index(0, SOURCE)) == "dism.log"


def test_the_open_logs_are_listed_for_the_combo(qapp):
    model = _model([_entry("a", log="cbs.log"), _entry("b", log="dism.log"),
                    _entry("c", log="cbs.log")])
    assert model.logs() == ["cbs.log", "dism.log"]


# ---- the filter ---------------------------------------------------------

def test_filtering_by_source_keeps_only_that_log(qapp):
    model = _model([_entry("from cbs", log="cbs.log"),
                    _entry("from dism", log="dism.log")])

    model.set_filter(log="dism.log")

    assert _messages(model) == ["from dism"]


def test_clearing_the_source_filter_brings_every_log_back(qapp):
    model = _model([_entry("from cbs", log="cbs.log"),
                    _entry("from dism", log="dism.log")])
    model.set_filter(log="dism.log")

    model.set_filter(log="")

    assert _messages(model) == ["from cbs", "from dism"]


def test_the_source_filter_combines_with_a_severity_filter(qapp):
    model = _model([_entry("cbs info", log="cbs.log"),
                    _entry("cbs error", log="cbs.log", level="Error"),
                    _entry("dism error", log="dism.log", level="Error")])

    model.set_filter(log="cbs.log", levels={"Error"})

    assert _messages(model) == ["cbs error"]


# ---- replace, for the re-merge ------------------------------------------

def test_replace_swaps_the_whole_contents(qapp):
    model = _model([_entry("old")])

    model.replace([_entry("new one"), _entry("new two")])

    assert _messages(model) == ["new one", "new two"]


def test_replace_keeping_the_newest_drops_from_the_front(qapp):
    model = _model([], cap=2)

    model.replace([_entry("a"), _entry("b"), _entry("c")])

    assert _messages(model) == ["b", "c"]
    assert model.dropped == 1


def test_replace_keeping_the_oldest_drops_from_the_back(qapp):
    """What "load earlier" needs: the window slid backwards, so what goes is
    the newest -- the same semantics `prepend` has."""
    model = _model([], cap=2)

    model.replace([_entry("a"), _entry("b"), _entry("c")], keep_oldest=True)

    assert _messages(model) == ["a", "b"]
    assert model.unloaded_newer == 1


def test_replace_reapplies_the_filter_that_is_on_screen(qapp):
    """Crossing two interactions: filter, then load earlier in a merged set.
    The re-merged records must obey the filter that is still showing."""
    model = _model([_entry("keep", level="Error")])
    model.set_filter(levels={"Error"})

    model.replace([_entry("chatter"), _entry("keep", level="Error")])

    assert _messages(model) == ["keep"]


def test_replace_recounts_the_folded_continuations(qapp):
    from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
    parent = _entry("Performing 3 operations:")
    child = LogEntry(timestamp=UNKNOWN_TIME, source="CSI", level="Info",
                     message="  (0) alpha",
                     raw={"continuation": "1", "log": "cbs.log"})

    model = _model([])
    model.replace([parent, child])

    assert model.folded_count() == 1
