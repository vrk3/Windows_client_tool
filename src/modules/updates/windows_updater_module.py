from dataclasses import dataclass, field
from typing import List, Callable, Optional
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
import logging

logger = logging.getLogger(__name__)


@dataclass
class WindowsUpdate:
    kb: str
    title: str
    classification: str
    size_mb: float
    release_date: str
    identity: Optional['WindowsUpdate'] = None


def fetch_pending_updates() -> List[WindowsUpdate]:
    """Fetch pending Windows updates using Windows Update API."""
    import win32com.client
    updates = []
    try:
        session = win32com.client.Dispatch("Microsoft.Update.Session")
        searcher = session.CreateUpdateSearcher()
        result = searcher.Search("IsInstalled=0 and IsHidden=0")
        for i in range(result.Updates.Count):
            u = result.Updates.Item(i)
            kb_list = [u.KBArticleIDs.Item(j) for j in range(u.KBArticleIDs.Count)]
            kb = ", ".join(f"KB{k}" for k in kb_list) if kb_list else "N/A"
            cats = [u.Categories.Item(j).Name for j in range(u.Categories.Count)]
            classification = cats[0] if cats else "Unknown"
            try:
                size_mb = u.MaxDownloadSize / (1024 * 1024)
            except Exception:
                size_mb = 0.0
            try:
                release_date = str(u.LastDeploymentChangeTime)[:10]
            except Exception:
                release_date = "Unknown"
            updates.append(WindowsUpdate(
                kb=kb, title=u.Title, classification=classification,
                size_mb=size_mb, release_date=release_date, identity=u,
            ))
    except Exception as e:
        logger.error("Failed to query Windows Updates: %s", e)
    return updates


def install_updates(updates: List[WindowsUpdate], output_cb: Callable[[str], None]) -> None:
    """Install updates."""
    import win32com.client
    try:
        session = win32com.client.Dispatch("Microsoft.Update.Session")
        downloader = session.CreateUpdateDownloader()
        installer = session.CreateUpdateInstaller()

        coll = win32com.client.Dispatch("Microsoft.Update.UpdateColl")
        for u in updates:
            if u.identity is not None:
                coll.Add(u.identity)

        if coll.Count == 0:
            output_cb("No updates to install.")
            return

        output_cb(f"Downloading {coll.Count} update(s)...")
        downloader.Updates = coll
        dl_result = downloader.Download()
        output_cb(f"Download result: {dl_result.ResultCode}")

        output_cb("Installing updates...")
        installer.Updates = coll
        install_result = installer.Install()
        output_cb(f"Install result: {install_result.ResultCode}")
        if install_result.RebootRequired:
            output_cb("Reboot required to complete installation.")
    except Exception as e:
        output_cb(f"Error: {e}")


class WindowsUpdater(BaseModule):
    name = "Windows Update"
    icon = "🔄"
    description = "Check for and install Windows updates."
    requires_admin = True
    group = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._updates = fetch_pending_updates()

    def create_widget(self):
        from PyQt6.QtWidgets import QVBoxLayout, QTableWidget, QPushButton, QGroupBox, QLabel, QWidget, QTableWidgetItem
        from PyQt6.QtCore import Qt

        widget = QWidget()
        layout = QVBoxLayout(widget)

        btn_check = QPushButton("Check for Updates")
        btn_check.clicked.connect(self._check_updates)
        layout.addWidget(btn_check)

        self._updates_table = QTableWidget()
        self._updates_table.setColumnCount(4)
        self._updates_table.setHorizontalHeaderLabels(["KB", "Title", "Classification", "Size"])
        layout.addWidget(self._updates_table)

        btn_install = QPushButton("Install Selected")
        btn_install.clicked.connect(self._install_selected)
        layout.addWidget(btn_install)

        self._populate_table()
        return widget

    def _populate_table(self):
        self._updates_table.setRowCount(len(self._updates))
        for i, update in enumerate(self._updates):
            self._updates_table.setItem(i, 0, QTableWidgetItem(update.kb))
            self._updates_table.setItem(i, 1, QTableWidgetItem(update.title))
            self._updates_table.setItem(i, 2, QTableWidgetItem(update.classification))
            self._updates_table.setItem(i, 3, QTableWidgetItem(f"{update.size_mb:.1f} MB"))

    def _check_updates(self):
        self._updates = fetch_pending_updates()
        self._populate_table()

    def _install_selected(self):
        # Get selected rows
        selected_rows = [self._updates_table.row(i) for i in range(self._updates_table.rowCount()) if self._updates_table.row(i).isSelected()]
        if not selected_rows:
            return
        updates_to_install = [self._updates[i] for i in selected_rows]
        if updates_to_install:
            self._output_cb = self._get_output_cb()
            install_updates(updates_to_install, self._output_cb or print)