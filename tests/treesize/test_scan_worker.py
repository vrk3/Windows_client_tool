"""Spec 3.4: the scan runs off the UI thread."""
import pytest

from modules.treesize.ui.scan_worker import ScanWorker
from modules.treesize.ui.shell import TreeSizeShell


def test_worker_reports_a_result(qapp, tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 1000)
    results = []
    worker = ScanWorker(str(tmp_path))
    worker.signals.finished.connect(results.append)
    worker.run()                        # run inline; threading is Qt's job
    assert results and results[0].store.size[results[0].root] == 1000


def test_worker_reports_cancellation_instead_of_a_result(qapp, tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    events = []
    worker = ScanWorker(str(tmp_path))
    worker.signals.finished.connect(lambda r: events.append("finished"))
    worker.signals.cancelled.connect(lambda: events.append("cancelled"))
    worker.cancel()
    worker.run()
    assert events == ["cancelled"]


def test_cancelling_also_resumes_so_a_paused_scan_can_stop(qapp, tmp_path):
    """should_cancel is polled only AFTER the pause releases, so a cancel that
    did not resume would leave the scan blocked forever."""
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    worker = ScanWorker(str(tmp_path))
    worker.pause()
    worker.cancel()
    worker.run()                        # would hang if cancel did not resume
    assert worker.is_cancelled()


def test_a_failing_scan_reports_instead_of_raising(qapp, monkeypatch, tmp_path):
    worker = ScanWorker(str(tmp_path))
    monkeypatch.setattr(worker.scanner, "scan",
                        lambda **kw: (_ for _ in ()).throw(OSError("disk gone")))
    failures = []
    worker.signals.failed.connect(failures.append)
    worker.run()
    assert failures and "disk gone" in failures[0]


def test_start_scan_does_not_block_the_caller(qapp, tmp_path):
    for i in range(30):
        (tmp_path / f"f{i}.bin").write_bytes(b"x" * 100)
    shell = TreeSizeShell()
    shell.start_scan(str(tmp_path))
    assert shell._worker is not None, "returned before the scan finished"
    assert shell.wait_for_scan(60_000)
    assert shell._result.node_count == 31


def test_a_second_scan_is_refused_while_one_is_running(qapp, tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    shell = TreeSizeShell()
    shell.start_scan(str(tmp_path))
    first = shell._worker
    shell.start_scan(str(tmp_path))
    assert shell._worker is first
    shell.wait_for_scan(60_000)
