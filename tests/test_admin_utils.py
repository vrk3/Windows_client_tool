import sys
from core.admin_utils import is_admin, get_restart_as_admin_command

def test_is_admin_returns_bool():
    assert isinstance(is_admin(), bool)

def test_get_restart_command_returns_executable():
    cmd = get_restart_as_admin_command()
    assert cmd["executable"] == sys.executable
    assert isinstance(cmd["args"], list)


def test_a_path_with_a_space_survives_the_relaunch(monkeypatch):
    r"""`" ".join(sys.argv)` turned one argument into two.

    C:\Users\John Doe\... and C:\Program Files\... are both ordinary,
    and both broke the elevated relaunch silently: ShellExecuteW got a
    command line the child then parsed as a different set of arguments.
    modules/security_dashboard/elevated_helper.py already names this file
    as the one that got it wrong, and already uses the fix.
    """
    import subprocess

    from core import admin_utils

    monkeypatch.setattr(
        admin_utils.sys, "argv",
        [r"C:\Users\John Doe\app\main.py", "--stages", "wu,winget"])
    captured = {}

    def fake_shell_execute(hwnd, verb, file, params, directory, show):
        captured["verb"] = verb
        captured["params"] = params
        return 42  # > 32 means ShellExecuteW succeeded

    monkeypatch.setattr(admin_utils, "_shell_execute", fake_shell_execute)
    monkeypatch.setattr(admin_utils.sys, "exit", lambda code=0: None)

    admin_utils.restart_as_admin()

    assert captured["verb"] == "runas"
    assert captured["params"] == subprocess.list2cmdline(
        [r"C:\Users\John Doe\app\main.py", "--stages", "wu,winget"])
    assert r'"C:\Users\John Doe\app\main.py"' in captured["params"]


def test_declining_the_uac_prompt_does_not_close_the_app(monkeypatch):
    """ShellExecuteW returns <= 32 on failure, and the commonest failure by
    far is the user saying No. Exiting on that would close the application
    because someone declined to elevate it."""
    from core import admin_utils

    exits = []
    monkeypatch.setattr(admin_utils, "_shell_execute",
                        lambda *a, **k: 5)  # SE_ERR_ACCESSDENIED / cancelled
    monkeypatch.setattr(admin_utils.sys, "exit", lambda code=0: exits.append(code))

    admin_utils.restart_as_admin()

    assert exits == [], "declining the prompt must leave the app running"
