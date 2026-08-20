from PyQt6.QtWidgets import QMessageBox

from core.confirm import confirm_destructive


def test_confirm_destructive_yes_returns_true(monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    assert confirm_destructive(None, "Delete", "Delete 3 file(s)?") is True


def test_confirm_destructive_no_returns_false(monkeypatch):
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)
    assert confirm_destructive(None, "Delete", "Delete 3 file(s)?") is False


def test_confirm_destructive_default_button_is_no():
    box_kwargs = {}

    def fake_exec(self):
        box_kwargs["default"] = self.standardButton(self.defaultButton())
        box_kwargs["text"] = self.text()
        return QMessageBox.StandardButton.No

    orig = QMessageBox.exec
    QMessageBox.exec = fake_exec
    try:
        confirm_destructive(None, "Delete", "Delete 3 file(s)?", detail="path/to/thing")
    finally:
        QMessageBox.exec = orig

    assert box_kwargs["default"] == QMessageBox.StandardButton.No
    assert "path/to/thing" in box_kwargs["text"]
    assert "cannot be undone" in box_kwargs["text"]


def test_confirm_destructive_irreversible_false_omits_undo_text():
    captured = {}

    def fake_exec(self):
        captured["text"] = self.text()
        return QMessageBox.StandardButton.Yes

    orig = QMessageBox.exec
    QMessageBox.exec = fake_exec
    try:
        confirm_destructive(None, "Stop Service", "Stop this service?", irreversible=False)
    finally:
        QMessageBox.exec = orig

    assert "cannot be undone" not in captured["text"]
