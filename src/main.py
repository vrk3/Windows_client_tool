import logging
import sys
import os
import traceback

# Add src/ to Python path so imports like `core.event_bus` work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMessageBox

from app import App
from ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def _global_exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler — logs traceback and shows error dialog."""
    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Unhandled exception:\n%s", tb_text)

    # Show non-fatal error dialog with Copy to Clipboard
    try:
        app = QApplication.instance()
        if app:
            msg = QMessageBox()
            msg.setWindowTitle("Unexpected Error")
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setText("An unexpected error occurred. The application may continue running.")
            msg.setDetailedText(tb_text)
            copy_btn = msg.addButton("Copy to Clipboard", QMessageBox.ButtonRole.ActionRole)
            msg.addButton(QMessageBox.StandardButton.Ok)
            msg.exec()
            if msg.clickedButton() == copy_btn:
                app.clipboard().setText(tb_text)
    except Exception:
        pass  # If dialog fails, at least the log was written


def main():
    qt_app = QApplication(sys.argv)

    # Initialize App singleton (wires all core services)
    app = App()

    # Install global exception handler (after logging is set up)
    sys.excepthook = _global_exception_handler

    # Register all data modules
    from modules.dashboard.dashboard_module import DashboardModule
    from modules.perfmon.perfmon_module import PerfMonModule
    from modules.process_explorer.process_explorer_module import ProcessExplorerModule
    from modules.tweaks.tweaks_module import TweaksModule
    from modules.cleanup.cleanup_module import CleanupModule
    from modules.cleanup.quick_cleanup_module import QuickCleanupModule
    from modules.treesize.treesize_module import TreeSizeModule
    from modules.quick_fix.quick_fix_module import QuickFixModule
    from modules.updates.updates_module import UpdatesModule
    # Batch B — System group
    from modules.hardware_inventory.hardware_module import HardwareModule
    from modules.network_diagnostics.network_module import NetworkDiagnosticsModule
    from modules.security_dashboard.security_module import SecurityDashboardModule
    from modules.driver_manager.driver_module import DriverModule
    # Batch B — Manage group
    from modules.startup_manager.startup_module import StartupModule
    from modules.scheduled_tasks.tasks_module import TasksModule
    from modules.windows_features.features_module import WindowsFeaturesModule
    from modules.certificate_viewer.cert_module import CertModule
    from modules.gpresult.gpresult_module import GPResultModule
    # Batch C — Tools group
    from modules.performance_tuner.perf_tuner_module import PerfTunerModule
    from modules.power_boot.power_module import PowerBootModule
    from modules.network_extras.net_extras_module import NetExtrasModule
    from modules.shared_resources.shares_module import SharesModule
    from modules.env_vars.env_vars_module import EnvVarsModule
    from modules.registry_explorer.registry_module import RegistryExplorerModule
    from modules.software_inventory.software_module import SoftwareModule
    from modules.remote_tools.remote_module import RemoteToolsModule
    from modules.disk_health.disk_health_module import DiskHealthModule
    from modules.restore_manager.restore_module import RestoreManagerModule
    # Track 2 — New Tool Modules
    from modules.services_manager.services_module import ServicesModule
    from modules.wifi_analyzer.wifi_module import WifiAnalyzerModule
    from modules.firewall_rules.firewall_manager_module import FirewallManagerModule
    from modules.local_users.users_module import LocalUsersModule
    from modules.system_report.report_module import SystemReportModule
    from modules.about.about_module import AboutModule
    from modules.boot_analyzer.boot_analyzer_module import BootAnalyzerModule
    from modules.diagnose.diagnose_module import DiagnoseModule
    from modules.duplicate_finder.duplicate_finder_module import DuplicateFinderModule
    from modules.hosts_editor.hosts_editor_module import HostsEditorModule
    from modules.store_apps.store_apps_module import StoreAppsModule

    app.module_registry.register(DashboardModule())
    app.module_registry.register(DiagnoseModule())
    # EventViewer, CBS, DISM, WU, Reliability, CrashDumps — embedded in DiagnoseModule
    app.module_registry.register(PerfMonModule())
    app.module_registry.register(ProcessExplorerModule())
    app.module_registry.register(TweaksModule())
    app.module_registry.register(CleanupModule())
    app.module_registry.register(QuickCleanupModule())
    app.module_registry.register(TreeSizeModule())
    app.module_registry.register(QuickFixModule())
    app.module_registry.register(UpdatesModule())
    app.module_registry.register(HardwareModule())
    app.module_registry.register(NetworkDiagnosticsModule())
    app.module_registry.register(SecurityDashboardModule())
    app.module_registry.register(DriverModule())
    app.module_registry.register(StartupModule())
    app.module_registry.register(TasksModule())
    app.module_registry.register(WindowsFeaturesModule())
    app.module_registry.register(CertModule())
    app.module_registry.register(GPResultModule())
    # Batch C
    app.module_registry.register(PerfTunerModule())
    app.module_registry.register(PowerBootModule())
    app.module_registry.register(NetExtrasModule())
    app.module_registry.register(SharesModule())
    app.module_registry.register(EnvVarsModule())
    app.module_registry.register(RegistryExplorerModule())
    app.module_registry.register(SoftwareModule())
    app.module_registry.register(RemoteToolsModule())
    app.module_registry.register(DiskHealthModule())
    app.module_registry.register(RestoreManagerModule())
    # Track 2
    app.module_registry.register(ServicesModule())
    app.module_registry.register(WifiAnalyzerModule())
    app.module_registry.register(FirewallManagerModule())
    app.module_registry.register(LocalUsersModule())
    app.module_registry.register(SystemReportModule())
    app.module_registry.register(AboutModule())
    app.module_registry.register(BootAnalyzerModule())
    app.module_registry.register(DuplicateFinderModule())
    app.module_registry.register(HostsEditorModule())
    app.module_registry.register(StoreAppsModule())

    # Start modules
    app.start()

    # Register search providers
    for module in app.module_registry.modules:
        provider = module.get_search_provider()
        if provider is not None:
            app.search.register_provider(provider)

    # Create window and register all modules (uses new register_module API)
    window = MainWindow(app)
    for module in app.module_registry.modules:
        window.register_module(module)

    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
