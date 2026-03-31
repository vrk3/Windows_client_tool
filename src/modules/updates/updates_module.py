import os
from typing import List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit,
    QCheckBox, QTimeEdit, QComboBox, QFormLayout, QProgressBar,
)
from PyQt6.QtCore import Qt, QThreadPool, QTime
from PyQt6.QtGui import QFont

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker, COMWorker
from core.windows_utils import is_reboot_pending
from modules.updates.winget_updater import (
    fetch_updates, install_update, install_all_updates, AppUpdate,
)
from modules.updates.windows_updater import (
    fetch_pending_updates, install_updates, WindowsUpdate,
)


# ---------------------------------------------------------------------------
# Tab 1 — Application Updates (winget)
# ---------------------------------------------------------------------------

class _AppUpdatesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._updates: List[AppUpdate] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Toolbar
        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._update_sel_btn = QPushButton("Update Selected")
        self._update_all_btn = QPushButton("Update All")
        self._update_sel_btn.setEnabled(False)
        self._update_all_btn.setEnabled(False)
        self._status_lbl = QLabel("Click Refresh to check for updates.")
        toolbar.addWidget(self._refresh_btn)
        toolbar.addWidget(self._update_sel_btn)
        toolbar.addWidget(self._update_all_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status_lbl)
        layout.addLayout(toolbar)

        # Progress bar (thin strip)
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # Updates table
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Name", "ID", "Installed", "Available", "Source"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table, 1)

        # Log output
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setFont(QFont("Consolas", 8))
        layout.addWidget(self._log)

        self._refresh_btn.clicked.connect(self._do_refresh)
        self._update_sel_btn.clicked.connect(self._do_update_selected)
        self._update_all_btn.clicked.connect(self._do_update_all)

    # ------------------------------------------------------------------
    # Worker functions — Worker passes itself as first argument, so all
    # callables passed to Worker() must accept a leading `worker` param.
    # ------------------------------------------------------------------

    def _do_refresh(self):
        self._refresh_btn.setEnabled(False)
        self._update_sel_btn.setEnabled(False)
        self._update_all_btn.setEnabled(False)
        self._status_lbl.setText("Checking for updates...")
        self._progress.setRange(0, 0)
        self._progress.show()
        self._table.setRowCount(0)

        def _fetch(worker):
            return fetch_updates()

        w = Worker(_fetch)
        w.signals.result.connect(self._on_updates)
        w.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(w)

    def _on_updates(self, updates: List[AppUpdate]):
        self._updates = updates
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._table.setRowCount(len(updates))
        for row, u in enumerate(updates):
            self._table.setItem(row, 0, QTableWidgetItem(u.name))
            self._table.setItem(row, 1, QTableWidgetItem(u.winget_id))
            self._table.setItem(row, 2, QTableWidgetItem(u.installed_version))
            self._table.setItem(row, 3, QTableWidgetItem(u.available_version))
            self._table.setItem(row, 4, QTableWidgetItem(u.source))
        self._status_lbl.setText(f"{len(updates)} update(s) available.")
        self._update_sel_btn.setEnabled(len(updates) > 0)
        self._update_all_btn.setEnabled(len(updates) > 0)

    def _on_error(self, err_str: str):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status_lbl.setText(f"Error: {err_str}")

    def _do_update_selected(self):
        selected_rows = {i.row() for i in self._table.selectedIndexes()}
        if not selected_rows:
            return
        ids = [self._updates[r].winget_id for r in selected_rows if r < len(self._updates)]
        self._run_updates(ids)

    def _do_update_all(self):
        self._refresh_btn.setEnabled(False)
        self._update_sel_btn.setEnabled(False)
        self._update_all_btn.setEnabled(False)
        self._log.clear()
        self._progress.setRange(0, 0)
        self._progress.show()

        def _run_all(worker):
            install_all_updates(lambda line: worker.signals.log_line.emit(line))
            return None

        w = Worker(_run_all)
        w.signals.log_line.connect(self._log.appendPlainText)
        w.signals.result.connect(self._on_update_done)
        w.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(w)

    def _run_updates(self, ids: List[str]):
        self._refresh_btn.setEnabled(False)
        self._update_sel_btn.setEnabled(False)
        self._update_all_btn.setEnabled(False)
        self._log.clear()
        self._progress.setRange(0, len(ids))
        self._progress.setValue(0)
        self._progress.show()

        def _run(worker):
            for i, wid in enumerate(ids):
                worker.signals.log_line.emit(f"Updating {wid}...")
                install_update(wid, lambda line: worker.signals.log_line.emit(line))
                worker.signals.progress.emit(i + 1)
            return None

        w = Worker(_run)
        w.signals.log_line.connect(self._log.appendPlainText)
        w.signals.progress.connect(self._progress.setValue)
        w.signals.result.connect(self._on_update_done)
        w.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(w)

    def _on_update_done(self, _result):
        self._refresh_btn.setEnabled(True)
        self._update_all_btn.setEnabled(True)
        self._progress.hide()
        self._do_refresh()


# ---------------------------------------------------------------------------
# Tab 2 — Windows Updates (COM)
# ---------------------------------------------------------------------------

class _WinUpdatesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._updates: List[WindowsUpdate] = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Reboot pending banner
        self._reboot_banner = QLabel("A system reboot is pending.")
        self._reboot_banner.setStyleSheet(
            "background: #FF8800; color: white; padding: 4px; font-weight: bold;"
        )
        self._reboot_banner.hide()
        layout.addWidget(self._reboot_banner)

        # Toolbar
        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._install_btn = QPushButton("Install Selected")
        self._install_btn.setEnabled(False)
        self._status_lbl = QLabel("Click Refresh to check for Windows Updates.")
        toolbar.addWidget(self._refresh_btn)
        toolbar.addWidget(self._install_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status_lbl)
        layout.addLayout(toolbar)

        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["KB", "Title", "Classification", "Size (MB)", "Released"]
        )
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table, 1)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setFont(QFont("Consolas", 8))
        layout.addWidget(self._log)

        self._refresh_btn.clicked.connect(self._do_refresh)
        self._install_btn.clicked.connect(self._do_install)

        # Check reboot on init
        try:
            if is_reboot_pending():
                self._reboot_banner.show()
        except Exception:
            pass

    def _do_refresh(self):
        self._refresh_btn.setEnabled(False)
        self._install_btn.setEnabled(False)
        self._status_lbl.setText("Searching for updates...")
        self._progress.setRange(0, 0)
        self._progress.show()
        self._table.setRowCount(0)

        def _fetch(worker):
            return fetch_pending_updates()

        w = COMWorker(_fetch)
        w.signals.result.connect(self._on_updates)
        w.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(w)

    def _on_updates(self, updates: List[WindowsUpdate]):
        self._updates = updates
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._table.setRowCount(len(updates))
        for row, u in enumerate(updates):
            self._table.setItem(row, 0, QTableWidgetItem(u.kb))
            self._table.setItem(row, 1, QTableWidgetItem(u.title))
            self._table.setItem(row, 2, QTableWidgetItem(u.classification))
            self._table.setItem(row, 3, QTableWidgetItem(f"{u.size_mb:.1f}"))
            self._table.setItem(row, 4, QTableWidgetItem(u.release_date))
        self._status_lbl.setText(f"{len(updates)} pending update(s).")
        self._install_btn.setEnabled(len(updates) > 0)
        try:
            self._reboot_banner.setVisible(is_reboot_pending())
        except Exception:
            pass

    def _on_error(self, err_str: str):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status_lbl.setText(f"Error: {err_str}")

    def _do_install(self):
        selected_rows = {i.row() for i in self._table.selectedIndexes()}
        if not selected_rows:
            return
        selected = [self._updates[r] for r in selected_rows if r < len(self._updates)]
        self._refresh_btn.setEnabled(False)
        self._install_btn.setEnabled(False)
        self._log.clear()
        self._progress.setRange(0, 0)
        self._progress.show()

        def _run(worker):
            install_updates(selected, lambda line: worker.signals.log_line.emit(line))
            return None

        w = COMWorker(_run)
        w.signals.log_line.connect(self._log.appendPlainText)
        w.signals.result.connect(self._on_install_done)
        w.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(w)

    def _on_install_done(self, _result):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        try:
            self._reboot_banner.setVisible(is_reboot_pending())
        except Exception:
            pass
        self._do_refresh()


# ---------------------------------------------------------------------------
# Tab 3 — Schedule
# ---------------------------------------------------------------------------

class _ScheduleTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._app_check = QCheckBox("Auto-check app updates (winget)")
        self._win_check = QCheckBox("Auto-check Windows updates")
        self._time_edit = QTimeEdit(QTime(9, 0))
        self._freq_combo = QComboBox()
        self._freq_combo.addItems(["Daily", "Weekly"])

        form.addRow(self._app_check)
        form.addRow(self._win_check)
        form.addRow("Check time:", self._time_edit)
        form.addRow("Frequency:", self._freq_combo)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("Save Schedule")
        self._remove_btn = QPushButton("Remove Schedule")
        self._status_lbl = QLabel("")
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._status_lbl)
        layout.addLayout(btn_row)
        layout.addStretch()

        self._save_btn.clicked.connect(self._save)
        self._remove_btn.clicked.connect(self._remove)

    def _save(self):
        import subprocess
        time_str = self._time_edit.time().toString("HH:mm")
        freq = self._freq_combo.currentText().upper()
        task_name = "WinClientTool_UpdateCheck"
        script = (
            "winget upgrade --all --silent "
            "--accept-source-agreements --accept-package-agreements"
        )
        cmd = [
            "schtasks", "/create", "/f",
            "/tn", task_name,
            "/tr", f'cmd /c "{script}"',
            "/sc", freq,
            "/st", time_str,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                self._status_lbl.setText("Schedule saved.")
            else:
                self._status_lbl.setText(f"Error: {result.stderr.strip()}")
        except Exception as e:
            self._status_lbl.setText(f"Error: {e}")

    def _remove(self):
        import subprocess
        cmd = ["schtasks", "/delete", "/f", "/tn", "WinClientTool_UpdateCheck"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                self._status_lbl.setText("Schedule removed.")
            else:
                self._status_lbl.setText(f"Error: {result.stderr.strip()}")
        except Exception as e:
            self._status_lbl.setText(f"Error: {e}")


# ---------------------------------------------------------------------------
# UpdatesModule — BaseModule entry point
# ---------------------------------------------------------------------------

class UpdatesModule(BaseModule):
    name = "Updates"
    icon = "🔄"
    description = "App and Windows update management"
    requires_admin = True
    group = ModuleGroup.TOOLS

    def create_widget(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(_AppUpdatesTab(), "App Updates")
        tabs.addTab(_WinUpdatesTab(), "Windows Updates")
        tabs.addTab(_ScheduleTab(), "Schedule")
        return tabs

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
