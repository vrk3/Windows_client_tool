from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget,
    QHeaderView, QProgressBar, QLabel, QMessageBox,
)
from PyQt6.QtCore import QThreadPool

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker, COMWorker
from modules.startup_manager.startup_reader import (
    StartupEntry,
    get_registry_entries,
    set_registry_entry_enabled,
    get_startup_folder_entries,
    set_startup_folder_entry_enabled,
    get_scheduled_task_entries,
    get_service_entries,
    get_browser_extensions,
)

COLUMNS = ["Name", "Command/Path", "Status", "Notes"]


class _StartupTab(QWidget):
    def __init__(self, loader_fn, enable_fn=None, disable_fn=None,
                 use_com=False, read_only=False, parent=None):
        super().__init__(parent)
        self._loader = loader_fn
        self._enable_fn = enable_fn
        self._disable_fn = disable_fn
        self._use_com = use_com
        self._read_only = read_only
        self._entries = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._enable_btn = QPushButton("Enable")
        self._disable_btn = QPushButton("Disable")
        self._status = QLabel("")

        self._enable_btn.setEnabled(False)
        self._disable_btn.setEnabled(False)

        if self._read_only:
            self._enable_btn.hide()
            self._disable_btn.hide()

        toolbar.addWidget(self._refresh_btn)
        if not self._read_only:
            toolbar.addWidget(self._enable_btn)
            toolbar.addWidget(self._disable_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status)
        layout.addLayout(toolbar)

        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.ResizeToContents
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, 1)

        self._refresh_btn.clicked.connect(self._load)
        self._enable_btn.clicked.connect(self._enable_selected)
        self._disable_btn.clicked.connect(self._disable_selected)
        self._table.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )

    def _load(self):
        self._refresh_btn.setEnabled(False)
        self._status.setText("Loading...")
        self._progress.show()
        self._table.setRowCount(0)

        loader = self._loader
        WorkerClass = COMWorker if self._use_com else Worker
        worker = WorkerClass(lambda _w: loader())
        worker.signals.result.connect(self._on_result)
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_result(self, entries):
        self._entries = entries
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            self._table.setItem(r, 0, QTableWidgetItem(e.name))
            self._table.setItem(r, 1, QTableWidgetItem(e.command))
            self._table.setItem(
                r, 2, QTableWidgetItem("Enabled" if e.enabled else "Disabled")
            )
            self._table.setItem(r, 3, QTableWidgetItem(e.extra))
        self._status.setText(f"{len(entries)} entries")

    def _on_error(self, err):
        self._refresh_btn.setEnabled(True)
        self._progress.hide()
        self._status.setText(f"Error: {err}")

    def _on_selection_changed(self):
        has_sel = bool(self._table.selectedItems())
        self._enable_btn.setEnabled(has_sel and not self._read_only)
        self._disable_btn.setEnabled(has_sel and not self._read_only)

    def _selected_entry(self):
        rows = {i.row() for i in self._table.selectedIndexes()}
        if rows:
            r = min(rows)
            if r < len(self._entries):
                return self._entries[r]
        return None

    def _enable_selected(self):
        e = self._selected_entry()
        if e and self._enable_fn:
            try:
                self._enable_fn(e.name)
                self._status.setText(f"Enabled: {e.name}")
                self._load()
            except Exception as ex:
                self._status.setText(f"Error: {ex}")

    def _disable_selected(self):
        e = self._selected_entry()
        if e and self._disable_fn:
            reply = QMessageBox.question(
                self, "Disable Startup Item",
                f"Disable '{e.name}'?\n\nThis will prevent it from starting automatically.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            try:
                self._disable_fn(e.name)
                self._status.setText(f"Disabled: {e.name}")
                self._load()
            except Exception as ex:
                self._status.setText(f"Error: {ex}")


class StartupModule(BaseModule):
    name = "Startup Manager"
    icon = "🚀"
    description = "Manage startup programs and services"
    requires_admin = False
    group = ModuleGroup.MANAGE

    def create_widget(self) -> QWidget:
        tabs = QTabWidget()

        tabs.addTab(
            _StartupTab(
                get_registry_entries,
                enable_fn=lambda n: set_registry_entry_enabled(n, True),
                disable_fn=lambda n: set_registry_entry_enabled(n, False),
            ),
            "Registry",
        )
        tabs.addTab(
            _StartupTab(
                get_startup_folder_entries,
                enable_fn=lambda n: set_startup_folder_entry_enabled(n, True),
                disable_fn=lambda n: set_startup_folder_entry_enabled(n, False),
            ),
            "Startup Folder",
        )
        tabs.addTab(
            _StartupTab(get_scheduled_task_entries, use_com=True, read_only=True),
            "Scheduled Tasks",
        )
        tabs.addTab(
            _StartupTab(get_service_entries, read_only=True),
            "Services",
        )
        tabs.addTab(
            _StartupTab(get_browser_extensions, read_only=True),
            "Browser Extensions",
        )

        self._startup_tabs = tabs
        return tabs

    def on_activate(self) -> None:
        if hasattr(self, "_startup_tabs"):
            tab = self._startup_tabs.currentWidget()
            if hasattr(tab, "_load") and hasattr(tab, "_status") and tab._status.text() == "":
                tab._load()

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
