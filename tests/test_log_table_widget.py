from datetime import datetime
from core.types import LogEntry
from ui.log_table_widget import LogTableWidget


def test_set_entries():
    widget = LogTableWidget()
    entries = [
        LogEntry(timestamp=datetime(2026, 3, 25, 12, 0), source="System", level="Error", message="Disk failure"),
        LogEntry(timestamp=datetime(2026, 3, 25, 12, 1), source="App", level="Info", message="Started"),
    ]
    widget.set_entries(entries)
    assert len(widget.get_entries()) == 2
    assert widget._status.text() == "2 entries"


def test_clear_entries():
    widget = LogTableWidget()
    entries = [
        LogEntry(timestamp=datetime(2026, 3, 25, 12, 0), source="Test", level="Warning", message="warn"),
    ]
    widget.set_entries(entries)
    widget.clear()
    assert len(widget.get_entries()) == 0
    assert widget._status.text() == "0 entries"


def test_append_entries():
    widget = LogTableWidget()
    e1 = [LogEntry(timestamp=datetime(2026, 3, 25, 12, 0), source="A", level="Info", message="first")]
    e2 = [LogEntry(timestamp=datetime(2026, 3, 25, 12, 1), source="B", level="Error", message="second")]
    widget.set_entries(e1)
    widget.append_entries(e2)
    assert len(widget.get_entries()) == 2
    assert widget._status.text() == "2 entries"
