from PyQt6.QtWidgets import QWidget, QLabel
from core.base_module import BaseModule

class StubModule(BaseModule):
    name = "Stub"
    icon = ""
    description = "A stub module"
    requires_admin = False
    def create_widget(self):
        return QLabel("stub")
    def on_activate(self):
        pass
    def on_deactivate(self):
        pass
    def on_start(self, app):
        self.app = app
    def on_stop(self):
        pass

def test_stub_module_can_be_instantiated():
    mod = StubModule()
    assert mod.name == "Stub"
    assert mod.requires_admin is False

def test_create_widget_returns_qwidget():
    assert isinstance(StubModule().create_widget(), QWidget)

def test_default_search_provider_is_none():
    assert StubModule().get_search_provider() is None

def test_default_toolbar_actions_is_empty():
    assert StubModule().get_toolbar_actions() == []

def test_default_menu_actions_is_empty():
    assert StubModule().get_menu_actions() == []

def test_cancel_all_workers():
    mod = StubModule()
    class FakeWorker:
        def __init__(self):
            self.cancelled = False
        def cancel(self):
            self.cancelled = True
    w1, w2 = FakeWorker(), FakeWorker()
    mod._workers.append(w1)
    mod._workers.append(w2)
    mod.cancel_all_workers()
    assert w1.cancelled
    assert w2.cancelled
    assert mod._workers == []


def test_require_admin_returns_true_when_elevated(monkeypatch):
    mod = StubModule()
    monkeypatch.setattr("core.admin_utils.is_admin", lambda: True)
    assert mod.require_admin() is True


def test_require_admin_blocks_and_explains_when_unelevated(monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    mod = StubModule()
    monkeypatch.setattr("core.admin_utils.is_admin", lambda: False)
    monkeypatch.setattr(
        QMessageBox, "warning",
        lambda *a, **k: QMessageBox.StandardButton.Cancel,
    )
    assert mod.require_admin() is False
