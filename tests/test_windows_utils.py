# tests/test_windows_utils.py
from unittest.mock import patch, MagicMock
import importlib


def _reload():
    import core.windows_utils as m
    importlib.reload(m)
    return m


def test_reboot_pending_pfro_key():
    """PendingFileRenameOperations key present → True."""
    open_calls = [0]

    def fake_open(hive, path):
        if "Session Manager" in path:
            return MagicMock(__enter__=lambda s: MagicMock(), __exit__=MagicMock(return_value=False))
        raise OSError

    with patch("winreg.OpenKey", side_effect=fake_open), \
         patch("winreg.QueryValueEx", return_value=("x", 7)):
        m = _reload()
        assert m.is_reboot_pending() is True


def test_reboot_pending_false_all_absent():
    """All three keys absent → False."""
    with patch("winreg.OpenKey", side_effect=OSError):
        m = _reload()
        assert m.is_reboot_pending() is False


def test_reboot_pending_wu_reboot_required():
    """Third key (WindowsUpdate RebootRequired) present → True."""
    call_n = [0]

    def fake_open(hive, path):
        call_n[0] += 1
        if call_n[0] < 3:
            raise OSError
        return MagicMock(__enter__=lambda s: MagicMock(), __exit__=MagicMock(return_value=False))

    with patch("winreg.OpenKey", side_effect=fake_open), \
         patch("winreg.QueryValueEx", return_value=(1, 4)):
        m = _reload()
        assert m.is_reboot_pending() is True


def test_ps_quote_escapes_single_quotes():
    from core.windows_utils import ps_quote
    assert ps_quote("Microsoft.WindowsCalculator") == "Microsoft.WindowsCalculator"
    assert ps_quote("it's a package") == "it''s a package"
    assert ps_quote("") == ""
