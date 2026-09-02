"""Every blocking subprocess call states how long it is willing to wait.

31 of 82 did not. A `sc`, `netsh` or `dism` that never returns pins a
QThreadPool slot for the life of the process; the pane waiting on it shows a
spinner that never stops, and no log line ever explains why. `subprocess.run`
without `timeout=` has no upper bound at all — the default is to wait
forever.

This test is the reason that number cannot climb back up.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

#: Popen is deliberately absent: it does not block, so a timeout is not the
#: right tool — the caller owns the process handle and decides what to do
#: with it. These four all wait.
BLOCKING = {"run", "check_output", "check_call", "call"}


def _untimed_calls():
    found = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in BLOCKING):
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
                continue
            if any(kw.arg == "timeout" for kw in node.keywords):
                continue
            # `**kwargs` forwarded from a wrapper may carry the timeout.
            if any(kw.arg is None for kw in node.keywords):
                continue
            found.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    return found


def test_no_blocking_subprocess_call_omits_its_timeout():
    offenders = _untimed_calls()
    assert offenders == [], (
        "these calls wait forever if the process never returns — pass "
        "timeout=, or use core.run.run which supplies one:\n  "
        + "\n  ".join(offenders))
