r"""netsh explains itself on STDOUT, and check=True throws that away.

From the real log, 2026-08-26:

    Worker error: Command '['netsh', 'advfirewall', 'firewall', 'set', 'rule',
    'name=@{Microsoft.WindowsFeedbackHub_..?ms-resource://..}', 'new',
    'enable=no']' returned non-zero exit status 1.

That toggle path was fixed the next day (37a4d32) by falling back to
PowerShell, which CAN address a Store app's MRT indirect name. But four
siblings were left raising CalledProcessError from check=True:

    netsh_block_program   netsh_open_port   netsh_export_rules   netsh_import_rules

Each runs inside a Worker whose error signal goes straight to the user, so
what they show is "returned non-zero exit status 1" -- a number, when netsh
had already written the reason ("The requested operation requires elevation.",
"No rules match the specified criteria.", "A rule with the same name already
exists.") to its own stdout, where check=True discarded it.
"""
import subprocess

import pytest

from modules.firewall_rules import firewall_manager_module as fw


@pytest.fixture
def netsh(monkeypatch):
    """Stand in for netsh: canned (rc, stdout), and record the argv."""
    calls = []
    answer = {"rc": 0, "out": "Ok."}

    def fake_run(args, **kwargs):
        calls.append(args)
        assert "check" not in kwargs or kwargs["check"] is False, (
            "check=True discards netsh's own explanation")
        return subprocess.CompletedProcess(
            args, answer["rc"], stdout=answer["out"], stderr="")

    monkeypatch.setattr(fw.subprocess, "run", fake_run)
    return calls, answer


def test_a_refused_block_rule_says_why(netsh):
    calls, answer = netsh
    answer["rc"] = 1
    answer["out"] = "The requested operation requires elevation."

    with pytest.raises(Exception) as caught:
        fw.netsh_block_program(r"C:\Tools\thing.exe")

    message = str(caught.value)
    assert "requires elevation" in message
    assert "exit status" not in message, (
        "it reported a number where netsh had given a reason")


def test_a_block_rule_that_worked_raises_nothing(netsh):
    calls, _ = netsh
    fw.netsh_block_program(r"C:\Tools\thing.exe")
    argv = calls[0]
    assert argv[:5] == ["netsh", "advfirewall", "firewall", "add", "rule"]
    assert "action=block" in argv
    assert r"program=C:\Tools\thing.exe" in argv


def test_a_refused_port_rule_says_why(netsh):
    _, answer = netsh
    answer["rc"] = 1
    answer["out"] = "A rule with the same name already exists."

    with pytest.raises(Exception) as caught:
        fw.netsh_open_port(8080)

    assert "already exists" in str(caught.value)


def test_a_refused_export_says_why(netsh):
    _, answer = netsh
    answer["rc"] = 1
    answer["out"] = "The system cannot find the path specified."

    with pytest.raises(Exception) as caught:
        fw.netsh_export_rules(r"D:\nope\rules.wfw")

    assert "cannot find the path" in str(caught.value)


def test_a_refused_import_says_why(netsh):
    _, answer = netsh
    answer["rc"] = 1
    answer["out"] = "The file is not a valid firewall policy file."

    with pytest.raises(Exception) as caught:
        fw.netsh_import_rules(r"D:\rules.wfw")

    assert "not a valid firewall policy" in str(caught.value)


def test_an_empty_complaint_still_names_the_exit_code(netsh):
    """netsh usually explains itself; when it says nothing at all, the number
    is all there is and hiding it would leave the user with nothing."""
    _, answer = netsh
    answer["rc"] = 1
    answer["out"] = ""

    with pytest.raises(Exception) as caught:
        fw.netsh_open_port(8080)

    assert "1" in str(caught.value)


def test_no_subprocess_call_in_this_module_uses_check_true():
    """The rule, guarded at source level: netsh writes its refusals to stdout,
    so check=True converts an explanation into an exit code.

    Parsed rather than grepped -- the docstring that explains this rule says
    "check=True" too, and a guard that trips on its own documentation is
    worthless.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(fw))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (keyword.arg == "check"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True):
                offenders.append(node.lineno)
    assert offenders == [], (
        f"a subprocess call on line(s) {offenders} still discards the reason "
        "it failed")
