"""The version number lives in exactly one place.

`src/_version.py` calls itself "Single source of truth for the application
version" and was read by exactly one file — the About pane.
`version_info.txt`, which is what Windows shows in the exe's Properties
dialog and what an installer reads, carried a hand-maintained `1,0,0,0`
that nothing derived from it. And `core/logging_service.py` carried a stray
`__version__ = "0.1.0"` that meant nothing at all and was never read.

Three numbers agreeing by luck is not a version scheme: the first release
where someone bumps `_version.py` and forgets `version_info.txt` ships an
exe whose Properties disagree with its own About box.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _app_version() -> str:
    text = (ROOT / "src" / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    assert match, "src/_version.py does not define __version__"
    return match.group(1)


def test_only_version_py_defines_a_version():
    """A second __version__ anywhere in src/ is a number nobody maintains."""
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        if path.name == "_version.py":
            continue
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if re.match(r"\s*__version__\s*=", line):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}")
    assert offenders == [], (
        "these define a second version nobody keeps in step:\n  "
        + "\n  ".join(offenders))


def test_the_exe_version_resource_is_generated_not_hand_written():
    """version_info.txt is build output. The template is what is edited."""
    assert (ROOT / "version_info.txt.in").exists(), (
        "version_info.txt.in should hold the template, with {version} and "
        "{version_tuple} placeholders filled in at build time")


def test_the_generated_resource_matches_version_py():
    from pyinstaller_common import render_version_info

    rendered = render_version_info(str(ROOT))
    version = _app_version()
    tuple_form = ", ".join(version.split(".") + ["0"])

    assert f"filevers=({tuple_form})" in rendered
    assert f"prodvers=({tuple_form})" in rendered
    assert f"u'FileVersion', u'{version}.0'" in rendered
    assert f"u'ProductVersion', u'{version}.0'" in rendered


def test_the_rendered_resource_is_still_valid_python():
    """PyInstaller execs this file. A template that renders to something
    unparseable fails the build with a traceback from inside PyInstaller,
    which is a long way from the cause."""
    from pyinstaller_common import render_version_info

    compile(render_version_info(str(ROOT)), "version_info.txt", "exec")
