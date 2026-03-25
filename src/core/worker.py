from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

class WorkerSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    cancelled = pyqtSignal()

class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self._cancelled = False

    def run(self):
        try:
            result = self.fn(self, *self.args, **self.kwargs)
            if self._cancelled:
                self.signals.cancelled.emit()
            else:
                self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled
