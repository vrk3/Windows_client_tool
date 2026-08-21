from collections import namedtuple

from core import disk_space

_Usage = namedtuple("_Usage", ["total", "used", "free"])


def test_check_wu_preflight_blocks_when_low(monkeypatch):
    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: int(0.5 * 1024 ** 3))
    reason = disk_space.check_wu_preflight(total_size_mb=500)
    assert reason is not None
    assert "GB free" in reason


def test_check_wu_preflight_allows_when_plenty(monkeypatch):
    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: 100 * 1024 ** 3)
    assert disk_space.check_wu_preflight(total_size_mb=500) is None


def test_check_wu_preflight_does_not_block_on_unknown(monkeypatch):
    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: None)
    assert disk_space.check_wu_preflight(total_size_mb=500) is None


def test_check_report_preflight_blocks_when_low(monkeypatch):
    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: int(10 * 1024 ** 2))
    reason = disk_space.check_report_preflight("C:\\some\\dir")
    assert reason is not None
    assert "MB free" in reason


def test_check_report_preflight_allows_when_plenty(monkeypatch):
    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: 5 * 1024 ** 3)
    assert disk_space.check_report_preflight("C:\\some\\dir") is None


def test_get_free_bytes_returns_none_on_error(monkeypatch, tmp_path):
    def _boom(path):
        raise OSError("no such drive")
    monkeypatch.setattr(disk_space.shutil, "disk_usage", _boom)
    assert disk_space.get_free_bytes(str(tmp_path)) is None


def test_get_free_bytes_reads_real_usage(tmp_path):
    free = disk_space.get_free_bytes(str(tmp_path))
    assert free is None or free >= 0


def test_check_wu_preflight_accepts_decimal_sizes(monkeypatch):
    """The WU COM API reports MaxDownloadSize as a VT_DECIMAL, which pywin32
    hands back as a decimal.Decimal. `Decimal / 1024.0` is a TypeError, and it
    took down the whole Run-All WU stage on a real machine. Every other test
    here passes an int, which is exactly why it survived."""
    from decimal import Decimal
    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: 100 * 1024 ** 3)
    assert disk_space.check_wu_preflight(total_size_mb=Decimal("523.75")) is None

    monkeypatch.setattr(disk_space, "get_free_bytes", lambda path: int(0.5 * 1024 ** 3))
    reason = disk_space.check_wu_preflight(total_size_mb=Decimal("523.75"))
    assert reason is not None and "GB free" in reason
