"""QuickCleanupModule — dashboard-style cleanup with pie chart and auto-refresh."""
from typing import Optional

from PyQt6.QtWidgets import QWidget

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from modules.ui.components.quick_cleanup_tab import QuickCleanupTab, ADVANCED_CATEGORIES


class QuickCleanupModule(BaseModule):
    name = "Quick Cleanup"
    icon = "⚡"
    description = "One-click cleanup dashboard with space analysis and smart cleaning"
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._tab: Optional[QuickCleanupTab] = None

    def create_widget(self) -> QWidget:
        self._tab = QuickCleanupTab()
        self._tab.build(advanced_categories=ADVANCED_CATEGORIES)
        return self._tab

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        if self._tab is not None:
            self._tab.scan()

    def refresh_data(self) -> None:
        if self._tab is not None:
            self._tab.scan()

    def on_deactivate(self) -> None:
        if self._tab is not None:
            self._tab.stop_auto_refresh()
            self._tab.cancel()

    def on_stop(self) -> None:
        if self._tab is not None:
            self._tab.cancel()

    def get_refresh_interval(self) -> Optional[int]:
        """Auto-refresh every 60 seconds."""
        return 60_000
