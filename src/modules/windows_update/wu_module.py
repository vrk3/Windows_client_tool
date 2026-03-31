import json
import logging
import subprocess
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (
    QHBoxLayout, QSplitter, QStackedWidget, QVBoxLayout, QWidget,
    QProgressBar, QLabel, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QPushButton, QMessageBox,
)

from ui.error_banner import ErrorBanner

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider
from core.worker import Worker
from ui.log_table_widget import LogTableWidget
from ui.detail_panel import DetailPanel
from modules.windows_update.wu_parser import WUParser
from modules.windows_update.wu_search_provider import WUSearchProvider

logger = logging.getLogger(__name__)

WU_LOG_PATH = r"C:\Windows\SoftwareDistribution\ReportingEvents.log"


class WindowsUpdateModule(BaseModule):
    name = "Windows Update"
    icon = "🔄"
    description = "Windows Update reporting events"
    requires_admin = False
    group = ModuleGroup.DIAGNOSE

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._table: Optional[LogTableWidget] = None
        self._detail: Optional[DetailPanel] = None
        self._progress: Optional[QProgressBar] = None
        self._search_provider = WUSearchProvider()
        self._error_banner: Optional[ErrorBanner] = None
        self._table_stack: Optional[QStackedWidget] = None
        self._history_table: Optional[QTableWidget] = None
        self._pause_btn: Optional[QPushButton] = None
        self._updates_paused: bool = False

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)

        # Controls row with progress bar and Pause Updates button
        controls = QHBoxLayout()
        self._pause_btn = QPushButton("Pause Updates")
        self._pause_btn.setToolTip("Toggle automatic Windows Updates on/off")
        self._pause_btn.clicked.connect(self._toggle_pause_updates)
        controls.addWidget(self._pause_btn)
        self._update_pause_btn_state()
        controls.addStretch()
        self._progress = QProgressBar()
        self._progress.setMaximumWidth(200)
        self._progress.setVisible(False)
        controls.addWidget(self._progress)
        layout.addLayout(controls)

        # Error banner
        self._error_banner = ErrorBanner(parent=self._widget)
        layout.addWidget(self._error_banner)

        # Tab widget: Log tab + History tab
        tabs = QTabWidget()
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        # -- Log tab --
        log_splitter = QSplitter()
        self._table = LogTableWidget()
        self._table.row_double_clicked.connect(self._on_row_double_clicked)
        self._table.row_selected.connect(self._on_row_selected)
        log_splitter.addWidget(self._table)

        self._detail = DetailPanel()
        log_splitter.addWidget(self._detail)
        log_splitter.setSizes([700, 300])

        self._table_stack = QStackedWidget()
        self._table_stack.addWidget(log_splitter)
        empty_page = QLabel("No data \u2014 click Refresh")
        empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_page.setStyleSheet("color: #888; font-size: 14px;")
        self._table_stack.addWidget(empty_page)
        tabs.addTab(self._table_stack, "Log")

        # -- History tab --
        history_widget = self._create_history_tab()
        tabs.addTab(history_widget, "History")

        layout.addWidget(tabs, 1)
        return self._widget

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        if self._table and len(self._table.get_entries()) == 0:
            self._load_log()

    def on_deactivate(self) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def get_toolbar_actions(self) -> list:
        actions = []
        refresh = QAction("Refresh", None)
        refresh.triggered.connect(self._load_log)
        actions.append(refresh)

        export = QAction("Export CSV", None)
        export.triggered.connect(lambda: self._table.export_csv() if self._table else None)
        actions.append(export)

        return actions

    def get_status_info(self) -> str:
        count = len(self._table.get_entries()) if self._table else 0
        paused = " [PAUSED]" if self._updates_paused else ""
        return f"Windows Update — {count} entries{paused}"

    def get_search_provider(self) -> Optional[SearchProvider]:
        return self._search_provider

    def _load_log(self) -> None:
        if self._progress:
            self._progress.setVisible(True)
            self._progress.setValue(0)

        def do_work(worker):
            parser = WUParser(WU_LOG_PATH)
            return parser.parse(progress_callback=lambda p: worker.signals.progress.emit(p))

        worker = Worker(do_work)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._on_log_loaded)
        worker.signals.error.connect(self._on_load_error)
        self._workers.append(worker)

        if self.app:
            self.app.thread_pool.start(worker)
        else:
            # Run synchronously when no app context (e.g. tests)
            worker.run()

    def _on_progress(self, value: int) -> None:
        if self._progress:
            self._progress.setValue(value)

    def _on_log_loaded(self, entries) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if self._table:
            self._table.set_entries(entries)
            self._search_provider.set_entries(entries)
            logger.info("Loaded %d Windows Update log entries", len(entries))
        if self._table_stack:
            self._table_stack.setCurrentIndex(0 if entries else 1)

    def _on_load_error(self, error_info) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if self._error_banner:
            self._error_banner.set_error(str(error_info))
        logger.error("Failed to load Windows Update log: %s", error_info)

    def _on_row_double_clicked(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)

    def _on_row_selected(self, entry) -> None:
        if self._detail:
            self._detail.show_entry(entry)

    # ------------------------------------------------------------------
    # History tab
    # ------------------------------------------------------------------

    def _create_history_tab(self) -> QWidget:
        """Build the History tab widget."""
        widget = QWidget()
        vlayout = QVBoxLayout(widget)
        vlayout.setContentsMargins(4, 4, 4, 4)

        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("Refresh History")
        hide_btn = QPushButton("Hide Selected Update")
        unhide_btn = QPushButton("Unhide Selected Update")
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(hide_btn)
        toolbar.addWidget(unhide_btn)
        toolbar.addStretch()
        vlayout.addLayout(toolbar)

        self._history_table = QTableWidget(0, 4)
        self._history_table.setHorizontalHeaderLabels(
            ["KB / HotFix ID", "Description", "Installed On", "Source"]
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._history_table.setSortingEnabled(True)
        vlayout.addWidget(self._history_table)

        refresh_btn.clicked.connect(self._load_history)
        hide_btn.clicked.connect(self._on_hide_update)
        unhide_btn.clicked.connect(self._on_unhide_update)

        return widget

    def _load_history(self) -> None:
        """Load installed hotfix history via Get-HotFix PowerShell command."""
        if self._progress:
            self._progress.setVisible(True)
            self._progress.setValue(0)

        def do_work(_worker):
            ps_script = (
                "Get-HotFix | Sort-Object InstalledOn -Descending | "
                "Select-Object HotFixID,Description,InstalledOn,Caption,Source | "
                "ConvertTo-Json -Compress -Depth 2"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True, text=True, timeout=30,
            )
            raw = result.stdout.strip()
            if not raw:
                return []
            data = json.loads(raw)
            if isinstance(data, dict):
                data = [data]
            return data

        worker = Worker(do_work)
        worker.signals.result.connect(self._on_history_loaded)
        worker.signals.error.connect(self._on_history_error)
        self._workers.append(worker)
        if self.app:
            self.app.thread_pool.start(worker)
        else:
            worker.run()

    def _on_history_loaded(self, data: list) -> None:
        if self._progress:
            self._progress.setVisible(False)
        if not self._history_table:
            return
        self._history_table.setRowCount(0)
        for entry in data:
            row = self._history_table.rowCount()
            self._history_table.insertRow(row)
            kb_id = str(entry.get("HotFixID", ""))
            desc = str(entry.get("Description", ""))
            installed_on = str(entry.get("InstalledOn", ""))
            source = str(entry.get("Source", ""))
            self._history_table.setItem(row, 0, QTableWidgetItem(kb_id))
            self._history_table.setItem(row, 1, QTableWidgetItem(desc))
            self._history_table.setItem(row, 2, QTableWidgetItem(installed_on))
            self._history_table.setItem(row, 3, QTableWidgetItem(source))
        self._history_table.resizeRowsToContents()

    def _on_history_error(self, err_str: str) -> None:
        if self._progress:
            self._progress.setVisible(False)
        logger.error("History load error: %s", err_str)

    def _on_hide_update(self) -> None:
        """Hide the selected update using wusa.exe."""
        row = self._history_table.currentRow()
        if row < 0:
            QMessageBox.warning(self._widget, "Hide Update", "Please select an update first.")
            return
        kb_item = self._history_table.item(row, 0)
        if not kb_item:
            return
        kb = kb_item.text().strip()
        if not kb:
            return
        reply = QMessageBox.question(
            self._widget, "Hide Update",
            f"Hide update {kb}? It will not be shown in Windows Update.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = subprocess.run(
            ["wusa.exe", "/hide", f"/kb:{kb}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            QMessageBox.information(self._widget, "Hide Update", f"Update {kb} has been hidden.")
            self._load_history()
        else:
            QMessageBox.critical(
                self._widget, "Hide Update",
                f"Failed to hide update {kb}.\n{result.stderr}",
            )

    def _on_unhide_update(self) -> None:
        """Unhide the selected update using wusa.exe."""
        row = self._history_table.currentRow()
        if row < 0:
            QMessageBox.warning(self._widget, "Unhide Update", "Please select an update first.")
            return
        kb_item = self._history_table.item(row, 0)
        if not kb_item:
            return
        kb = kb_item.text().strip()
        if not kb:
            return
        reply = QMessageBox.question(
            self._widget, "Unhide Update",
            f"Unhide update {kb}?",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = subprocess.run(
            ["wusa.exe", "/unhide", f"/kb:{kb}"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            QMessageBox.information(self._widget, "Unhide Update", f"Update {kb} has been unhidden.")
            self._load_history()
        else:
            QMessageBox.critical(
                self._widget, "Unhide Update",
                f"Failed to unhide update {kb}.\n{result.stderr}",
            )

    # ------------------------------------------------------------------
    # Pause Updates
    # ------------------------------------------------------------------

    def _toggle_pause_updates(self) -> None:
        """Toggle automatic Windows Updates by setting/removing a registry policy."""
        import winreg
        key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
        try:
            if self._updates_paused:
                # Resume: remove NoAutoUpdate value
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_WRITE)
                try:
                    winreg.DeleteValue(key, "NoAutoUpdate")
                except FileNotFoundError:
                    pass
                finally:
                    winreg.CloseKey(key)
                self._updates_paused = False
                QMessageBox.information(self._widget, "Windows Update", "Updates have been resumed.")
            else:
                # Pause: set NoAutoUpdate = 1
                key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)
                winreg.SetValueEx(key, "NoAutoUpdate", 0, winreg.REG_DWORD, 1)
                winreg.CloseKey(key)
                self._updates_paused = True
                QMessageBox.information(self._widget, "Windows Update", "Updates have been paused.")
        except PermissionError:
            QMessageBox.critical(
                self._widget, "Windows Update",
                "Administrator privileges are required to pause updates.",
            )
        except Exception as e:
            QMessageBox.critical(self._widget, "Windows Update", f"Error: {e}")
        self._update_pause_btn_state()

    def _update_pause_btn_state(self) -> None:
        """Check current pause state from registry and update button label."""
        import winreg
        key_path = r"SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
        self._updates_paused = False
        try:
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, winreg.KEY_READ)
            try:
                val, _ = winreg.QueryValueEx(key, "NoAutoUpdate")
                self._updates_paused = val == 1
            except FileNotFoundError:
                self._updates_paused = False
            finally:
                winreg.CloseKey(key)
        except Exception:
            self._updates_paused = False
        if self._pause_btn:
            self._pause_btn.setText("Resume Updates" if self._updates_paused else "Pause Updates")
            self._pause_btn.setStyleSheet(
                "background-color: #4caf50; color: white; font-weight: bold;"
                if self._updates_paused
                else ""
            )
