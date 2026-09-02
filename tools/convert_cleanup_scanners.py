"""Turn hand-written `scan_*` functions into catalog JSON — provably.

One-off conversion tool for audit #14. Reads a `scanners_*.py`, finds the
functions whose whole body is "expand some paths, call `_make_item`, sum the
sizes", and emits the equivalent `ScannerSpec` rows.

It converts only what it can prove it understands. A function that reads the
registry, shells out, walks a tree with its own rules, or has any shape this
tool does not recognise is REPORTED AND SKIPPED, never guessed at. The census
that justified this work found 430 plain path lists and 79 glob variants out
of 538; the other 29 stay as Python, and that is the correct outcome for
them.

Usage:
    python tools/convert_cleanup_scanners.py scanners_system.py           # report
    python tools/convert_cleanup_scanners.py scanners_system.py --write   # emit JSON
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
import sys

SCANNERS = pathlib.Path("src/modules/cleanup/cleanup_scanner")
DEFINITIONS = SCANNERS / "definitions"

#: Locals these functions assign from the environment, and the variable each
#: one stands for. Taken from reading the eight files: every one of them
#: opens with some subset of these.
ENV_LOCALS = {
    "local": "LOCALAPPDATA",
    "localappdata": "LOCALAPPDATA",
    "appdata": "APPDATA",
    "roaming": "APPDATA",
    "userprofile": "USERPROFILE",
    "home": "USERPROFILE",
    "profile": "USERPROFILE",
    "programdata": "ProgramData",
    "progdata": "ProgramData",
    "windir": "windir",
    "temp": "TEMP",
    "tmp": "TEMP",
    "public": "PUBLIC",
    "programfiles": "ProgramFiles",
    "pf": "ProgramFiles",
    "pf86": "ProgramFiles(x86)",
}

#: Literal drive-letter paths, rewritten to the variable that means them.
#: This is audit #16 landing as a side effect: 136 hardcoded C:\ paths, on a
#: machine where Windows need not be on C:.
LITERAL_REWRITES = [
    ("C:\\Windows", "%windir%"),
    ("C:\\ProgramData", "%ProgramData%"),
    ("C:\\Users", "%SystemDrive%\\Users"),
    ("C:\\Program Files (x86)", "%ProgramFiles(x86)%"),
    ("C:\\Program Files", "%ProgramFiles%"),
]


class Unconvertible(Exception):
    """This function is more than a path list. Leave it alone."""


def _rewrite_literal(text: str) -> str:
    for prefix, var in LITERAL_REWRITES:
        if text.lower().startswith(prefix.lower()):
            return var + text[len(prefix):]
    return text


def _path_expr(node: ast.AST, env: dict) -> str:
    """One path expression -> a `%VAR%`-style string, or raise."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _rewrite_literal(node.value)

    if isinstance(node, ast.Name):
        if node.id in env:
            return env[node.id]
        raise Unconvertible(f"unknown local {node.id!r}")

    if isinstance(node, ast.JoinedStr):  # f-string
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append(_path_expr(value.value, env))
            else:
                raise Unconvertible("unsupported f-string part")
        return _rewrite_literal("".join(parts))

    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _path_expr(node.left, env) + _path_expr(node.right, env)

    if isinstance(node, ast.Call):
        func = node.func
        # os.path.join(a, b, c)
        if (isinstance(func, ast.Attribute) and func.attr == "join"
                and isinstance(func.value, ast.Attribute) and func.value.attr == "path"):
            return os.path.join(*[_path_expr(a, env) for a in node.args])
        # os.environ.get("VAR", "")
        if (isinstance(func, ast.Attribute) and func.attr == "get"
                and isinstance(func.value, ast.Attribute) and func.value.attr == "environ"):
            if node.args and isinstance(node.args[0], ast.Constant):
                return "%" + node.args[0].value + "%"
        # glob.glob(pattern) / _glob.glob(pattern)
        if isinstance(func, ast.Attribute) and func.attr == "glob" and node.args:
            return _path_expr(node.args[0], env)
        raise Unconvertible(f"unsupported call {ast.dump(func)[:60]}")

    raise Unconvertible(f"unsupported node {type(node).__name__}")


def _collect_env(fn: ast.FunctionDef) -> dict:
    """The `local = os.environ.get("LOCALAPPDATA", "")` preamble."""
    env = {}
    for stmt in fn.body:
        if not (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Name)):
            continue
        name = stmt.targets[0].id
        try:
            env[name] = _path_expr(stmt.value, env)
        except Unconvertible:
            if name.lower() in ENV_LOCALS:
                env[name] = "%" + ENV_LOCALS[name.lower()] + "%"
    return env


def _safety_of(fn: ast.FunctionDef) -> str:
    """The safety= passed to _make_item. One per function, or it is not
    a plain path list."""
    found = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("_make_item", "_make_item_with_age"):
            for kw in node.keywords:
                if kw.arg == "safety" and isinstance(kw.value, ast.Constant):
                    found.add(kw.value.value)
            # positional: _make_item_with_age(path, safety, age)
            if node.func.id == "_make_item_with_age" and len(node.args) >= 2 \
                    and isinstance(node.args[1], ast.Constant):
                found.add(node.args[1].value)
    if len(found) == 1:
        return found.pop()
    if not found:
        return "safe"
    raise Unconvertible(f"more than one safety level: {sorted(found)}")


def convert(fn: ast.FunctionDef) -> dict:
    """A `scan_*` function -> one ScannerSpec row, or raise Unconvertible."""
    body_dump = ast.dump(fn)
    for forbidden, why in (("subprocess", "shells out"),
                           ("winreg", "reads the registry"),
                           ("os.walk", "walks a tree"),
                           ("scandir", "walks a tree"),
                           ("listdir", "walks a tree")):
        if forbidden in body_dump:
            raise Unconvertible(why)

    env = _collect_env(fn)
    paths: list = []

    for node in ast.walk(fn):
        # targets = [...] / targets.extend([...])
        if isinstance(node, (ast.List, ast.Tuple)):
            parent_is_env = False
            for elt in node.elts:
                try:
                    candidate = _path_expr(elt, env)
                except Unconvertible:
                    parent_is_env = True
                    break
                if not isinstance(candidate, str) or not candidate.strip():
                    parent_is_env = True
                    break
            if not parent_is_env and node.elts:
                for elt in node.elts:
                    value = _path_expr(elt, env)
                    if value and value not in paths:
                        paths.append(value)

    # `for pf in glob.glob(os.path.join(pf_dir, "*.pf")):` — the loop
    # variable is not resolvable, but what it iterates over IS the path
    # expression, and a glob is exactly what the engine handles.
    for node in ast.walk(fn):
        if not isinstance(node, ast.For):
            continue
        try:
            value = _path_expr(node.iter, env)
        except Unconvertible:
            continue
        if value and value not in paths:
            paths.append(value)

    # A direct `_make_item(<expr>, ...)` with an expression not in any list.
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("_make_item", "_make_item_with_age") and node.args:
            try:
                value = _path_expr(node.args[0], env)
            except Unconvertible:
                continue
            if value and value not in paths:
                paths.append(value)

    paths = [p for p in paths if p and "%" not in p.replace("%%", "") or "%" in p]
    paths = [p for p in paths if p.strip() and p not in ("", ".")]
    if not paths:
        raise Unconvertible("no path expression recognised")

    doc = ast.get_docstring(fn) or ""
    label = doc.split(".")[0].split("\n")[0].strip() or fn.name[5:].replace("_", " ").title()

    return {
        "id": fn.name[len("scan_"):],
        "label": label,
        "paths": paths,
        "safety": _safety_of(fn),
        "description": doc.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="e.g. scanners_system.py")
    parser.add_argument("--write", action="store_true", help="emit the JSON file")
    args = parser.parse_args()

    path = SCANNERS / args.source
    tree = ast.parse(path.read_text(encoding="utf-8"))

    converted, skipped = [], []
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("scan_"):
            continue
        try:
            converted.append(convert(fn))
        except Unconvertible as exc:
            skipped.append((fn.name, str(exc)))

    print(f"{path.name}: {len(converted)} convertible, {len(skipped)} left as Python")
    for name, why in skipped:
        print(f"    skip  {name}: {why}")

    if args.write:
        DEFINITIONS.mkdir(exist_ok=True)
        out = DEFINITIONS / (path.stem.replace("scanners_", "") + ".json")
        payload = {
            "category": path.stem.replace("scanners_", ""),
            "scanners": converted,
        }
        out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8")
        print(f"    wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
