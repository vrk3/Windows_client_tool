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

    # Start modules first (calls on_start before create_widget)
    app.start()

    # Create and show main window
    window = MainWindow(app)

    # Add module tabs (after on_start so modules have app reference)
    for module in app.module_registry.modules:
        enabled = module not in app.module_registry.disabled_modules
        window.add_module_tab(module, enabled=enabled)

    window.show()
    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
