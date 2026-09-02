"""No plugin module depends on another in both directions.

Modules are supposed to be independent: that is what lets them be
registered in any order, tested alone, and moved between composite hosts
unchanged (CLAUDE.md's Composite Modules section says exactly this about
children). Two cycles had formed:

    process_explorer <-> dashboard    15 edges one way, 3 the other
    modules/ui       <-> cleanup      13 edges one way, 1 the other

Neither was a design decision. `process_explorer` was reaching into
`dashboard.procengine` — 5,792 lines of Qt-free process engine that belongs
to neither pane and now lives in `core/procengine`. `modules/ui` was not a
module at all: it registered nothing, held two widgets that import
cleanup's own scanners throughout, and now lives in
`modules/cleanup/components`.

A composite importing its own child is NOT a cycle and is expected — the
Dashboard hosts Process Explorer, so `dashboard -> process_explorer` is the
intended direction and stays.
"""
import ast
import collections
import pathlib

MODULES = pathlib.Path(__file__).resolve().parent.parent / "src" / "modules"


def _edges():
    """(importer, imported) -> the places it happens."""
    found = collections.defaultdict(list)
    for path in sorted(MODULES.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(MODULES).parts
        if not parts:
            continue
        owner = parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                if not name.startswith("modules."):
                    continue
                other = name.split(".")[1]
                if other != owner:
                    found[(owner, other)].append(
                        f"{path.relative_to(MODULES).as_posix()}:{node.lineno}")
    return found


def test_no_two_modules_import_each_other():
    edges = _edges()
    cycles = sorted({tuple(sorted((a, b)))
                     for (a, b) in edges if (b, a) in edges})
    detail = []
    for a, b in cycles:
        detail.append(f"{a} <-> {b}")
        for line in edges[(a, b)][:3]:
            detail.append(f"    {a} -> {b}: {line}")
        for line in edges[(b, a)][:3]:
            detail.append(f"    {b} -> {a}: {line}")
    assert cycles == [], (
        "these modules depend on each other in both directions:\n  "
        + "\n  ".join(detail))


def test_every_directory_under_modules_is_actually_a_module():
    """`modules/ui` registered nothing and was not a module. A directory in
    the plugin namespace that holds no BaseModule teaches every reader that
    the namespace does not mean what it says."""
    offenders = []
    for entry in sorted(MODULES.iterdir()):
        if not entry.is_dir() or entry.name.startswith("__"):
            continue
        source = "\n".join(
            p.read_text(encoding="utf-8", errors="replace")
            for p in entry.rglob("*.py") if "__pycache__" not in p.parts)
        if not any(base in source for base in
                   ("BaseModule", "LogReaderModule", "CompositeModule")):
            offenders.append(entry.name)
    assert offenders == [], (
        "these live under modules/ but define no module:\n  "
        + "\n  ".join(offenders))


def test_the_process_engine_stays_out_of_the_panes():
    """core/procengine is engine code — no Qt, so it is testable headless,
    and importable by Dashboard, Process Explorer and Security Dashboard
    alike without any of them depending on another."""
    engine = MODULES.parent / "core" / "procengine"
    assert engine.is_dir(), "core/procengine is missing"
    offenders = []
    for path in sorted(engine.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(n.startswith("PyQt6") or n.startswith("modules.")
                   for n in names):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], (
        "the engine must not depend on Qt or on any pane:\n  "
        + "\n  ".join(offenders))
