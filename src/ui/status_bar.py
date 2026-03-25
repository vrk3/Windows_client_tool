from PyQt6.QtWidgets import QStatusBar, QLabel, QWidget


class AppStatusBar(QStatusBar):
    """Status bar showing module info and admin status."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._module_label = QLabel("")
        self._admin_label = QLabel("")
        self.addPermanentWidget(self._module_label)
        self.addPermanentWidget(self._admin_label)

    def set_module_info(self, text: str) -> None:
        self._module_label.setText(text)

    def set_admin_status(self, is_admin: bool) -> None:
        if is_admin:
            self._admin_label.setText("Admin")
            self._admin_label.setStyleSheet("color: #4ec9b0; font-weight: bold;")
        else:
            self._admin_label.setText("User")
            self._admin_label.setStyleSheet("color: #ce9178;")
