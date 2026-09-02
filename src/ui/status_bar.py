from PyQt6.QtWidgets import QStatusBar, QLabel, QWidget
from core.semantic_colors import semantic


class AppStatusBar(QStatusBar):
    """Status bar showing module info and admin status."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._module_label = QLabel("")
        self._refresh_label = QLabel("")
        self._refresh_label.setStyleSheet("color: #888;")
        self._admin_label = QLabel("")
        self.addPermanentWidget(self._module_label)
        self.addPermanentWidget(self._refresh_label)
        self.addPermanentWidget(self._admin_label)

    def set_module_info(self, text: str) -> None:
        self._module_label.setText(text)

    def set_last_updated(self, timestamp: str) -> None:
        """The HH:MM:SS the current module's auto-refresh last ran."""
        self._refresh_label.setText(f"Updated {timestamp}")

    def set_admin_status(self, is_admin: bool) -> None:
        if is_admin:
            self._admin_label.setText("Admin")
            self._admin_label.setStyleSheet(
                f"color: {semantic('success')}; font-weight: bold;")
        else:
            self._admin_label.setText("User")
            self._admin_label.setStyleSheet(f"color: {semantic('warning')};")
