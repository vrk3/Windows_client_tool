"""No exception is swallowed without saying so.

CLAUDE.md, verbatim: "Silent exception swallowing is forbidden — `except
Exception: pass` and bare `except: pass` silently hide errors from users who
see only empty results. Always log with logger.warning() or logger.error()."

There were 49 handlers whose entire body was `pass`, `continue` or `break`.
The heaviest concentration was in `startup_reader.py`, with six — where a
swallowed registry error means a startup entry the user never learns about,
on a pane whose entire job is to list them.

The level is not uniform, and should not be. `OSError` from
`winreg.EnumValue` is how the API says an enumeration is finished — control
flow, not a failure — and logging 300 of those at WARNING would bury the
one that matters. What this test enforces is that something is written,
not that everything shouts.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

SILENT_BODIES = (ast.Pass, ast.Continue, ast.Break)


def _silent_handlers():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            body = node.body
            if len(body) == 1 and isinstance(body[0], SILENT_BODIES):
                offenders.append(
                    f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    return offenders


def test_no_exception_handler_is_entirely_silent():
    offenders = _silent_handlers()
    assert offenders == [], (
        "these discard an exception with nothing written anywhere — add a "
        "logger.debug/warning naming what was being read:\n  "
        + "\n  ".join(offenders))


def test_the_engines_that_must_stay_qt_free_still_are():
    """Adding `import logging` to a dozen files is a chance to break the
    split that lets ~450 engine tests run headless. TreeSize's scan/ and
    store/, the Log Viewer's parser and reader, and the ten non-UI files in
    gpresult/ must not import PyQt6.
    """
    qt_free = [
        "modules/treesize/scan", "modules/treesize/store",
        "modules/treesize/targets",
        "modules/log_viewer/cmtrace_parser.py",
        "modules/log_viewer/log_reader.py",
        "modules/gpresult/rsop_parser.py",
        "modules/gpresult/pol_parser.py",
        "modules/gpresult/policy_drift.py",
        "modules/gpresult/admx_catalog.py",
        "modules/gpresult/rsop_snapshot.py",
        "modules/gpresult/tweak_conflicts.py",
        "modules/gpresult/tattooed.py",
        "modules/gpresult/gpupdate.py",
        "modules/gpresult/rsop_runner.py",
    ]
    offenders = []
    for entry in qt_free:
        target = SRC / entry
        paths = sorted(target.rglob("*.py")) if target.is_dir() else [target]
        for path in paths:
            if not path.exists():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(n.startswith("PyQt6") for n in names):
                    offenders.append(
                        f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    assert offenders == [], (
        "these must stay importable without a display:\n  "
        + "\n  ".join(offenders))
