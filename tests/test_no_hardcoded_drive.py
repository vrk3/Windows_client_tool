"""Windows does not have to be on C:.

It usually is, which is exactly why hardcoding it survives review: on the
machine you are testing on, `r"C:\\Windows\\Prefetch"` is right. On a machine
where Windows is on D:, the scanner reports "0 B to clean" and never says it
looked somewhere that does not exist. Nothing errors, nothing is logged, and
the answer is simply wrong.

There were 136 such literals across 31 files when this was written. The
cleanup catalog (audit #14) removed the largest cluster by expressing paths
as `%windir%`; `core.windows_utils` has `system_root()`, `system_drive()`,
`program_files()`, `program_data()` and `system32()` for the rest.

A RATCHET: BUDGET only ever falls, in the same commit that removes
literals.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

#: 136 before the cleanup catalog (audit #14) expressed its paths as
#: %windir%; 73 after; 64 once the single-constant modules moved to
#: the windows_utils helpers. Only ever lower it.
BUDGET = 64

#: Where a drive letter is the subject rather than a path to open:
#: `windows_utils` defines the fallbacks, and a UI placeholder like
#: "C:\\path\\to\\program.exe --flag" is example text shown to the user.
EXEMPT = {
    "core/windows_utils.py",
    "modules/startup_manager/startup_module.py",
}


def hardcoded_drive_literals():
    """String constants containing a drive letter, excluding docstrings."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in EXEMPT:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        if "C:\\" not in source:
            continue
        tree = ast.parse(source)

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc:
                    docstrings.add(doc)

        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if "C:\\" not in node.value or node.value in docstrings:
                continue
            found.append(f"{rel}:{node.lineno}  {node.value[:60]}")
    return found


def test_the_hardcoded_drive_count_only_falls():
    literals = hardcoded_drive_literals()
    assert len(literals) <= BUDGET, (
        f"{len(literals)} hardcoded drive letters, budget is {BUDGET}.\n"
        "Use core.windows_utils.system_root()/program_files()/... , or "
        "%windir% in a catalog definition.\nNew ones:\n  "
        + "\n  ".join(literals[BUDGET:BUDGET + 15]))


def test_the_budget_is_not_stale():
    count = len(hardcoded_drive_literals())
    assert count > BUDGET - 15, (
        f"only {count} left against a budget of {BUDGET}: lower BUDGET to "
        f"{count} so the ratchet keeps its grip.")


def test_the_helpers_answer_from_the_environment(monkeypatch):
    """The point of the helpers — they must actually read the environment,
    not just wrap the same constant."""
    from core import windows_utils

    monkeypatch.setenv("SystemRoot", r"D:\Windows")
    monkeypatch.setenv("SystemDrive", "D:")
    monkeypatch.setenv("ProgramFiles", r"D:\Program Files")
    monkeypatch.setenv("ProgramData", r"D:\ProgramData")

    assert windows_utils.system_root() == r"D:\Windows"
    assert windows_utils.system_drive() == "D:"
    assert windows_utils.program_files() == r"D:\Program Files"
    assert windows_utils.program_data() == r"D:\ProgramData"
    assert windows_utils.system32() == r"D:\Windows\System32"


def test_the_helpers_still_answer_when_the_environment_is_stripped(monkeypatch):
    """A service account or a sanitised environment can be missing these."""
    from core import windows_utils

    for name in ("SystemRoot", "windir", "SystemDrive", "ProgramFiles",
                 "ProgramFiles(x86)", "ProgramData", "ALLUSERSPROFILE"):
        monkeypatch.delenv(name, raising=False)

    assert windows_utils.system_root().endswith("Windows")
    assert windows_utils.system_drive().endswith(":")
    assert "Program Files" in windows_utils.program_files()
    assert "Program Files (x86)" in windows_utils.program_files(x86=True)
    assert windows_utils.program_data().endswith("ProgramData")
