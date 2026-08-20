"""Runs a scan off the UI thread (spec 3.4).

**Threading contract.** The worker owns the store exclusively while scanning and
mutates it only from the worker thread. It emits index ranges, never node
objects, so nothing crosses threads that could be mutated on both sides. The
store's arrays are append-only during a scan, so a main-thread read of an
already-emitted range cannot race an append.

**On incremental tree population.** Only the WALK engine can populate a tree as
it scans: it walks breadth-first, so a node's parent already exists when the
node is added. The MFT engine cannot -- records arrive in MFT order with no
parent/child guarantee, and the tree does not exist at all until
`MftTreeBuilder.finish()` links it. So batches drive a progress readout during
the scan and the tree is populated when the scan completes. Pretending
otherwise would mean showing a tree whose parents are not yet known.

What this DOES buy, which is the point: the UI stays responsive, and Stop and
Pause work while a full-drive scan is running.
"""
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from ..scan.scanner import Scanner


class ScanSignals(QObject):
    batch_ready = pyqtSignal(object)     # (start, end) index range
    finished = pyqtSignal(object)        # ScanResult
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()


class ScanWorker(QRunnable):
    def __init__(self, target: str, filters=None,
                 charge_all_hardlinks: bool = False,
                 collect_owners: bool = False) -> None:
        super().__init__()
        self.signals = ScanSignals()
        self.scanner = Scanner(target, filters=filters,
                               charge_all_hardlinks=charge_all_hardlinks,
                               collect_owners=collect_owners)
        self._cancelled = False

    # Cancellation and pause are the scanner's own callbacks; this class only
    # decides when they answer yes.
    def cancel(self) -> None:
        self._cancelled = True
        # A paused scan polls should_cancel only after the pause releases, so
        # cancelling must also resume or the scan would never observe it.
        self.scanner.resume()

    def is_cancelled(self) -> bool:
        return self._cancelled

    def pause(self) -> None:
        self.scanner.pause()

    def resume(self) -> None:
        self.scanner.resume()

    def run(self) -> None:
        try:
            result = self.scanner.scan(
                on_batch=self.signals.batch_ready.emit,
                should_cancel=self.is_cancelled)
        except Exception as exc:                      # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        if self._cancelled:
            self.signals.cancelled.emit()
        else:
            self.signals.finished.emit(result)
