"""TreeSize module (spec 9).

`requires_admin = False` deliberately: the walk fallback keeps the module fully
functional unelevated, and the Home tab's *Start as administrator* button plus
a status-bar notice offer the fast path when it would help.
"""
import ctypes
import logging
from typing import Optional

from PyQt6.QtWidgets import QWidget

from core.base_module import BaseModule
from core.module_groups import ModuleGroup

from modules.treesize.ui.shell import TreeSizeShell
from modules.treesize.ui.theme import apply_theme

logger = logging.getLogger(__name__)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class TreeSizeModule(BaseModule):
    name = "TreeSize"
    icon = "📊"
    description = "Disk space analysis: what is using the drive, and where"
    requires_admin = False
    group = ModuleGroup.TOOLS

    def __init__(self) -> None:
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._shell: Optional[TreeSizeShell] = None
        self._last_summary = "No scan yet"

    def create_widget(self) -> QWidget:
        self._shell = TreeSizeShell()
        # The sheet is applied to this module's root widget, so it scopes to
        # the pane by descent and leaves every other module's styling alone.
        apply_theme(self._shell)
        self._shell.scan_finished.connect(self._on_scan_finished)
        # Elevation only changes which engine is chosen, never whether the
        # module works, so it is a note rather than a gate.
        self._shell.ribbon.set_enabled("tools.admin", not _is_admin())
        self._widget = self._shell
        return self._widget

    def on_start(self, app) -> None:
        self._app = app

    def on_activate(self) -> None:
        if self._shell is not None:
            self._shell.drive_list.refresh()

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def cancel_all_workers(self) -> None:
        if self._shell is not None:
            self._shell.stop_scan()

    def get_status_info(self) -> str:
        return self._last_summary

    def _on_scan_finished(self, result) -> None:
        from modules.treesize.ui.formatting import format_bytes, format_count
        state = "" if result.complete else " (incomplete)"
        self._last_summary = (
            f"{format_bytes(result.store.size[result.root])} across "
            f"{format_count(result.node_count)} nodes via {result.engine}{state}")
