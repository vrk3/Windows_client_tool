import logging
import os
import tempfile
from unittest.mock import patch

from core.logging_service import LoggingService


def test_setup_creates_log_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "logs")
        svc = LoggingService(log_dir=log_path, log_level="DEBUG")
        svc.setup()
        test_logger = logging.getLogger("test.setup")
        test_logger.info("hello from test")
        svc.shutdown()
        log_file = os.path.join(log_path, "app.log")
        assert os.path.exists(log_file)
        with open(log_file) as f:
            content = f.read()
        assert "hello from test" in content


def test_session_log_goes_to_app_data_when_running_from_source(monkeypatch):
    """#4: source runs must never drop logs into the working directory."""
    monkeypatch.setattr("core.logging_service.sys.frozen", False, raising=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = LoggingService(log_dir=tmpdir, log_level="INFO")
        svc.setup_session_log()
        try:
            assert svc.session_log_dir == tmpdir
        finally:
            svc.shutdown()


def test_session_log_falls_back_when_exe_dir_unwritable(monkeypatch):
    """A read-only exe dir (Program Files) must not lose the session log."""
    monkeypatch.setattr("core.logging_service.sys.frozen", True, raising=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = LoggingService(log_dir=tmpdir, log_level="INFO")
        # Simulate a probe write failure in the exe dir.
        with patch("builtins.open", side_effect=OSError("read-only")):
            svc.setup_session_log()
        try:
            assert svc.session_log_dir == tmpdir
        finally:
            svc.shutdown()


def test_log_level_is_respected():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "logs")
        svc = LoggingService(log_dir=log_path, log_level="WARNING")
        svc.setup()
        test_logger = logging.getLogger("test.level")
        test_logger.debug("debug msg")
        test_logger.warning("warning msg")
        svc.shutdown()
        log_file = os.path.join(log_path, "app.log")
        with open(log_file) as f:
            content = f.read()
        assert "debug msg" not in content
        assert "warning msg" in content


def test_format_includes_level_and_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "logs")
        svc = LoggingService(log_dir=log_path, log_level="INFO")
        svc.setup()
        test_logger = logging.getLogger("mymodule")
        test_logger.info("formatted message")
        svc.shutdown()
        log_file = os.path.join(log_path, "app.log")
        with open(log_file) as f:
            content = f.read()
        assert "[INFO]" in content
        assert "mymodule" in content
