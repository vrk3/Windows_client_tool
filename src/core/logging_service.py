"""Centralized logging service for Windows Client Tool."""

import datetime
import logging
import os
import socket
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

__version__ = "0.1.0"


class ApplicationLogger(logging.Logger):
    """Custom logger with application context."""

    def warning(self, msg, *args, **kwargs):
        """Log WARNING level message."""
        if args:
            try:
                msg = msg % args
            except TypeError:
                msg = str(msg)
        self.log(logging.WARNING, msg, stacklevel=2)

    def error(self, msg, *args, **kwargs):
        """Log ERROR level message."""
        if args:
            try:
                msg = msg % args
            except TypeError:
                msg = str(msg)
        self.log(logging.ERROR, msg, stacklevel=2)

    def exception(self, msg, *args, exc_info: Optional[bool] = None, **kwargs):
        """Log exception traceback if exc_info is not None."""
        if exc_info is None:
            exc_info = kwargs.pop("exc_info", True)
        if args:
            try:
                msg = msg % args
            except TypeError:
                msg = str(msg)
        self.log(logging.ERROR, msg, exc_info=exc_info, stacklevel=2)

    def info(self, msg, *args, **kwargs):
        """Log INFO level message."""
        if args:
            try:
                msg = msg % args
            except TypeError:
                msg = str(msg)
        self.log(logging.INFO, msg, stacklevel=2)

    def debug(self, msg, *args, **kwargs):
        """Log DEBUG level message if DEBUG enabled."""
        if args:
            try:
                msg = msg % args
            except TypeError:
                msg = str(msg)
        self.log(logging.DEBUG, msg, stacklevel=2)


class LoggingService:
    """Configure Python logging for Windows Client Tool application.

    Provides:
    - Rotating file logs in %APPDATA%/WindowsTweaker/logs/ (persistent across runs)
    - Per-session log next to the exe named {COMPUTERNAME}_{date}_{time}.log
    - Console output when stdout is available
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
        self._log_dir = log_dir or ""
        self._log_level = getattr(logging, log_level.upper(), logging.INFO)
        self._console_level = getattr(logging, console_level.upper(), logging.WARNING)
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._handlers: list[logging.Handler] = []

    def setup(self) -> None:
        """Configure logging with rotation and dual output."""
        # Root logger must pass everything — individual handlers filter by level.
        logging.getLogger().setLevel(logging.DEBUG)

        formatter = logging.Formatter(self.LOG_FORMAT, datefmt=self.DATE_FORMAT)

        if self._log_dir:
            try:
                os.makedirs(self._log_dir, exist_ok=True)
                log_file = os.path.join(self._log_dir, "app.log")
                file_handler = RotatingFileHandler(
                    log_file,
                    maxBytes=self._max_bytes,
                    backupCount=self._backup_count,
                    encoding="utf-8",
                )
                file_handler.setFormatter(formatter)
                file_handler.setLevel(self._log_level)
                logging.getLogger().addHandler(file_handler)
                self._handlers.append(file_handler)
            except Exception as e:
                print(f"Could not create log file handler: {e}")

        # Console handler — skip when stdout is unavailable (frozen windowed mode)
        if hasattr(sys, "stdout") and sys.stdout is not None and hasattr(sys.stdout, "write"):
            try:
                console_handler = logging.StreamHandler(sys.stdout)
                console_handler.setFormatter(formatter)
                console_handler.setLevel(self._console_level)
                logging.getLogger().addHandler(console_handler)
                self._handlers.append(console_handler)
            except Exception as e:
                print(f"Could not create console handler: {e}")

    def setup_session_log(self) -> None:
        """Add a per-session log file next to the running exe.

        The file is named {COMPUTERNAME}_{YYYY-MM-DD}_{HH-MM-SS}.log and placed
        in the directory containing the executable (or cwd when running from source).
        This lets logs from multiple machines be collected from one shared folder.
        """
        if getattr(sys, "frozen", False):
            out_dir = os.path.dirname(os.path.abspath(sys.executable))
        else:
            out_dir = os.getcwd()

        raw_name = os.environ.get("COMPUTERNAME") or socket.gethostname() or "unknown"
        computer_name = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in raw_name
        )
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_path = os.path.join(out_dir, f"{computer_name}_{timestamp}.log")

        formatter = logging.Formatter(self.LOG_FORMAT, datefmt=self.DATE_FORMAT)
        try:
            handler = logging.FileHandler(log_path, encoding="utf-8")
            handler.setFormatter(formatter)
            handler.setLevel(self._log_level)
            logging.getLogger().addHandler(handler)
            self._handlers.append(handler)
            logging.getLogger(__name__).info(
                "Session log started — computer: %s, file: %s", computer_name, log_path
            )
        except Exception as e:
            logging.getLogger(__name__).warning(
                "Could not create session log at %s: %s", log_path, e
            )

    def set_level(self, level: str) -> None:
        """Update logging level for all file handlers."""
        level_int = getattr(logging, level.upper(), logging.INFO)
        for handler in self._handlers:
            if isinstance(handler, (RotatingFileHandler, logging.FileHandler)):
                handler.setLevel(level_int)

    def shutdown(self) -> None:
        """Flush and close all handlers before application shutdown."""
        for handler in self._handlers:
            try:
                handler.flush()
                handler.close()
                logging.getLogger().removeHandler(handler)
            except Exception:
                logger = logging.getLogger(__name__)
                logger.warning("Error shutting down logging handler %s", handler, exc_info=True)
        self._handlers.clear()
        self._log_dir = ""
