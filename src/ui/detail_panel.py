from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from core.types import LogEntry


class DetailPanel(QWidget):
    """Side panel showing full details of a selected log entry."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._title = QLabel("Details")
        self._title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title)

        self._content = QTextEdit()
        self._content.setReadOnly(True)
        layout.addWidget(self._content)

    def show_entry(self, entry: LogEntry) -> None:
        """Display full details of a log entry."""
        self._content.clear()
        html = f"""
        <b>Time:</b> {entry.timestamp.strftime('%Y-%m-%d %H:%M:%S')}<br>
        <b>Source:</b> {entry.source}<br>
        <b>Level:</b> {entry.level}<br>
        <hr>
        <b>Message:</b><br>
        <pre>{entry.message}</pre>
        """
        if entry.raw:
            html += "<hr><b>Raw Data:</b><br><pre>"
            for k, v in entry.raw.items():
                html += f"{k}: {v}\n"
            html += "</pre>"
        self._content.setHtml(html)
        self.setVisible(True)

    def hide_panel(self) -> None:
        self.setVisible(False)
        self._content.clear()
