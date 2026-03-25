from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, List, Optional
from PyQt6.QtWidgets import QWidget

if TYPE_CHECKING:
    from core.search_provider import SearchProvider

class BaseModule(ABC):
    name: str
    icon: str
    description: str
    requires_admin: bool

    def __init__(self):
        self._workers: List = []
        self.app = None

    @abstractmethod
    def create_widget(self) -> QWidget: ...
    @abstractmethod
    def on_activate(self) -> None: ...
    @abstractmethod
    def on_deactivate(self) -> None: ...
    @abstractmethod
    def on_start(self, app) -> None: ...
    @abstractmethod
    def on_stop(self) -> None: ...

    def get_config_schema(self) -> dict:
        return {}
    def get_toolbar_actions(self) -> list:
        return []
    def get_menu_actions(self) -> list:
        return []
    def get_status_info(self) -> str:
        return ""
    def get_search_provider(self) -> Optional["SearchProvider"]:
        return None
    def cancel_all_workers(self) -> None:
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()
