r"""A worker that outlives its signals object must not raise inside run().

Seen for real on 2026-08-24, twice in one process exit, while the Security
Dashboard's 37-second sweep was still on the pool:

    ERROR core.worker: Worker error: wrapped C/C++ object of type
                       WorkerSignals has been deleted
      File "src\core\worker.py", line 87, in run
        self.signals.cancelled.emit()

Qt destroys its QObjects when the QApplication goes down; a worker running on
the pool at that moment finds its `WorkerSignals` gone. `run()` then walks
into the trap three times over -- the emit raises, the `except` handler's own
`error.emit` raises again, and the `finally`'s `finished.emit` raises a third
time and escapes `run()` entirely, out of a QRunnable on a Qt thread.

Closing the app while any pane is loading is enough to hit this, so it is not
specific to the dashboard: every module in the app uses these workers.
"""
import pytest

from core.worker import Worker


class DeadSignals:
    """A signals object whose C++ half is gone, as PyQt presents it."""

    def __getattr__(self, name):
        raise RuntimeError(
            "wrapped C/C++ object of type WorkerSignals has been deleted"
        )


def test_run_survives_a_deleted_signals_object():
    worker = Worker(lambda _w: "done")
    worker.signals = DeadSignals()

    worker.run()   # must not raise


def test_run_survives_deletion_on_the_cancelled_path():
    """The exact line from the log: cancelled during a completed run."""
    worker = Worker(lambda _w: worker.cancel() or "done")
    worker.signals = DeadSignals()

    worker.run()


def test_run_survives_deletion_when_cancelled_before_it_starts():
    worker = Worker(lambda _w: pytest.fail("cancelled work must not run"))
    worker.cancel()
    worker.signals = DeadSignals()

    worker.run()


def test_a_live_worker_still_emits_everything(qapp):
    """The guard must not swallow signals that CAN be delivered."""
    worker = Worker(lambda _w: "payload")
    seen = []
    worker.signals.result.connect(lambda r: seen.append(("result", r)))
    worker.signals.finished.connect(lambda: seen.append(("finished", None)))

    worker.run()

    assert seen == [("result", "payload"), ("finished", None)]


def test_a_real_exception_in_the_work_still_reaches_the_error_signal(qapp):
    worker = Worker(lambda _w: 1 / 0)
    seen = []
    worker.signals.error.connect(lambda m: seen.append(m))

    worker.run()

    assert seen and "division by zero" in seen[0]
