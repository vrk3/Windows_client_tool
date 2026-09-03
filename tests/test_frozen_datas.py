r"""Every data directory the app reads at runtime must be in the build.

A module that loads JSON relative to its own `__file__` works perfectly from
source and finds nothing at all when frozen, because PyInstaller only ships
what `get_datas()` names. The failure is the quiet kind `pyinstaller_common`
already warns about twice in its own comments: the exe RUNS, the pane opens,
and the feature is simply not there.

Found by checking before a build rather than after one:
**`modules/cleanup/cleanup_scanner/definitions/` was never in `get_datas`**,
so every frozen build since the catalog conversion has shipped with **zero
of its 461 catalog scanners**. `catalog.load_catalog()` globs
`Path(__file__).parent / "definitions"`, gets an empty directory inside
`_MEIPASS`, and returns `{}` — no error, no log, the Cleanup tabs just quietly
offer the ~80 hand-written scanners and none of the rest.

This test walks the source for directories loaded that way and asserts the
build ships each one, so the next such directory cannot go missing silently.
"""
import ast
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"


def _declared_data_dirs():
    """Every directory `get_datas()` puts into the build."""
    import sys
    sys.path.insert(0, str(ROOT))
    from pyinstaller_common import get_datas

    return {pathlib.Path(source).resolve()
            for source, _target in get_datas(str(ROOT))}


def _referenced_data_dirs():
    r"""Directories a module builds from its own location and reads files from.

    Matches the two shapes this codebase uses:
        Path(__file__).parent / "name"
        os.path.join(os.path.dirname(__file__), "name"[, "more"])
    """
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:                     # pragma: no cover
            continue
        for node in ast.walk(tree):
            parts = _dir_parts(node)
            if not parts:
                continue
            candidate = path.parent.joinpath(*parts).resolve()
            if candidate.is_dir() and any(candidate.iterdir()):
                found.setdefault(candidate, []).append(
                    f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    return found


def _dir_parts(node):
    """`["definitions"]` for the two __file__-relative shapes, else None."""
    # Path(__file__).parent / "definitions"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        if not (isinstance(node.right, ast.Constant)
                and isinstance(node.right.value, str)):
            return None
        if _is_file_parent(node.left):
            return [node.right.value]
        return None
    # os.path.join(os.path.dirname(__file__), "definitions", ...)
    if isinstance(node, ast.Call) and _is_attr(node.func, "join"):
        args = node.args
        if not args or not _is_dirname_of_file(args[0]):
            return None
        rest = []
        for arg in args[1:]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                rest.append(arg.value)
            else:
                return None
        return rest or None
    return None


def _is_attr(node, name):
    return isinstance(node, ast.Attribute) and node.attr == name


def _is_file_parent(node):
    return (_is_attr(node, "parent")
            and isinstance(node.value, ast.Call)
            and any(isinstance(a, ast.Name) and a.id == "__file__"
                    for a in node.value.args))


def _is_dirname_of_file(node):
    return (isinstance(node, ast.Call) and _is_attr(node.func, "dirname")
            and any(isinstance(a, ast.Name) and a.id == "__file__"
                    for a in node.args))


def _is_shipped(directory, declared):
    return any(directory == d or d in directory.parents for d in declared)


def test_the_cleanup_catalog_definitions_are_in_the_build():
    """461 scanners live here, and the frozen build had none of them."""
    definitions = (SRC / "modules" / "cleanup" / "cleanup_scanner"
                   / "definitions").resolve()
    assert definitions.is_dir()
    assert _is_shipped(definitions, _declared_data_dirs()), (
        "cleanup_scanner/definitions is not in get_datas — frozen, "
        "load_catalog() globs an empty directory and returns no scanners")


def test_every_file_relative_data_directory_is_shipped():
    declared = _declared_data_dirs()
    missing = {
        directory: sites
        for directory, sites in _referenced_data_dirs().items()
        if not _is_shipped(directory, declared)
    }
    assert not missing, "\n".join(
        [""] + [f"{d.relative_to(ROOT).as_posix()}  (read at {', '.join(s)})"
                for d, s in sorted(missing.items())])


@pytest.mark.parametrize("relative", [
    "config",
    "src/ui/styles",
    "src/modules/tweaks/definitions",
    "src/modules/cleanup/cleanup_scanner/definitions",
])
def test_the_known_data_directories_are_all_declared(relative):
    assert _is_shipped((ROOT / relative).resolve(), _declared_data_dirs())
