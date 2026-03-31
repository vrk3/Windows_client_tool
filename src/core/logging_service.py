"""Centralized logging service for Windows Client Tool."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

__version__ = "0.1.0"


class ApplicationLogger(logging.Logger):
    """Custom logger with application context."""

    def warning(self, msg, *args, **kwargs):
        """Log WARNING level message."""
        if args or kwargs:
            msg = msg % args
        self.log(logging.WARNING, msg, stacklevel=2)

    def error(self, msg, *args, **kwargs):
        """Log ERROR level message."""
        if args or kwargs:
            msg = msg % args
        self.log(logging.ERROR, msg, stacklevel=2)

    def exception(self, msg, *args, exc_info: Optional[bool] = None, **kwargs):
        """Log exception traceback if exc_info is not None."""
        if exc_info is None:
            exc_info = kwargs.get("exc_info", True)
        if args or kwargs:
            msg = msg % args
        self.log(logging.ERROR, msg, exc_info=exc_info, stacklevel=2)

    def info(self, msg, *args, **kwargs):
        """Log INFO level message."""
        if args or kwargs:
            msg = msg % args
        self.log(logging.INFO, msg, stacklevel=2)

    def debug(self, msg, *args, **kwargs):
        """Log DEBUG level message if DEBUG enabled."""
        if args or kwargs:
            msg = msg % args
        self.log(logging.DEBUG, msg, stacklevel=2)


class LoggingService:
    """Configure Python logging for Windows Client Tool application.

    This service provides:
    - Rotating file logs with size/date limits
    - Console output (colored when supported)
    - Application-specific logging levels
    - Graceful shutdown handling
    """

    LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    MAX_BYTES = 5 * 1024 * 1024  # 5MB rotation
    BACKUP_COUNT = 5

    def __init__(
        self,
        log_dir: Optional[str] = None,
        log_level: str = "INFO",
        console_level: str = "WARNING",
        max_bytes: int = -1,
        backup_count: int = 5,
    ):
        """Initialize logging service.

        Args:
            log_dir: Directory to write log files (creates if needed)
            log_level: Minimum level for file handler
            console_level: Minimum level for console output
            max_bytes: Rotation file size (use -1 for unlimited)
            backup_count: Number of backup files to keep
        """
        self._log_dir = log_dir or ""
        self._log_level = getattr(logging, log_level.upper(), logging.INFO)
        self._console_level = getattr(logging, console_level.upper(), logging.WARNING)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handlers: list[logging.Handler] = []

    def setup(self) -> None:
        """Configure logging with rotation and dual output."""
        try:
            os.makedirs(self._log_dir, exist_ok=True)
        except OSError as e:
            print(f"Log directory creation failed: {e}")
            return

        if not self._log_dir:
            return

        log_file = os.path.join(self._log_dir, "app.log")
        formatter = logging.Formatter(self.LOG_FORMAT, datefmt=self.DATE_FORMAT)

        # File handler with rotation
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=self._max_bytes,
                backupCount=self._backup_count,
                encoding="utf-8",
            )
        except Exception as e:
            print(f"Could not create file handler: {e}")
            file_handler = None

        if file_handler:
            file_handler.setFormatter(formatter)
            file_handler.setLevel(self._log_level)
            file_handler.addFilter(self._create_filter())
            self._handlers.append(file_handler)

        # Console handler with color when possible
        try:
            console_handler = logging.StreamHandler(sys.stdout)
        except Exception as e:
            print(f"Could not create console handler: {e}")
            console_handler = None

        if console_handler:
            console_handler.setFormatter(formatter)
            console_handler.setLevel(self._console_level)
            if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
                console_handler.addFilter(self._create_color_filter())
            self._handlers.append(console_handler)

        # Register at cleanup
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().addHandler(console_handler)

    def _create_filter(self) -> logging.Filter:
        """Create filter for log messages with module name."""
        return logging.Filter("app")

    def _create_color_filter(self) -> logging.Filter:
        """Create color filter for console output."""

        # Simple filter to only console handlers
        class ConsoleFilter(logging.Filter):
            def filter(self, record):
                return True

        return ConsoleFilter()

    def set_level(self, level: str) -> None:
        """Update logging level for all handlers.

        Args:
            level: New level string ("DEBUG", "INFO", "WARNING", "ERROR")
        """
        level = getattr(logging, level.upper(), logging.INFO)
        for handler in self._handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.setLevel(level)

    def shutdown(self) -> None:
        """Cleanup handlers before application shutdown."""
        for handler in self._handlers:
            handler.flush()
            handler.close()
            logging.getLogger().removeHandler(handler)
        self._handlers.clear()
        self._log_dir = ""
