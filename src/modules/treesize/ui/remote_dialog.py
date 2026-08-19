"""Connect-to-a-remote-target dialog (spec 6).

One dialog for every backend: they differ in which fields matter, not in what
a connection is. A backend whose package is missing is shown disabled with the
reason, rather than being absent — "SSH is not listed" sends people hunting,
"SSH needs paramiko" tells them what to do.
"""
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout,
)

from ..targets import available_targets
from ..targets.base import Credentials


class RemoteTargetDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scan a remote target")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.backend = QComboBox(self)
        self._classes = {}
        for target_class, usable, why in sorted(
                available_targets(), key=lambda t: t[0].display_name):
            label = target_class.display_name if usable else (
                f"{target_class.display_name} — {why.split('.')[0]}")
            self.backend.addItem(label, target_class.id)
            self._classes[target_class.id] = (target_class, usable, why)
            if not usable:
                index = self.backend.count() - 1
                self.backend.model().item(index).setEnabled(False)
        form.addRow("Type:", self.backend)

        self.host = QLineEdit(self)
        self.host.setPlaceholderText("hostname, or https://host/dav for WebDAV")
        form.addRow("Host:", self.host)

        self.port = QSpinBox(self)
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("default")
        form.addRow("Port:", self.port)

        self.username = QLineEdit(self)
        form.addRow("User:", self.username)

        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.password)

        self.root = QLineEdit(self)
        self.root.setText("/")
        form.addRow("Path:", self.root)
        layout.addLayout(form)

        note = QLabel(
            "Credentials are used for this scan only and are not stored.",
            self)
        note.setObjectName("optionsNote")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self):
        """(target instance, label) for the chosen backend, or (None, reason)."""
        target_id = self.backend.currentData()
        target_class, usable, why = self._classes[target_id]
        if not usable:
            return None, why
        credentials = Credentials(
            host=self.host.text().strip(),
            port=self.port.value(),
            username=self.username.text().strip(),
            password=self.password.text(),
            root=self.root.text().strip() or "/",
        )
        if not credentials.host:
            return None, "A host is required."
        label = f"{target_class.display_name}: {credentials.host}{credentials.root}"
        return target_class(credentials), label
