import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.admin_utils import is_admin, restart_as_admin
from core.base_module import BaseModule
from ui.status_bar import AppStatusBar
from ui.toolbar import DynamicToolbar
from ui.search_bar import SearchBar
from ui.filter_panel import FilterPanel
from ui.search_results import SearchResultsTable

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Application shell with tabs, toolbar, menu bar, and admin banner."""

    def __init__(self, app_instance):
        super().__init__()
        self._app = app_instance
        self.setWindowTitle("Windows 11 Tweaker & Optimizer")
        self._restore_window_size()

        # Central layout
        central = QWidget()
        self._layout = QVBoxLayout(central)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        # Admin banner
        if not is_admin():
            self._layout.addWidget(self._create_admin_banner())

        # Tab widget
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._layout.addWidget(self._tabs)

        self.setCentralWidget(central)

        # Toolbar
        self._toolbar = DynamicToolbar(self)
        self.addToolBar(self._toolbar)

        # Search bar
        self._search_bar = SearchBar(self)
        self._search_bar.search_requested.connect(self._on_search)
        self._search_bar.filter_toggled.connect(self._on_filter_toggled)
        self._toolbar.addWidget(self._search_bar)

        # Filter panel (hidden by default)
        self._filter_panel = FilterPanel(self)
        self._layout.addWidget(self._filter_panel)

        # Search results (hidden by default)
        self._search_results = SearchResultsTable(self)
        self._search_results.setVisible(False)
        self._layout.addWidget(self._search_results)

        # Status bar
        self._status_bar = AppStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.set_admin_status(is_admin())

        # Menu bar
        self._setup_menus()

        # Keyboard shortcuts
        self._setup_shortcuts()

        # Track modules per tab index
        self._tab_modules: list[BaseModule] = []
        self._active_tab_index: int = -1

    def _restore_window_size(self):
        size = self._app.config.get("app.window_size", [1400, 900])
        self.resize(size[0], size[1])

    def _create_admin_banner(self) -> QWidget:
        banner = QWidget()
        banner.setStyleSheet("background-color: #805500; padding: 4px;")
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel("Some features require administrator privileges.")
        label.setStyleSheet("color: white;")
        layout.addWidget(label)
        layout.addStretch()
        btn = QPushButton("Restart as Admin")
        btn.clicked.connect(self._on_restart_as_admin)
        layout.addWidget(btn)
        return banner

    def _on_restart_as_admin(self):
        reply = QMessageBox.question(
            self,
            "Restart as Administrator",
            "The application will restart with elevated privileges. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            restart_as_admin()

    def add_module_tab(self, module: BaseModule, enabled: bool = True) -> None:
        widget = module.create_widget()
        index = self._tabs.addTab(widget, module.name)
        self._tab_modules.append(module)
        if not enabled:
            self._tabs.setTabEnabled(index, False)
            self._tabs.setTabToolTip(index, "Requires administrator privileges")

    def _on_tab_changed(self, index: int):
        # Deactivate only the previously active module
        if 0 <= self._active_tab_index < len(self._tab_modules):
            old_mod = self._tab_modules[self._active_tab_index]
            if old_mod not in self._app.module_registry.disabled_modules:
                try:
                    old_mod.on_deactivate()
                except Exception:
                    logger.exception("Error deactivating module %s", old_mod.name)

        # Activate current
        self._active_tab_index = index
        if 0 <= index < len(self._tab_modules):
            mod = self._tab_modules[index]
            if mod not in self._app.module_registry.disabled_modules:
                try:
                    mod.on_activate()
                    self._toolbar.set_module_actions(mod.get_toolbar_actions())
                    self._status_bar.set_module_info(mod.get_status_info())
                except Exception:
                    logger.exception("Error activating module %s", mod.name)

    def _setup_menus(self):
        menu_bar = self.menuBar()

        # File menu
        file_menu = menu_bar.addMenu("&File")
        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Alt+F4"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View menu
        view_menu = menu_bar.addMenu("&View")
        theme_action = QAction("Toggle &Theme", self)
        theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(theme_action)

    def _setup_shortcuts(self):
        # Ctrl+Tab / Ctrl+Shift+Tab for tab navigation
        QShortcut(QKeySequence("Ctrl+Tab"), self).activated.connect(self._next_tab)
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self).activated.connect(self._prev_tab)

        # Ctrl+1..9 for direct tab access
        for i in range(1, 10):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            shortcut.activated.connect(lambda idx=i - 1: self._tabs.setCurrentIndex(idx))

        # F5 refresh
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_current)

        # Ctrl+F focus search
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self._search_bar.focus_search
        )
        # Ctrl+Shift+F focus search with filters
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(
            self._search_bar.focus_search_with_filters
        )
        # Escape clears search
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._clear_search)

    def _next_tab(self):
        idx = (self._tabs.currentIndex() + 1) % max(self._tabs.count(), 1)
        self._tabs.setCurrentIndex(idx)

    def _prev_tab(self):
        idx = (self._tabs.currentIndex() - 1) % max(self._tabs.count(), 1)
        self._tabs.setCurrentIndex(idx)

    def _refresh_current(self):
        # Modules can override on_activate to handle refresh
        idx = self._tabs.currentIndex()
        if 0 <= idx < len(self._tab_modules):
            mod = self._tab_modules[idx]
            mod.on_activate()

    def _open_settings(self):
        from ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self._app, self)
        dialog.exec()

    def _toggle_theme(self):
        new_theme = self._app.theme.toggle()
        self._app.config.set("app.theme", new_theme)

    def _on_search(self, text: str, regex: bool):
        if not text.strip():
            self._search_results.setVisible(False)
            return
        query = self._filter_panel.build_query(text, regex)
        results = self._app.search.execute(query)
        self._search_results.set_results(results)
        self._search_results.setVisible(True)

    def _on_filter_toggled(self, expanded: bool):
        self._filter_panel.setVisible(expanded)

    def _clear_search(self):
        self._search_bar.clear()
        self._search_results.setVisible(False)
        self._filter_panel.setVisible(False)

    def closeEvent(self, event):
        size = self.size()
        self._app.config.set("app.window_size", [size.width(), size.height()])
        self._app.shutdown()
        event.accept()
