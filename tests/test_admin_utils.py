import sys
from core.admin_utils import is_admin, get_restart_as_admin_command

def test_is_admin_returns_bool():
    assert isinstance(is_admin(), bool)

def test_get_restart_command_returns_executable():
    cmd = get_restart_as_admin_command()
    assert cmd["executable"] == sys.executable
    assert isinstance(cmd["args"], list)
