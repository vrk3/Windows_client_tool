from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QWidget
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QPalette, QColor


class ErrorBanner(QWidget):
    """Dismissible error banner widget for module-level error display."""
    dismissed = pyqtSignal()

    def __init__(self, message: str = "", parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QWidget {
                background: #5c1a1a;
                border: 1px solid #c42b1c;
                border-radius: 4px;
            }
        """)
        self.setMaximumHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self._label = QLabel(f"\u26a0 {message}" if message else "")
        self._label.setStyleSheet("color: #f48771; font-size: 12px;")
        layout.addWidget(self._label)
        layout.addStretch()
        close_btn = QPushButton("\u00d7")
        close_btn.setStyleSheet(
            "background: transparent; color: #888; border: none; font-size: 16px; padding: 0 4px;"
        )
        close_btn.clicked.connect(self.hide)
        close_btn.clicked.connect(self.dismissed.emit)
        layout.addWidget(close_btn)
        self.hide()

    def set_error(self, message: str) -> None:
        """Show the banner with the given error message."""
        self._label.setText(f"\u26a0 {message}")
        self.show()

    def clear(self) -> None:
        """Hide the banner without emitting dismissed."""
        self.hide()
