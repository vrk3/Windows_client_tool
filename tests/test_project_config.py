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
