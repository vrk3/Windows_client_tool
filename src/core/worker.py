"""Worker thread pool utilities for background tasks.

This module provides safe worker implementation with signal emission
for progress updates, error handling, and cancellation support.
"""

import atexit
import logging
from threading import Lock
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    """Signal definitions for Worker class."""

    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    log_line = pyqtSignal(str)  # thread-safe log output
    cancelled = pyqtSignal()
    finished = pyqtSignal()  # always emitted after result or error


class Worker(QRunnable):
    """Thread worker with signal emission for safe async operations.

    Usage pattern:
        def _process(worker):
            def do_work():
                result = do_implementation(worker)
                return result

            w = Worker(_process)
            w.signals.result.connect(handler)
            app.thread_pool.start(w)

        Args:
            fn: Callable that accepts (worker: Worker) as first argument
            *args: Positional args to pass to fn
            **kwargs: Keyword args to pass to fn

        Signals:
            result: Emitted with computed result value
            error: Emitted with exception message string
            progress: Emitted with progress percentage (0-100)
            log_line: Emitted with log message string
            cancelled: Emitted if worker cancelled
            finished: Emitted when worker completes
    """

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        """Create worker instance.

        Args:
            fn: Worker function accepting (worker, *args, **kwargs)
            *args: Args to pass to worker function
            **kwargs: Keyword args to pass to worker function
        """
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancelled = False
        self._cancel_lock = Lock()

    def run(self) -> Any:
        """Execute worker function.

        Emits progress updates, result, errors via signals.
        Raises:
            RuntimeError: If worker cancelled before completion
        """
        with self._cancel_lock:
            if self._cancelled:
                raise RuntimeError("Worker cancelled")

        try:
            result = self.fn(self, *self.args, **self.kwargs)
            self.signals.result.emit(result)
        except Exception as e:
            logger.exception("Worker error: %s", e)
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

    def cancel(self) -> bool:
        """Cancel worker and prevent future result emission.

        Returns:
            True if worker was cancelled or already cancelled
        """
        self._cancelled = True
        with self._cancel_lock:
            return self._cancelled

    @property
    def cancelled(self) -> bool:
        """Check if worker has been cancelled."""
        return self._cancelled

    @property
    def is_cancelled(self) -> bool:
        """Alias for cancelled property."""
        return self._cancelled


class COMWorker(Worker):
    """Worker subclass for COM/COM-related operations.

    This worker initializes COM on the thread before running and
    cleans up. Use this for any worker calling win32com.client or
    COM-related pythoncom modules.
    """

    def run(self) -> None:
        """Run COM-backed worker function.

        Initializes COM with CoInitialize before calling super().run()
        and uninitializes with CoUninitialize in finally block.
        """
        import pythoncom

        pythoncom.CoInitialize()
        try:
            super().run()
        finally:
            pythoncom.CoUninitialize()

