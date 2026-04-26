# src/ui/main_window.py
import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QStackedWidget, QVBoxLayout, QWidget,
)

from core.admin_utils import is_admin, restart_as_admin
from core.base_module import BaseModule
from ui.sidebar_nav import SidebarNav
from ui.status_bar import AppStatusBar
from ui.toolbar import DynamicToolbar
from ui.search_bar import SearchBar
from ui.filter_panel import FilterPanel
from ui.search_results import SearchResultsTable
from ui.notification_tray import SystemTrayManager

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Application shell: SidebarNav + QStackedWidget, toolbar, menu, status bar."""

    def __init__(self, app_instance):
        super().__init__()
        self._app = app_instance
        self.setWindowTitle("Windows 11 Tweaker & Optimizer")
        self._restore_window_size()

        self._module_map: Dict[str, BaseModule] = {}
        self._module_widgets: Dict[str, QWidget] = {}
        self._active_module: Optional[BaseModule] = None
        self._module_refresh_timers: Dict[str, QTimer] = {}
        self._auto_refresh_paused: bool = self._app.config.get(
            "app.auto_refresh_paused", False
        )
        self._minimize_paused: bool = False  # True if WE paused due to window hide

        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        if not is_admin():
            root_layout.addWidget(self._create_admin_banner())

        self._sidebar = SidebarNav()
        self._sidebar.set_admin(is_admin())
        self._stack = QStackedWidget()

        # Restore sidebar collapsed state
        saved_collapsed = self._app.config.get("app.sidebar_collapsed", False)
        if saved_collapsed:
            self._sidebar._toggle_collapse()

        # Persist sidebar collapsed state when it changes
        self._sidebar.collapsed_changed.connect(
            lambda collapsed: self._app.config.set("app.sidebar_collapsed", collapsed)
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(self._stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 1200])
        root_layout.addWidget(splitter)

        self._search_results = SearchResultsTable(self)
        self._search_results.setVisible(False)
        self._search_results.result_activated.connect(self._on_result_activated)
        root_layout.addWidget(self._search_results)

        self.setCentralWidget(central)

        self._toolbar = DynamicToolbar(self)
        self.addToolBar(self._toolbar)
        self._search_bar = SearchBar(self)
        self._search_bar.search_requested.connect(self._on_search)
        self._search_bar.filter_toggled.connect(self._on_filter_toggled)
        self._toolbar.addWidget(self._search_bar)

        pause_text = "\u23f8 Pause Refresh" if not self._auto_refresh_paused else "\u25b6 Resume Refresh"
        self._pause_refresh_action = QAction(pause_text, self)
        self._pause_refresh_action.triggered.connect(self._toggle_auto_refresh_pause)
        self._toolbar.addAction(self._pause_refresh_action)

        self._filter_panel = FilterPanel(self)
        self._filter_panel.setVisible(False)
        root_layout.insertWidget(root_layout.indexOf(splitter), self._filter_panel)

        self._status_bar = AppStatusBar(self)
        self.setStatusBar(self._status_bar)
        self._status_bar.set_admin_status(is_admin())

        self._setup_menus()
        self._setup_shortcuts()
        self._setup_tray()
        self._sidebar.module_selected.connect(self._on_module_selected)
        self._schedule_update_check()
        self._show_module_warnings()

    def _restore_window_size(self) -> None:
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

    def _show_module_warnings(self) -> None:
        failed = self._app.module_registry.failed_modules
        if not failed:
            return
        names = ", ".join(m.name for m in failed)
        QMessageBox.warning(
            self,
            "Some Modules Failed to Load",
            f"The following modules failed to start and are disabled:\n\n"
            f"{names}\n\nCheck the application log for details.",
        )

    def _on_restart_as_admin(self) -> None:
        reply = QMessageBox.question(
            self, "Restart as Administrator",
            "The application will restart with elevated privileges. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            restart_as_admin()

    def register_module(self, module: BaseModule) -> None:
        """Register a module: create its widget, add to sidebar and stack."""
        enabled = module not in self._app.module_registry.disabled_modules
        if enabled:
            widget = module.create_widget()
        else:
            placeholder = QLabel(
                f"⚠️ {module.name} requires administrator privileges.\n\n"
                "Restart the application as Administrator to enable this module."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setWordWrap(True)
            widget = placeholder
        self._stack.addWidget(widget)
        self._module_map[module.name] = module
        self._module_widgets[module.name] = widget

        self._sidebar.add_module(
            group=module.group,
            name=module.name,
            icon=getattr(module, "icon", ""),
            display=module.name,
            requires_admin=module.requires_admin,
        )

        # Auto-select first enabled module
        if self._active_module is None and enabled:
            self._sidebar.select(module.name)
            self._active_module = module
            self._stack.setCurrentWidget(widget)
            try:
                module.on_activate()
            except Exception:
                logger.exception("Error activating first module %s", module.name)

    # Backward-compat alias (old main.py used add_module_tab)
    def add_module_tab(self, module: BaseModule, enabled: bool = True) -> None:
        self.register_module(module)

    def _on_module_selected(self, name: str) -> None:
        # Stop previous module's refresh timer
        if self._active_module is not None:
            prev_name = self._active_module.name
            if prev_name in self._module_refresh_timers:
                self._module_refresh_timers[prev_name].stop()
                del self._module_refresh_timers[prev_name]
            try:
                self._active_module.on_deactivate()
            except Exception:
                logger.exception("Error deactivating %s", self._active_module.name)

        module = self._module_map.get(name)
        if module is None:
            return
        self._active_module = module
        widget = self._module_widgets.get(name)
        if widget is not None:
            self._stack.setCurrentWidget(widget)
        try:
            module.on_activate()
        except Exception:
            logger.exception("Error activating %s", name)

        # Start auto-refresh timer if configured and not paused
        interval = module.get_refresh_interval()
        if interval is not None and not self._auto_refresh_paused:
            self._start_module_refresh_timer(module, interval)

        self._toolbar.set_module_actions(module.get_toolbar_actions())
        self._status_bar.set_module_info(module.get_status_info())

    def _start_module_refresh_timer(self, module: BaseModule, interval: int) -> None:
        """Start an auto-refresh QTimer for a module."""
        timer = QTimer()
        timer.setInterval(interval)
        refresh_method = getattr(module, "refresh_data", None) or module.on_activate
        timer.timeout.connect(refresh_method)
        timer.start()
        self._module_refresh_timers[module.name] = timer

    def hideEvent(self, event):
        """Auto-pause all refresh timers when window is hidden/minimized."""
        if not self._auto_refresh_paused:
            self._minimize_paused = True
            for timer in self._module_refresh_timers.values():
                timer.stop()

    def showEvent(self, event):
        """Resume refresh timers when window becomes visible again."""
        if self._minimize_paused:
            self._minimize_paused = False
            for timer in self._module_refresh_timers.values():
                timer.start()

    def _toggle_auto_refresh_pause(self) -> None:
        """Globally pause or resume all module auto-refresh timers."""
        self._auto_refresh_paused = not self._auto_refresh_paused
        self._app.config.set("app.auto_refresh_paused", self._auto_refresh_paused)

        if self._auto_refresh_paused:
            # Stop all active timers
            for timer in self._module_refresh_timers.values():
                timer.stop()
            self._pause_refresh_action.setText("\u25b6 Resume Refresh")
        else:
            # Restart timer for current module
            module = self._active_module
            if module is not None:
                interval = module.get_refresh_interval()
                if interval is not None:
                    # Stop any existing timer before starting a new one
                    if module.name in self._module_refresh_timers:
                        self._module_refresh_timers[module.name].stop()
                        del self._module_refresh_timers[module.name]
                    self._start_module_refresh_timer(module, interval)
            self._pause_refresh_action.setText("\u23f8 Pause Refresh")

    def _setup_menus(self) -> None:
        menu_bar = self.menuBar()

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

        tools_menu = menu_bar.addMenu("&Tools")
        restore_action = QAction("&Restore Manager...", self)
        restore_action.triggered.connect(self._open_restore_manager)
        tools_menu.addAction(restore_action)

        view_menu = menu_bar.addMenu("&View")
        theme_action = QAction("Toggle &Theme", self)
        theme_action.triggered.connect(self._toggle_theme)
        view_menu.addAction(theme_action)

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("F5"), self).activated.connect(self._refresh_current)
        QShortcut(QKeySequence("Ctrl+F"), self).activated.connect(
            self._search_bar.focus_search)
        QShortcut(QKeySequence("Ctrl+Shift+F"), self).activated.connect(
            self._search_bar.focus_search_with_filters)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._clear_search)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._open_command_palette)

    def _setup_tray(self) -> None:
        from PyQt6.QtWidgets import QStyle
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._tray_manager = SystemTrayManager(self, icon)
        self._tray_manager.show()
        self._tray_manager.connect_activated(self._on_tray_activated)

    def _on_tray_activated(self, reason) -> None:
        from PyQt6.QtWidgets import QSystemTrayIcon
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()
                self.activateWindow()

    def _open_command_palette(self) -> None:
        from ui.command_palette import CommandPalette
        modules = list(self._module_map.values())
        palette = CommandPalette(modules, self._navigate_to_module, self)
        # Centre near top of main window
        geo = self.geometry()
        pw = palette.sizeHint().width() or 480
        x = geo.x() + (geo.width() - pw) // 2
        y = geo.y() + 80
        palette.move(x, y)
        palette.exec()

    def _navigate_to_module(self, name: str) -> None:
        self._sidebar.select(name)
        self._on_module_selected(name)

    def _schedule_update_check(self) -> None:
        """Run the update check once in the background 3 seconds after startup."""
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(3000, self._run_update_check)

    def _run_update_check(self) -> None:
        from core.worker import Worker
        from core.update_checker import UpdateChecker
        from modules.about.about_module import _APP_VERSION
        _GITHUB_REPO = "your-user/windows-client-tool"  # update when published

        def _check(_w):
            return UpdateChecker(_GITHUB_REPO, _APP_VERSION).check()

        worker = Worker(_check)
        worker.signals.result.connect(self._on_update_result)
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(worker)

    def _on_update_result(self, result) -> None:
        if result.error or not result.update_available:
            return
        self._tray_manager.show_balloon(
            "Update Available",
            f"Version {result.latest_version} is available. "
            f"Current: {result.current_version}",
        )
        logger.info(
            "Update available: %s → %s (%s)",
            result.current_version, result.latest_version, result.release_url,
        )

    def show_notification(self, title: str, message: str) -> None:
        """Public helper for modules to show a tray balloon notification."""
        self._tray_manager.show_balloon(title, message)

    def _refresh_current(self) -> None:
        if self._active_module:
            try:
                self._active_module.on_activate()
            except Exception:
                logger.exception("Error refreshing %s", self._active_module.name)

    def _open_settings(self) -> None:
        from ui.settings_dialog import SettingsDialog
        SettingsDialog(self._app, self).exec()

    def _open_restore_manager(self) -> None:
        try:
            from ui.restore_manager import RestoreManagerDialog
            RestoreManagerDialog(self._app, self).exec()
        except ImportError:
            QMessageBox.information(self, "Coming Soon",
                                    "Restore Manager will be available in a future update.")

    def _toggle_theme(self) -> None:
        new_theme = self._app.theme.toggle()
        self._app.config.set("app.theme", new_theme)

    def _on_search(self, text: str, regex: bool) -> None:
        if not text.strip():
            self._search_results.setVisible(False)
            return
        query = self._filter_panel.build_query(text, regex)
        results = self._app.search.execute(query)
        self._search_results.set_results(results)
        self._search_results.setVisible(bool(results))
        self._status_bar.showMessage(
            f"Search: {len(results)} result(s) for '{text}'"
        )

    def _on_filter_toggled(self, expanded: bool) -> None:
        self._filter_panel.setVisible(expanded)

    def _on_result_activated(self, result) -> None:
        from ui.search_result_detail import SearchResultDetail
        SearchResultDetail(result, self).exec()

    def _clear_search(self) -> None:
        self._search_bar.clear()
        self._search_results.setVisible(False)
        self._filter_panel.setVisible(False)

    def closeEvent(self, event) -> None:
        # Stop all refresh timers
        for timer in self._module_refresh_timers.values():
            timer.stop()
        self._module_refresh_timers.clear()

        if self._app.config.get("app.minimize_to_tray", False):
            event.ignore()
            self.hide()
            self._tray_manager.show_balloon(
                "Still Running",
                "Windows Tweaker is minimized to the tray. Double-click to restore.",
            )
            return
        size = self.size()
        self._app.config.set("app.window_size", [size.width(), size.height()])
        self._app.shutdown()
        event.accept()
