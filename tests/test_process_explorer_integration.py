# tests/test_process_explorer_integration.py
from unittest.mock import MagicMock
from modules.process_explorer.process_explorer_module import ProcessExplorerModule
from core.module_groups import ModuleGroup


def test_module_attributes():
    assert ProcessExplorerModule.name == "Process Explorer"
    assert ProcessExplorerModule.group == ModuleGroup.PROCESS
    assert ProcessExplorerModule.requires_admin is False


def test_module_creates_widget(qapp):
    mod = ProcessExplorerModule()
    mock_app = MagicMock()
    from PyQt6.QtCore import QThreadPool
    mock_app.thread_pool = QThreadPool.globalInstance()
    mod.on_start(mock_app)
    widget = mod.create_widget()
    assert widget is not None
    mod.on_stop()
