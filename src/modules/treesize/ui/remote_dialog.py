"""Connect-to-a-remote-target dialog (spec 6).

One dialog for every backend: they differ in which fields matter, not in what
a connection is. So the fields are relabelled and hidden per backend from the
target's own `form_labels` — "Host" is wrong for a bucket and meaningless for
a mailbox, and a Port box on an S3 connection is not a harmless extra: it
invites a value that goes nowhere.

A backend whose package is missing is shown disabled with the reason, rather
than being absent — "SSH is not listed" sends people hunting, "SSH needs
paramiko" tells them what to do.
"""
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QLineEdit, QSpinBox, QVBoxLayout,
)

from ..targets import available_targets
from ..targets.base import FORM_FIELDS, Credentials
from ..targets.credential_store import CredentialStore

PLACEHOLDERS = {
    "ssh": {"host": "hostname or IP"},
    "webdav": {"host": "https://host/dav"},
    "s3": {"host": "my-bucket", "root": "logs/ (blank for the whole bucket)"},
    "azure": {"host": "https://account.blob.core.windows.net"},
    "gdrive": {"password": "OAuth access token"},
    "sharepoint": {"username": "b!xxxxxxxx", "password": "Bearer token"},
    "outlook": {"host": "leave blank for the default mailbox"},
}


class RemoteTargetDialog(QDialog):
    def __init__(self, parent=None, credential_store=None) -> None:
        super().__init__(parent)
        self.credential_store = credential_store or CredentialStore()
        self.setWindowTitle("Scan a remote target")
        self.setMinimumWidth(440)
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
        self.host.editingFinished.connect(self.recall_password)

        self.port = QSpinBox(self)
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText("default")

        self.username = QLineEdit(self)
        self.username.editingFinished.connect(self.recall_password)

        self.password = QLineEdit(self)
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.root = QLineEdit(self)
        self.root.setText("/")

        # Explicit label widgets rather than the strings QFormLayout would
        # make for us: a row cannot be hidden or relabelled without a handle
        # on the label itself.
        self._labels: dict[str, QLabel] = {}
        for field in FORM_FIELDS:
            label = QLabel("", self)
            self._labels[field] = label
            form.addRow(label, getattr(self, field))

        # Opt-in: connecting once is not consent to keep the secret.
        self.remember = QCheckBox(
            "Remember this password in Windows Credential Manager", self)
        form.addRow("", self.remember)
        layout.addLayout(form)

        note = QLabel(
            "Passwords are kept in Windows Credential Manager when you ask "
            "for them to be, and never written to a settings file. Unticking "
            "the box forgets a password that was stored earlier.",
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

        self.backend.currentIndexChanged.connect(self._on_backend_changed)
        self._select_first_usable()
        self._apply_form()

    # -- backend selection -----------------------------------------------

    def _select_first_usable(self) -> None:
        """Open on something the user can actually proceed with.

        Backends sort alphabetically and AWS S3 comes first, so without this
        the dialog opens on a greyed-out entry and looks broken before the
        user has touched it.
        """
        for index in range(self.backend.count()):
            if self._classes[self.backend.itemData(index)][1]:
                self.backend.setCurrentIndex(index)
                return

    def select_backend(self, target_id: str) -> bool:
        index = self.backend.findData(target_id)
        if index < 0:
            return False
        self.backend.setCurrentIndex(index)
        self._apply_form()
        return True

    def _on_backend_changed(self) -> None:
        self._apply_form()
        self.recall_password()

    def current_class(self):
        return self._classes[self.backend.currentData()][0]

    # -- the per-backend form --------------------------------------------

    def label_for(self, field: str) -> QLabel:
        return self._labels[field]

    def row_is_used(self, field: str) -> bool:
        """False when the chosen backend has no use for the field."""
        return self.current_class().form_labels.get(field) is not None

    def required_fields(self) -> tuple:
        return tuple(self.current_class().required_fields)

    def _apply_form(self) -> None:
        target_class = self.current_class()
        placeholders = PLACEHOLDERS.get(target_class.id, {})
        for field in FORM_FIELDS:
            caption = target_class.form_labels.get(field)
            editor = getattr(self, field)
            used = caption is not None
            self._labels[field].setText(f"{caption}:" if used else "")
            self._labels[field].setVisible(used)
            editor.setVisible(used)
            if hasattr(editor, "setPlaceholderText"):
                editor.setPlaceholderText(placeholders.get(field, ""))
        # A backend with no password field has nothing to remember.
        self.remember.setVisible(self.row_is_used("password"))
        self._retune_root_default(target_class)

    def _retune_root_default(self, target_class) -> None:
        """"/" is a sensible default path and a nonsense default prefix.

        Object keys do not begin with a slash, so a prefix of "/" matches
        nothing at all -- a scan that comes back empty and looks like an
        authentication problem. Only an untouched default is changed; what
        the user typed survives a change of backend.
        """
        caption = (target_class.form_labels.get("root") or "").lower()
        current = self.root.text().strip()
        if "prefix" in caption:
            if current == "/":
                self.root.setText("")
        elif caption and not current:
            self.root.setText("/")

    # -- credentials ------------------------------------------------------

    def recall_password(self) -> None:
        """Offer back a stored password for this backend, host and user.

        A password already typed into the box wins: overwriting it with a
        stale stored secret is how a rotated password turns into an auth
        failure nobody can explain.
        """
        host = self.host.text().strip()
        if not host or self.password.text():
            return
        target_id = self.backend.currentData()
        found = self.credential_store.load(
            target_id, host, self.username.text().strip())
        if not found:
            return
        username, secret = found
        if username and not self.username.text().strip():
            self.username.setText(username)
        self.password.setText(secret)
        self.remember.setChecked(True)

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
        missing = self._first_missing(target_class, credentials)
        if missing:
            # Named, because "a host is required" on a Google Drive
            # connection that has no host field is worse than no message.
            return None, f"{missing} is required."
        if self.remember.isChecked() and self.row_is_used("password"):
            self.credential_store.save(target_id, credentials)
        else:
            # Unticking is the only way to forget one from inside the app;
            # otherwise the user is sent to Credential Manager to clean up.
            self.credential_store.forget(
                target_id, credentials.host, credentials.username)
        return target_class(credentials), self._label_for(target_class,
                                                          credentials)

    @staticmethod
    def _first_missing(target_class, credentials):
        for field in target_class.required_fields:
            if not str(getattr(credentials, field, "") or "").strip():
                return target_class.form_labels.get(field) or field
        return None

    @staticmethod
    def _label_for(target_class, credentials) -> str:
        """What the scan is called in the tree and the path box.

        Built from whichever field identifies this backend's target, because
        "Google Drive: /" identifies nothing.
        """
        parts = [target_class.display_name]
        detail = credentials.host or credentials.username
        if detail:
            parts.append(detail)
        label = ": ".join(parts)
        root = (credentials.root or "").strip()
        if target_class.form_labels.get("root") and root not in ("", "/"):
            label = f"{label}/{root.lstrip('/')}"
        return label
