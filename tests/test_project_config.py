"""The project has a configuration file, and it describes this project.

Written because there wasn't one: imports worked only via two separate
sys.path.insert calls (src/main.py and tests/conftest.py), and nothing in
the tree said what Python version or lint rules this code is held to.
"""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _config() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as handle:
        return tomllib.load(handle)


def test_the_project_declares_itself():
    project = _config()["project"]
    assert project["name"] == "winclienttool"
    assert project["requires-python"] == ">=3.12"


def test_ruff_knows_where_the_source_is():
    ruff = _config()["tool"]["ruff"]
    assert "src" in ruff["src"]
    assert ruff["line-length"] == 100


def test_the_version_comes_from_the_one_file_that_holds_it():
    """_version.py calls itself the single source of truth; make it one."""
    project = _config()["project"]
    assert project["dynamic"] == ["version"]


def test_pytest_is_configured_in_one_place():
    """CI and a local run must be the same command.

    They were not: the workflow passed --timeout=120 while pytest-timeout
    was absent from the venv, so the identical command exited 4 locally
    with "unrecognized arguments: --timeout=120".
    """
    pytest_cfg = _config()["tool"]["pytest"]["ini_options"]
    assert "--timeout=120" in pytest_cfg["addopts"]
    assert pytest_cfg["testpaths"] == ["tests"]


def test_the_temp_root_is_moved_off_the_broken_symlink():
    r"""Session teardown died walking %TEMP%\pytest-of-<user>\pytest-current
    — a symlink this machine cannot stat at all — and took the pass/fail
    summary with it. Retention policy does NOT avoid that walk; only
    relocating basetemp does."""
    pytest_cfg = _config()["tool"]["pytest"]["ini_options"]
    assert "--basetemp=" in pytest_cfg["addopts"]
    assert pytest_cfg["tmp_path_retention_policy"] == "none"


def test_the_environment_coupled_markers_are_registered():
    markers = " ".join(_config()["tool"]["pytest"]["ini_options"]["markers"])
    for name in ("slow", "real_machine", "needs_admin"):
        assert name in markers
