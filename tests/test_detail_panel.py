from datetime import datetime
from core.types import LogEntry
from ui.detail_panel import DetailPanel


def test_show_entry():
    panel = DetailPanel()
    entry = LogEntry(
        timestamp=datetime(2026, 3, 25, 12, 0),
        source="System",
        level="Error",
        message="Something broke",
        raw={"EventID": 1001},
    )
    panel.show_entry(entry)
    assert panel.isVisible()
    content = panel._content.toPlainText()
    assert "Something broke" in content


def test_hide_panel():
    panel = DetailPanel()
    entry = LogEntry(timestamp=datetime(2026, 3, 25, 12, 0), source="Test", level="Info", message="test")
    panel.show_entry(entry)
    panel.hide_panel()
    assert not panel.isVisible()
