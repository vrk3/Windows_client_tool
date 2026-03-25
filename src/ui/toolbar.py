from PyQt6.QtWidgets import QToolBar, QWidget


class DynamicToolbar(QToolBar):
    """Toolbar that updates actions based on the active module."""

    def __init__(self, parent: QWidget = None):
        super().__init__("Main Toolbar", parent)
        self.setMovable(False)
        self._module_actions = []

    def set_module_actions(self, actions: list) -> None:
        """Replace module-specific actions."""
        for action in self._module_actions:
            self.removeAction(action)
        self._module_actions = list(actions)
        for action in self._module_actions:
            self.addAction(action)
