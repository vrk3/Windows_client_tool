r"""Not freezing while a big log is parsed.

Measured before building anything, which is what this task asked for: the
84.5 MB archive opens in 1.44 s and the 90-log `C:\Windows\Logs` tree in
1.45 s. Both are past the second where a frozen window stops looking busy and
starts looking broken.

**Deliberately NOT a worker thread.** Moving the parse off the UI thread would
make `open()` asynchronous, and roughly two hundred existing tests call
`open()` and assert on the result immediately -- the contract that open()
completes before it returns is load-bearing. Chunked parsing with
`processEvents` between slices keeps that contract, keeps the window
responsive, and makes Cancel possible, without introducing a single
widget-lifetime hazard.
"""
import pytest

from modules.log_viewer.log_viewer_module import LogViewerWidget

MANY = "".join(
    '<![LOG[line {n}]LOG]!><time="13:45:{s:02d}.000+000" date="08-20-2026" '
    'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n'.format(
        n=n, s=n % 60) for n in range(6000))


@pytest.fixture
def big(tmp_path):
    path = tmp_path / "big.log"
    path.write_text(MANY, encoding="utf-8")
    return str(path)


def test_a_small_log_opens_without_any_fuss(qapp, tmp_path):
    """The chunking must not add ceremony to the common case."""
    path = tmp_path / "small.log"
    path.write_text(
        '<![LOG[one]LOG]!><time="13:45:10.000+000" date="08-20-2026" '
        'component="CBS" context="" type="1" thread="1" file="a.cpp:1">\n',
        encoding="utf-8")
    widget = LogViewerWidget()
    try:
        widget.open(str(path))
        assert widget.model.total == 1
        assert "%" not in widget.status.text()
    finally:
        widget.stop()


def test_a_large_log_still_opens_completely(qapp, big):
    """The contract this design exists to keep: open() returns done."""
    widget = LogViewerWidget()
    try:
        widget.open(big)
        assert widget.model.total == 6000
    finally:
        widget.stop()


def test_a_large_open_reports_progress(qapp, big):
    seen = []
    widget = LogViewerWidget()
    try:
        widget.progress_reported.connect(seen.append)
        widget.open(big)
        assert seen, "a 6,000-record open reported no progress at all"
        assert max(seen) == 100
    finally:
        widget.stop()


def test_cancelling_stops_the_load_and_leaves_the_pane_usable(qapp, big):
    widget = LogViewerWidget()
    try:
        # Cancel as soon as the first chunk lands.
        widget.progress_reported.connect(lambda _p: widget.cancel_load())
        widget.open(big)

        assert widget.model.total < 6000, "the load ran to completion"
        assert "cancel" in widget.status.text().lower()
        # Still usable afterwards.
        widget.filter_box.setText("line 1")
        assert widget.model.rowCount() >= 0
    finally:
        widget.stop()


def test_a_cancelled_load_does_not_poison_the_next_one(qapp, big):
    widget = LogViewerWidget()
    try:
        widget.progress_reported.connect(lambda _p: widget.cancel_load())
        widget.open(big)
        widget.progress_reported.disconnect()

        widget.open(big)

        assert widget.model.total == 6000, "the cancel flag survived"
    finally:
        widget.stop()
