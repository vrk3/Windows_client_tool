import logging
import os
from logging.handlers import RotatingFileHandler


class LoggingService:
    """Configures Python logging with file rotation and console output."""

    LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

    def __init__(self, log_dir: str, log_level: str = "INFO"):
        self._log_dir = log_dir
        self._log_level = getattr(logging, log_level.upper(), logging.INFO)
        self._handlers: list[logging.Handler] = []

    def setup(self) -> None:
        os.makedirs(self._log_dir, exist_ok=True)
        log_file = os.path.join(self._log_dir, "app.log")

        formatter = logging.Formatter(self.LOG_FORMAT)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(self._log_level)
        self._handlers.append(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logging.DEBUG)
        self._handlers.append(console_handler)

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        for handler in self._handlers:
            root.addHandler(handler)

    def shutdown(self) -> None:
        root = logging.getLogger()
        for handler in self._handlers:
            handler.flush()
            handler.close()
            root.removeHandler(handler)
        self._handlers.clear()

    def set_level(self, level: str) -> None:
        self._log_level = getattr(logging, level.upper(), logging.INFO)
        for handler in self._handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.setLevel(self._log_level)
