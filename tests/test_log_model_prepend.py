"""Prepending an earlier chunk to the model, and what the cap does about it.

`append` grows the log forwards and lets the cap drop the OLDEST records.
`prepend` is its mirror: it puts an earlier chunk in front, and the cap then
evicts the NEWEST -- the sliding window that lets someone walk back through a
380 MB archive the 200,000-record cap could never hold at once.

Two things here are silent by nature and so are pinned by tests:
`deque.extendleft` reverses what it is given, and a full deque discards from
the far end without saying so.
"""
from datetime import datetime

import pytest

from core.types import LogEntry
from modules.log_viewer.cmtrace_parser import UNKNOWN_TIME
from modules.log_viewer.log_model import LogModel, MESSAGE


def _entry(message, level="Info", source="C", thread="1", when=None):
    return LogEntry(timestamp=when or datetime(2026, 8, 20, 13, 45, 12),
                    source=source, level=level, message=message,
                    raw={"thread": thread})


def _cont(message):
    return LogEntry(timestamp=UNKNOWN_TIME, source="CSI", level="Info",
                    message=message, raw={"continuation": "1"})


def _messages(model):
    return [model.data(model.index(row, MESSAGE))
            for row in range(model.rowCount())]


def _model(entries=(), cap=None):
    model = LogModel(cap=cap) if cap else LogModel()
    model.append(list(entries))
    return model


# ---- order --------------------------------------------------------------

def test_a_prepended_chunk_lands_before_what_was_loaded(qapp):
    model = _model([_entry("newer")])

    model.prepend([_entry("older")])

    assert _messages(model) == ["older", "newer"]


def test_a_prepended_chunk_keeps_its_own_order(qapp):
    """`deque.extendleft` REVERSES what it is handed.

    Without a `reversed()` to cancel it, an earlier chunk goes in backwards:
    every timestamp in it runs the wrong way, and nothing else in the viewer
    would say so -- the rows are all present and all plausible.
    """
    model = _model([_entry("d")])

    model.prepend([_entry("a"), _entry("b"), _entry("c")])

    assert _messages(model) == ["a", "b", "c", "d"]


def test_prepending_nothing_leaves_the_model_alone(qapp):
    model = _model([_entry("one")])

    model.prepend([])

    assert _messages(model) == ["one"]
    assert model.unloaded_newer == 0


# ---- the cap, sliding ---------------------------------------------------

def test_prepending_past_the_cap_evicts_the_newest(qapp):
    """The window slides. What goes is the newest, because the user is
    walking backwards and the earlier chunk is what they asked for."""
    model = _model([_entry("1"), _entry("2"), _entry("3"), _entry("4")], cap=4)

    model.prepend([_entry("a"), _entry("b")])

    assert _messages(model) == ["a", "b", "1", "2"]


def test_the_evicted_newest_records_are_counted(qapp):
    """Showing a slice out of the middle of a file without saying so is how
    someone concludes a log is clean."""
    model = _model([_entry("1"), _entry("2"), _entry("3"), _entry("4")], cap=4)

    model.prepend([_entry("a"), _entry("b")])

    assert model.unloaded_newer == 2


def test_eviction_is_not_confused_with_ageing_out(qapp):
    """`dropped` means "fell off the old end", which is the opposite end and
    a different thing to tell the user about."""
    model = _model([_entry("1"), _entry("2"), _entry("3"), _entry("4")], cap=4)

    model.prepend([_entry("a"), _entry("b")])

    assert model.dropped == 0
    assert model.unloaded_newer == 2


def test_a_prepend_that_fits_evicts_nothing(qapp):
    model = _model([_entry("1"), _entry("2")], cap=4)

    model.prepend([_entry("a")])

    assert model.unloaded_newer == 0
    assert _messages(model) == ["a", "1", "2"]


def test_a_chunk_bigger_than_the_cap_is_refused(qapp):
    """`extendleft` would keep the chunk's OLDEST end and silently discard
    both the seam and everything already loaded -- a window with a hole in
    it. One comparison is cheaper than that failure."""
    model = _model([_entry("1")], cap=3)

    with pytest.raises(ValueError):
        model.prepend([_entry(str(n)) for n in range(4)])


def test_clearing_forgets_the_eviction_count(qapp):
    model = _model([_entry("1"), _entry("2")], cap=2)
    model.prepend([_entry("a")])

    model.clear()

    assert model.unloaded_newer == 0


# ---- crossing chunk 2: folding ------------------------------------------

def test_an_orphan_continuation_folds_once_its_parent_arrives(qapp):
    """The one place backward paging and continuation folding touch.

    A tail slice can open in the middle of a 1,260-line CSI block, so its
    first records are continuations with no parent above them and each keeps
    a row of its own. Loading the earlier chunk brings the parent in, and the
    orphan must stop being an orphan.
    """
    model = _model([_cont("  (0)  Uninstall: alpha"),
                    _entry("Ending TrustedInstaller")])
    assert model.folded_count() == 0, "no parent yet, so nothing is folded"

    model.prepend([_entry("Performing 3 operations as follows:",
                          source="CSI")])

    assert model.folded_count() == 1
    rows = _messages(model)
    assert len(rows) == 2, "the orphan folded away under its new parent"
    assert rows[0].startswith("Performing 3 operations as follows:")
    assert "(+1 lines)" in rows[0]
    assert rows[1] == "Ending TrustedInstaller"


# ---- crossing two interactions ------------------------------------------

def test_a_filter_still_applies_to_a_prepended_chunk(qapp):
    """Every defect the real-log pass found lived where two interactions
    crossed. Filter, then load earlier: the new rows must obey the filter
    that is still on screen."""
    model = _model([_entry("new error", level="Error")])
    model.set_filter(levels={"Error"})

    model.prepend([_entry("old chatter"), _entry("old error", level="Error")])

    assert _messages(model) == ["old error", "new error"]


def test_a_search_needle_still_applies_to_a_prepended_chunk(qapp):
    model = _model([_entry("keep me")])
    model.set_filter(needle="keep")

    model.prepend([_entry("drop me"), _entry("keep this too")])

    assert _messages(model) == ["keep this too", "keep me"]
