import logging
import os
from typing import Optional

from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class ThemeManager:
    """Manages dark/light theme switching via QSS stylesheets."""

    THEMES = ("dark", "light")

    def __init__(self, styles_dir: str):
        self._styles_dir = styles_dir
        self._current_theme: str = "dark"

    @property
    def current_theme(self) -> str:
        return self._current_theme

    def apply_theme(self, theme: str) -> None:
        if theme not in self.THEMES:
            logger.warning("Unknown theme '%s', falling back to dark", theme)
            theme = "dark"
        qss_path = os.path.join(self._styles_dir, f"{theme}.qss")
        stylesheet = self._load_qss(qss_path)
        if stylesheet is not None:
            app = QApplication.instance()
            if app:
                app.setStyleSheet(stylesheet)
            self._current_theme = theme
            logger.info("Applied theme: %s", theme)
        else:
            logger.error("Failed to load theme '%s' from %s", theme, qss_path)

    def _load_qss(self, path: str) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    def toggle(self) -> str:
        new_theme = "light" if self._current_theme == "dark" else "dark"
        self.apply_theme(new_theme)
        return new_theme
