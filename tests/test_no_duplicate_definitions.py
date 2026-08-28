"""No name may be bound twice at module or class level, anywhere in src/.

A duplicated definition silently overrides the first copy and runs green.
`shell.py` shipped 90 identical lines of scan_remote and four other methods
that way. `security_reader.py` shipped ten duplicated module-level functions
built on two helpers with OPPOSITE polarity -- `_check_service(good_running=)`
against `_svc_check(running_bad=)` -- so which answer the pane showed was
decided by file order.

The existing guard (tests/treesize/test_ui_shell.py) covers one directory and
only class methods. This one covers every module under src/ and both levels.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


def _duplicates_in(body, path, prefix=""):
    found, seen = [], set()
    for item in body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = prefix + item.name
            if name in seen:
                found.append(f"{path.relative_to(SRC)}:{item.lineno} {name}")
            seen.add(name)
        if isinstance(item, ast.ClassDef):
            found += _duplicates_in(item.body, path, prefix=item.name + ".")
    return found


def test_no_module_or_class_defines_a_name_twice():
    duplicates = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        duplicates += _duplicates_in(tree.body, path)
    assert not duplicates, (
        "these names are bound twice; the second silently wins:\n  "
        + "\n  ".join(duplicates))
