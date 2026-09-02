# Codebase Audit — Forty Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the forty findings from the 2026-09-02 codebase audit, highest impact first, each as its own reviewable commit.

**Architecture:** No new subsystems. The work is three shapes: (a) point defects with a named file and line, (b) *adoption* of infrastructure the codebase already built and then only half-used (`core/semantic_colors.py`, `core/windows_utils.ps_quote`, `tweaks/definitions/*.json` as a data-driven catalog), and (c) the project scaffolding that was never added at all (`pyproject.toml`, lint, pytest config). Scaffolding goes first, because every later task wants to run the same lint and the same test command.

**Tech Stack:** Python 3.12, PyQt6, pytest, pywin32/WMI, PyInstaller. Windows-only.

**Spec:** The audit report — https://claude.ai/code/artifact/618a5fb5-4a47-40b7-b685-c9336d8590a5 — numbered 01–40. Every task below names the audit item it closes.

## Global Constraints

- **Windows-only, Python 3.12+, PyQt6 ≥6.6.** No task may add a dependency that is not already in `requirements.txt` except where a task says so explicitly (`pytest-timeout`, `pytest-xdist`, `ruff`, `mypy` — all dev-only).
- **`scan/`, `store/`, parsers and readers stay Qt-free.** TreeSize's `scan/`+`store/`, Log Viewer's `cmtrace_parser.py`/`log_reader.py`, and all ten non-UI files in `gpresult/` must not gain a PyQt6 import. That split is what lets ~450 engine tests run headless.
- **A refusal is never an answer.** `None` means "could not look"; `False` means "looked, and no". No task may collapse the two. See `security_reader.py` and `tweak_engine.py`.
- **Silent exception swallowing is forbidden** (CLAUDE.md). Any handler this plan touches logs at `warning` or above.
- **Do not "clean up" two things CLAUDE.md records as deliberate:** the seven `shell=True` call sites, and the modules that hand-roll `QMessageBox.question()` rather than using `core/confirm.py`'s `confirm_destructive()`.
- **Test command:** `QT_QPA_PLATFORM=offscreen python -m pytest -q` from the project root. After Task 2 this needs no flags.
- **Every task ends green.** Full suite, not just the task's own test.
- **Branch:** `feat/audit-p1`, off `6753224`. One commit per task.

## Priority mapping

| Priority | Audit items | Tasks |
|---|---|---|
| **P1** — high impact | 01, 02, 03, 09, 10, 14, 15, 20, 25, 26, 31, 32, 33, 34 | 1–13 |
| **P2** — medium impact | 04, 05, 06, 07, 11, 12, 16, 17, 21, 22, 23, 27, 28, 29, 35, 36, 37, 38 | 14–31 |
| **P3** — low impact | 08, 13, 18, 19, 24, 30, 39, 40 | 32–39 |

---

# P1 — High impact

## Task 1: Project configuration (audit #33)

The tree has no `pyproject.toml`, no `setup.cfg`, no lint or type config. Imports work only because `src/main.py:10` and `tests/conftest.py:5` each call `sys.path.insert`. This task adds the file every later task depends on.

**Files:**
- Create: `pyproject.toml`
- Modify: `requirements.txt`
- Test: `tests/test_project_config.py`

**Interfaces:**
- Produces: a `pyproject.toml` whose `[tool.ruff]` and `[tool.mypy]` sections every later task is checked against. Task 2 adds `[tool.pytest.ini_options]` to the same file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_project_config.py
"""The project has a configuration file, and it describes this project.

Written because there wasn't one: imports worked only via two separate
sys.path.insert calls, and nothing in the tree said what Python version or
lint rules this code is held to.
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_project_config.py -q`
Expected: FAIL — `FileNotFoundError: pyproject.toml`

- [ ] **Step 3: Write the configuration**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "winclienttool"
description = "Windows 11 optimization and system diagnostics utility"
requires-python = ">=3.12"
dynamic = ["version"]
dependencies = [
    "PyQt6>=6.6",
    "psutil>=5.9",
    "pywin32>=306",
    "WMI>=1.5.1",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=7.0", "pytest-timeout>=2.2", "pytest-xdist>=3.5", "ruff>=0.5", "mypy>=1.10"]

[tool.setuptools.dynamic]
version = { attr = "_version.__version__" }

[tool.setuptools]
package-dir = { "" = "src" }

[tool.ruff]
src = ["src", "tests"]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
# Deliberately narrow to start. The tree is 92k lines written without a
# linter; turning on the full default set produces thousands of findings
# and teaches everyone to ignore the tool. Each later task may widen this.
select = ["E4", "E7", "E9", "F", "W6"]
ignore = [
    "F403", "F405",  # cleanup_scanner/__init__.py star-imports — audit #19 (Task 35)
]

[tool.ruff.lint.per-file-ignores]
"src/modules/cleanup/cleanup_scanner/__init__.py" = ["F401"]

[tool.mypy]
python_version = "3.12"
mypy_path = "src"
# Advisory for now: 907 of 4,744 functions have no return annotation.
# Tightening this is Task 30's job, not this one's.
ignore_missing_imports = true
check_untyped_defs = false
```

- [ ] **Step 4: Record the dev dependencies**

Append to `requirements.txt`, replacing the existing `# Dev / test only` block:

```
# Dev / test only. Also declared in pyproject.toml's [project.optional-dependencies]
# dev extra; this file stays the one CI installs from.
pytest>=7.0
pytest-timeout>=2.2
pytest-xdist>=3.5
ruff>=0.5
```

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_project_config.py -q`
Expected: 3 passed

Then `python -m ruff check src tests` — expect findings; do not fix them here. Note the count in the commit message so later tasks can show it falling.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt tests/test_project_config.py
git commit -m "build: add pyproject.toml with ruff and mypy configuration (audit #33)"
```

---

## Task 2: Make the test run report its own verdict (audit #31, #34)

A full run reaches 100% and then dies in `pytest_sessionfinish` with `PermissionError: [WinError 5] ... Temp\pytest-of-iorda\pytest-current`, so the `N passed, M failed` line and every traceback are lost. Separately, CI passes `--timeout=120` while `pytest-timeout` is not installed locally, so `python -m pytest --timeout=120` exits 4 here with "unrecognized arguments".

**Files:**
- Modify: `pyproject.toml` (add `[tool.pytest.ini_options]`)
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/conftest.py`
- Test: `tests/test_project_config.py` (extend)

**Interfaces:**
- Consumes: `pyproject.toml` from Task 1.
- Produces: markers `slow`, `real_machine` and `needs_admin`, registered in config. Task 3 applies them.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_project_config.py

def test_pytest_is_configured_in_one_place():
    """CI and a local run must be the same command.

    They were not: the workflow passed --timeout=120 while pytest-timeout
    was absent from the venv, so the identical command exited 4 locally
    with "unrecognized arguments: --timeout=120".
    """
    pytest_cfg = _config()["tool"]["pytest"]["ini_options"]
    assert "--timeout=120" in pytest_cfg["addopts"]
    assert pytest_cfg["testpaths"] == ["tests"]


def test_the_temp_directory_is_not_left_for_pytest_to_clean():
    """Session teardown died on %TEMP%\\pytest-of-<user>\\pytest-current,
    taking the pass/fail summary with it. Retaining nothing avoids the
    junction that trips cleanup_dead_symlinks."""
    pytest_cfg = _config()["tool"]["pytest"]["ini_options"]
    assert pytest_cfg["tmp_path_retention_policy"] == "none"


def test_the_environment_coupled_markers_are_registered():
    markers = " ".join(_config()["tool"]["pytest"]["ini_options"]["markers"])
    for name in ("slow", "real_machine", "needs_admin"):
        assert name in markers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_project_config.py -q`
Expected: FAIL — `KeyError: 'pytest'`

- [ ] **Step 3: Add the pytest configuration**

```toml
# append to pyproject.toml

[tool.pytest.ini_options]
testpaths = ["tests"]
# --timeout is a safety net against a genuine hang eating a whole CI job
# silently. It uses pytest-timeout's "thread" method, which can only
# interrupt regular Python execution — a test blocked in a native Qt call
# (a stray dialog .exec()) is not preempted by it.
addopts = "-q --timeout=120"
# Retaining nothing: pytest's own tmpdir cleanup walks
# %TEMP%\pytest-of-<user>\pytest-current, a junction it cannot stat on this
# machine, and raises PermissionError inside pytest_sessionfinish — after
# the last test, before the summary is printed. The whole verdict was lost
# to it.
tmp_path_retention_policy = "none"
markers = [
    "slow: takes seconds, not milliseconds",
    "real_machine: reads or writes the actual machine (WMI, registry, services) rather than a fixture",
    "needs_admin: requires an elevated process; skipped otherwise",
]
```

- [ ] **Step 4: Install the missing dependency**

Run: `python -m pip install "pytest-timeout>=2.2" "pytest-xdist>=3.5" "ruff>=0.5"`

- [ ] **Step 5: Make CI run the same bare command**

In `.github/workflows/ci.yml`, replace the `Run tests` step's `run:` line with:

```yaml
        # Flags live in pyproject.toml's [tool.pytest.ini_options] so this
        # is exactly the command a developer runs locally. When the two
        # drift, "it passed for me" stops meaning anything.
        run: python -m pytest
```

Leave the `QT_QPA_PLATFORM: offscreen` env and the explanatory comment above it in place.

- [ ] **Step 6: Run the full suite and read the verdict**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest`
Expected: the run *ends with a summary line*. It will read approximately `5 failed, 4006 passed, 5 skipped, 1 error`. Those failures are Task 3's subject — do not fix them here. This task's deliverable is that the number is visible at all.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml tests/test_project_config.py requirements.txt
git commit -m "test: configure pytest in pyproject so a run reports its verdict (audit #31, #34)"
```

---

## Task 3: Un-couple six tests from this particular machine (audit #32)

With Task 2 done the verdict is visible: `5 failed, 4006 passed, 5 skipped, 1 error`. Every one of the six is coupled to the machine rather than to the code, which is why CI is green and the developer's own run is red.

| Test | Why it fails here |
|---|---|
| `test_firewall_table_fit.py::test_short_columns_fit_their_widest_real_value` | `column 'Action' clips 'Allow'`, `72 <= 70` — real Qt font metrics |
| `test_firewall_table_fit.py::test_program_column_holds_an_ordinary_system32_path` | `384 <= 380` — same |
| `test_security_history_tab.py::test_the_history_columns_are_sized_to_their_contents` | `224 >= 420` — same |
| `test_backup_service.py::test_a_real_export_reports_the_file_it_wrote` | runs a real `reg export`; `ERROR: Unable to write to the file` |
| `test_procengine_details.py::test_the_snapshot_source_honours_a_budget` | `assert 0 > 0` — a wall-clock budget |
| `test_services_tab.py::test_declining_the_confirmation_runs_no_action` (error at setup) | polls live WMI for 12s, `the service table never filled from WMI` |

**Files:**
- Modify: `tests/test_firewall_table_fit.py`
- Modify: `tests/test_security_history_tab.py`
- Modify: `tests/test_backup_service.py`
- Modify: `tests/test_procengine_details.py`
- Modify: `tests/test_services_tab.py`
- Modify: `src/modules/firewall_rules/firewall_manager_module.py` (default column widths)
- Modify: `src/modules/security_dashboard/security_module.py` (history column widths)

**Interfaces:**
- Consumes: the `slow`, `real_machine` and `needs_admin` markers registered in Task 2.

- [ ] **Step 1: Fix the column-fit tests to assert the rule, not the pixels**

The tests are right that a bounded-vocabulary column must not clip. What is wrong is that the *production defaults* are pixel constants (`70`, `380`, `420`) chosen against one machine's fonts. Make the widths derive from the same metrics the test measures.

In `src/modules/firewall_rules/firewall_manager_module.py`, replace the hardcoded default widths with a helper:

```python
def _fit_to_contents(table, columns: "Iterable[int]", padding: int = 24) -> None:
    """Size each column to its widest rendered value.

    The defaults used to be pixel constants picked on one machine. Qt's own
    font metrics differ with DPI, the installed UI font and the Windows text
    scale, so 70px held "Allow" on the CI runner and clipped it at 72px
    here — a real failure of the rule the test states, dressed up as a
    flaky test.
    """
    metrics = table.fontMetrics()
    for col in columns:
        header = table.horizontalHeaderItem(col)
        widest = metrics.horizontalAdvance(header.text()) if header else 0
        for row in range(table.rowCount()):
            item = table.item(row, col)
            if item is not None:
                widest = max(widest, metrics.horizontalAdvance(item.text()))
        table.setColumnWidth(col, widest + padding)
```

Call it after the table is populated, for the bounded columns `(1, 2, 3, 4, 8)` and the program column `7`. Do the same for the Security Dashboard history table's column 1.

- [ ] **Step 2: Run the three column tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_firewall_table_fit.py tests/test_security_history_tab.py -q`
Expected: PASS, on this machine and on any other.

- [ ] **Step 3: Mark the three genuinely environment-dependent tests**

These three cannot be made deterministic — they are the point. Mark them so an ordinary run excludes them and a deliberate run includes them.

```python
# tests/test_backup_service.py
@pytest.mark.real_machine
@pytest.mark.needs_admin
def test_a_real_export_reports_the_file_it_wrote():
    ...

# tests/test_procengine_details.py
@pytest.mark.slow
@pytest.mark.real_machine
def test_the_snapshot_source_honours_a_budget():
    ...

# tests/test_services_tab.py — on the fixture whose setup polls WMI
@pytest.fixture
@pytest.mark.real_machine
def scanned_services_tab(...):
    ...
```

For `test_services_tab.py` the marker belongs on every test using that fixture; add `pytestmark = [pytest.mark.real_machine, pytest.mark.slow]` at module level instead.

- [ ] **Step 4: Deselect them by default, keep them runnable**

Extend `addopts` in `pyproject.toml`:

```toml
addopts = "-q --timeout=120 -m 'not real_machine'"
```

and add to the CI workflow, after the existing test step:

```yaml
      - name: Run the real-machine tests
        env:
          QT_QPA_PLATFORM: offscreen
        # These read the actual machine — WMI, the registry, live services.
        # They are excluded from the default run because they fail for
        # environmental reasons rather than code reasons, and a suite that
        # is normally red teaches everyone to ignore it. Run separately, and
        # allowed to fail, so their signal is visible without gating merges.
        continue-on-error: true
        run: python -m pytest -m real_machine
```

- [ ] **Step 5: Run the full suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest`
Expected: `0 failed`. Confirm with `python -m pytest -m real_machine --collect-only -q` that the marked tests are still reachable.

- [ ] **Step 6: Commit**

```bash
git add tests/ src/modules/firewall_rules/firewall_manager_module.py src/modules/security_dashboard/security_module.py pyproject.toml .github/workflows/ci.yml
git commit -m "test: derive column widths from font metrics, mark real-machine tests (audit #32)"
```

---

## Task 4: Closing to tray must not kill auto-refresh (audit #01)

`MainWindow.closeEvent` stops **and clears** `_module_refresh_timers` before it checks `app.minimize_to_tray`. With that setting on it then calls `event.ignore()` and hides — but the dict is already empty, so `showEvent`'s resume loop has nothing to restart. Every live pane stops updating for the rest of the session, and the only way back is selecting a different module.

**Files:**
- Modify: `src/ui/main_window.py:511-531`
- Test: `tests/test_minimize_to_tray_refresh.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_minimize_to_tray_refresh.py
"""Hiding to the tray must not be a one-way door for auto-refresh.

closeEvent cleared _module_refresh_timers before it checked
minimize_to_tray, so the ignore-and-hide path left showEvent with an empty
dict to resume. Live panes went quiet for the rest of the session.
"""
from PyQt6.QtGui import QCloseEvent


def test_hiding_to_the_tray_keeps_the_refresh_timers(main_window_with_refreshing_module):
    window = main_window_with_refreshing_module
    window._app.config.set("app.minimize_to_tray", True)
    assert window._module_refresh_timers, "precondition: a timer is running"

    event = QCloseEvent()
    window.closeEvent(event)

    assert not event.isAccepted(), "closing to tray must not accept the close"
    assert window._module_refresh_timers, "the timers must survive to be resumed"


def test_a_real_close_still_stops_the_timers(main_window_with_refreshing_module):
    window = main_window_with_refreshing_module
    window._app.config.set("app.minimize_to_tray", False)

    window.closeEvent(QCloseEvent())

    assert not window._module_refresh_timers
```

Add a `main_window_with_refreshing_module` fixture to the test file that builds a `MainWindow` over a stub `App` and registers one module whose `get_refresh_interval()` returns `60_000`.

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_minimize_to_tray_refresh.py -q`
Expected: FAIL — `assert window._module_refresh_timers` is empty after `closeEvent`.

- [ ] **Step 3: Move the teardown below the tray branch**

```python
    def closeEvent(self, event) -> None:
        # The minimize-to-tray check comes FIRST. Tearing the refresh timers
        # down above it and then calling event.ignore() left showEvent with
        # an empty dict to resume from, so hiding to the tray silently ended
        # auto-refresh for the rest of the session.
        if self._app.config.get("app.minimize_to_tray", False):
            event.ignore()
            self.hide()
            self._tray_manager.show_balloon(
                "Still Running",
                "Windows Tweaker is minimized to the tray. Double-click to restore.",
            )
            return

        for timer in self._module_refresh_timers.values():
            timer.stop()
        self._module_refresh_timers.clear()

        update_worker = getattr(self, "_update_worker", None)
        if update_worker is not None:
            update_worker.cancel()

        size = self.size()
        self._app.config.set("app.window_size", [size.width(), size.height()])
        self._app.shutdown()
        event.accept()
        super().closeEvent(event)
```

Note `hideEvent` already stops the timers on its own when the window hides, so the tray path is still not left with timers ticking against a hidden window.

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_minimize_to_tray_refresh.py tests/test_always_on_top.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ui/main_window.py tests/test_minimize_to_tray_refresh.py
git commit -m "fix(ui): keep refresh timers alive when closing to the tray (audit #01)"
```

---

## Task 5: Quote the elevated relaunch command line (audit #02)

`restart_as_admin()` passes `" ".join(sys.argv)` to `ShellExecuteW`. A user profile named `John Doe`, or an install under `C:\Program Files\`, and the elevated relaunch receives a truncated argument list. `security_dashboard/elevated_helper.py:39` already names this file as the one that still gets it wrong, and already uses the fix.

**Files:**
- Modify: `src/core/admin_utils.py`
- Test: `tests/test_admin_utils.py` (extend)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_admin_utils.py
import subprocess
from core import admin_utils


def test_a_path_with_a_space_survives_the_relaunch(monkeypatch):
    """'" ".join(sys.argv)' turned one argument into two.

    C:\\Users\\John Doe\\... and C:\\Program Files\\... are both ordinary,
    and both broke the elevated relaunch silently — ShellExecuteW got a
    command line the child parsed as a different set of arguments.
    """
    monkeypatch.setattr(admin_utils.sys, "argv",
                        [r"C:\Users\John Doe\app\main.py", "--stages", "wu,winget"])
    captured = {}

    def fake_shell_execute(hwnd, verb, file, params, directory, show):
        captured["params"] = params
        return 42

    monkeypatch.setattr(admin_utils, "_shell_execute", fake_shell_execute)
    monkeypatch.setattr(admin_utils.sys, "exit", lambda code=0: None)

    admin_utils.restart_as_admin()

    assert captured["params"] == subprocess.list2cmdline(
        [r"C:\Users\John Doe\app\main.py", "--stages", "wu,winget"])
    assert '"C:\\Users\\John Doe\\app\\main.py"' in captured["params"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_admin_utils.py -q`
Expected: FAIL — `AttributeError: module 'core.admin_utils' has no attribute '_shell_execute'`

- [ ] **Step 3: Rewrite the module**

```python
# src/core/admin_utils.py
import ctypes
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_SW_SHOWNORMAL = 1


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except (AttributeError, OSError):
        return False


def _shell_execute(hwnd, verb: str, file: str, params: str, directory, show: int) -> int:
    """Seam for tests — the real ShellExecuteW cannot be called in a test run."""
    return ctypes.windll.shell32.ShellExecuteW(hwnd, verb, file, params, directory, show)


def get_restart_as_admin_command() -> dict:
    """(executable, argument string) for ShellExecuteW(..., "runas", ...).

    The arguments are quoted with `subprocess.list2cmdline`, not joined on a
    space. Joining broke on the first path containing one, and both
    C:\\Program Files\\ and a two-word user profile are ordinary. The same
    reasoning, and the same fix, is written up at
    modules/security_dashboard/elevated_helper.py:39.
    """
    return {"executable": sys.executable, "args": list(sys.argv)}


def restart_as_admin() -> None:
    info = get_restart_as_admin_command()
    arguments = subprocess.list2cmdline(info["args"])
    result = _shell_execute(None, "runas", info["executable"], arguments, None, _SW_SHOWNORMAL)
    # ShellExecuteW returns <= 32 on failure. The commonest by far is the
    # user declining the UAC prompt, which is not an error — but it does
    # mean we must NOT exit, or declining the prompt closes the app.
    if result is not None and int(result) <= 32:
        logger.info("elevated relaunch was not started (ShellExecuteW returned %s)", result)
        return
    sys.exit(0)
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_admin_utils.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/core/admin_utils.py tests/test_admin_utils.py
git commit -m "fix(core): quote the elevated relaunch command line (audit #02)"
```

---

## Task 6: One subprocess runner (audit #15)

`CREATE_NO_WINDOW` is declared in 42 of 378 files. Each of the 112 call sites reimplements creation flags, encoding and error handling — and 31 of them forget the timeout. One runner fixes Task 7 in a single place and gives the app one spot that logs what it shelled out to.

**Files:**
- Create: `src/core/run.py`
- Test: `tests/test_core_run.py`

**Interfaces:**
- Produces:
  - `run(argv: Sequence[str], *, timeout: float = 60.0, cwd: str | None = None, check: bool = False) -> CompletedProcess[str]`
  - `run_ps(script: str, *, timeout: float = 120.0) -> CompletedProcess[str]`
  - `CREATE_NO_WINDOW: int`
  - Both raise nothing on non-zero exit unless `check=True`; both return `returncode = -1` with the reason in `stderr` on timeout, so a caller never has to distinguish "timed out" from "crashed" by exception type.
  - Task 7 replaces call sites with these.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core_run.py
"""One place that knows how to shell out.

Written because 42 files each declared their own CREATE_NO_WINDOW, and 31
of 82 run/check_output/call sites had no timeout at all — a hung sc, netsh
or dism pinned a thread-pool slot for the life of the process.
"""
import subprocess
import pytest
from core import run as run_mod


def test_a_command_that_works_comes_back_with_its_output():
    result = run_mod.run(["cmd", "/c", "echo", "hello"])
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_a_timeout_is_reported_not_raised():
    """A caller wanting to show 'this took too long' should not have to
    catch TimeoutExpired around every call — that is exactly the discipline
    31 call sites failed to keep."""
    result = run_mod.run(["cmd", "/c", "ping", "-n", "10", "127.0.0.1"], timeout=0.4)
    assert result.returncode == -1
    assert "timed out" in result.stderr.lower()


def test_check_still_raises_when_the_caller_asks_for_it():
    with pytest.raises(subprocess.CalledProcessError):
        run_mod.run(["cmd", "/c", "exit", "3"], check=True)


def test_there_is_a_default_timeout():
    import inspect
    default = inspect.signature(run_mod.run).parameters["timeout"].default
    assert isinstance(default, (int, float)) and default > 0


def test_powershell_runs_without_a_profile():
    """A user's PowerShell profile can print banners, change the culture, or
    fail outright — none of which belong in a reading this app takes."""
    result = run_mod.run_ps("Write-Output 'ok'")
    assert "ok" in result.stdout
    assert result.returncode == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_core_run.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.run'`

- [ ] **Step 3: Write the runner**

```python
# src/core/run.py
"""The one way this app shells out.

Before this existed, 42 files declared their own CREATE_NO_WINDOW and 112
call sites each re-decided encoding, error handling and — in 31 cases,
not at all — the timeout. A `sc`, `netsh` or `dism` that never returns
pins a QThreadPool slot for the life of the process, and the pane waiting
on it sits on its spinner forever.

Two rules this module exists to enforce:

* **Every call has a timeout.** It is a keyword argument with a default,
  not something a caller must remember.
* **A timeout is a result, not an exception.** Callers overwhelmingly want
  to show the user "that took too long" in the same place they show
  "that failed", so a timeout comes back as returncode -1 with the reason
  in stderr. `check=True` still raises for the callers that want it.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

#: Suppress the console window a subprocess would otherwise flash up in a
#: windowed build. Windows-only, and the whole reason 42 files each had
#: their own copy of this constant.
CREATE_NO_WINDOW = 0x08000000

DEFAULT_TIMEOUT = 60.0
PS_DEFAULT_TIMEOUT = 120.0


def run(
    argv: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    cwd: Optional[str] = None,
    check: bool = False,
    input_text: Optional[str] = None,
) -> "subprocess.CompletedProcess[str]":
    """Run `argv` and return its result. Never hangs.

    `argv` is a list, never a string — this function does not take
    `shell=True`. The seven call sites in this codebase that legitimately
    need a shell are listed in CLAUDE.md and stay where they are.
    """
    logger.debug("run: %s (timeout=%ss)", subprocess.list2cmdline(list(argv)), timeout)
    try:
        return subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            check=check,
            input=input_text,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("run: timed out after %ss: %s",
                       timeout, subprocess.list2cmdline(list(argv)))
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=-1,
            stdout=_as_text(exc.stdout),
            stderr=f"timed out after {timeout}s",
        )


def run_ps(script: str, *, timeout: float = PS_DEFAULT_TIMEOUT) -> "subprocess.CompletedProcess[str]":
    """Run a PowerShell script block.

    `-NoProfile` because a user's profile can print banners, change the
    culture or fail outright, none of which belongs in a reading this app
    takes. Values interpolated into `script` must go through
    `core.windows_utils.ps_quote` first.
    """
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        timeout=timeout,
    )


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
```

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_core_run.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/core/run.py tests/test_core_run.py
git commit -m "feat(core): add the one subprocess runner, with a mandatory timeout (audit #15)"
```

---

## Task 7: No subprocess call without a timeout (audit #03)

31 of 82 `subprocess.run`/`check_output`/`call` sites have no `timeout=`.

**Files:**
- Modify: `src/core/backup_service.py:217,498,512`
- Modify: `src/modules/services_manager/services_module.py:103,201,207,218`
- Modify: `src/modules/quick_fix/fix_actions.py:82,106,127`
- Modify: `src/modules/network_extras/net_extras_module.py:121,125,135`
- Modify: `src/modules/network_diagnostics/network_tools.py:160,181`
- Modify: `src/modules/debloat/debloat_scanner.py:88`
- Modify: `src/modules/registry_explorer/registry_module.py:165`
- Modify: `src/modules/remote_tools/remote_module.py:38`
- Modify: `src/modules/tweaks/app_catalog.py:316,437`
- Modify: the remaining sites the guard test names
- Test: `tests/test_no_untimed_subprocess.py`

**Interfaces:**
- Consumes: `core.run.run` and `core.run.run_ps` from Task 6.

- [ ] **Step 1: Write the guard test**

```python
# tests/test_no_untimed_subprocess.py
"""Every subprocess call states how long it is willing to wait.

31 of 82 did not. A `sc`, `netsh` or `dism` that never returns pins a
QThreadPool slot for the life of the process; the pane waiting on it shows
a spinner that never stops, and no log line ever explains why.

This test is the reason that number cannot climb back up.
"""
import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

# subprocess.Popen is exempt: it does not block, so a timeout is not the
# right tool — the caller owns the process handle and decides.
BLOCKING = {"run", "check_output", "check_call", "call"}


def _offenders():
    found = []
    for path in SRC.rglob("*.py"):
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
            found.append(f"{path.relative_to(SRC).as_posix()}:{node.lineno}")
    return found


def test_no_blocking_subprocess_call_omits_its_timeout():
    offenders = _offenders()
    assert offenders == [], (
        "these calls can hang forever — pass timeout=, or use core.run.run "
        "which supplies one:\n  " + "\n  ".join(offenders))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_no_untimed_subprocess.py -q`
Expected: FAIL, listing 31 locations.

- [ ] **Step 3: Fix each site**

Work through the list the test prints. For each, prefer replacing the call with `core.run.run`:

```python
# before — src/modules/services_manager/services_module.py
result = subprocess.run(["sc", "qc", name], capture_output=True, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW)

# after
from core.run import run
result = run(["sc", "qc", name], timeout=15)
```

Where the call is inside a worker and a long wait is legitimate (`dism`, `sfc`, `Compact-WinSxS`), pass an explicit generous timeout rather than none, and say why:

```python
# DISM component cleanup genuinely runs for minutes on a machine that has
# not been serviced in a while. Ten is past any real run and short of
# "never returns".
result = run(["dism", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], timeout=600)
```

Do not change the three `shell=True` calls in `backup_service.py`/`tweak_engine.py` to `run()` — they need a shell (CLAUDE.md records why). Add `timeout=` to them in place.

- [ ] **Step 4: Run the guard test and the full suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_no_untimed_subprocess.py -q`
Expected: PASS

Run: `QT_QPA_PLATFORM=offscreen python -m pytest`
Expected: `0 failed`

- [ ] **Step 5: Commit**

```bash
git add src tests/test_no_untimed_subprocess.py
git commit -m "fix: give every blocking subprocess call a timeout (audit #03)"
```

---

## Task 8: Build module widgets lazily (audit #09)

`MainWindow.register_module` calls `create_widget()` on all 33 registered modules before the window is shown, so the user pays for 32 panes they are not looking at. Measured on this machine: **1.78s**, against 0.17s to import every module package and 0.05s to stand up `App`. Widget construction *is* the startup cost.

`CompositeModule` already does lazy tabs, and CLAUDE.md records the trap: never `removeTab`/`insertTab` to swap a built widget in — each page is permanent and the child is added into its layout.

**Files:**
- Modify: `src/ui/main_window.py`
- Test: `tests/test_lazy_module_widgets.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lazy_module_widgets.py
"""A module's widget is built when it is first shown, not at launch.

Building all 33 up front cost 1.78s of a 2.10s startup, of which Tweaks
alone was 1.28s — all of it for panes the user is not looking at.
"""
from PyQt6.QtWidgets import QLabel, QWidget
from core.base_module import BaseModule


class _CountingModule(BaseModule):
    name = "Counter"
    icon = ""
    description = ""
    group = "TOOLS"

    def __init__(self):
        super().__init__()
        self.builds = 0

    def create_widget(self) -> QWidget:
        self.builds += 1
        return QLabel("built")


def test_registering_a_module_does_not_build_its_widget(main_window, counting_module):
    main_window.register_module(counting_module)
    assert counting_module.builds == 0


def test_selecting_it_builds_it_once(main_window, counting_module):
    main_window.register_module(counting_module)
    main_window._on_module_selected("Counter")
    assert counting_module.builds == 1
    main_window._on_module_selected("Counter")
    assert counting_module.builds == 1, "a second visit must reuse the widget"


def test_the_first_module_is_still_visible_after_show(main_window, counting_module):
    """The auto-selected first module must be built by the time the window
    is on screen, or the app opens on an empty pane."""
    main_window.register_module(counting_module)
    main_window.showEvent(None)
    assert counting_module.builds == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_lazy_module_widgets.py -q`
Expected: FAIL — `assert 1 == 0`, the widget was built during `register_module`.

- [ ] **Step 3: Give each module a permanent page**

In `register_module`, add a permanent container per module and record the module as unbuilt:

```python
    def register_module(self, module: BaseModule) -> None:
        """Register a module: reserve its page, add to sidebar and stack.

        The widget itself is NOT built here. Building all 33 up front cost
        1.78s of a 2.10s startup for panes nobody was looking at. The page
        is permanent and the real widget is added into its layout on first
        selection — never removeWidget/insertWidget, which re-enters the
        handler that asked for the build (the same trap CompositeModule
        documents for tabs).
        """
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        enabled = module not in self._app.module_registry.disabled_modules
        if not enabled:
            placeholder = QLabel(
                f"⚠️ {module.name} requires administrator privileges.\n\n"
                "Restart the application as Administrator to enable this module."
            )
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setWordWrap(True)
            page_layout.addWidget(placeholder)
            self._built.add(module.name)   # nothing more to build

        self._stack.addWidget(page)
        self._module_map[module.name] = module
        self._module_pages[module.name] = page

        self._sidebar.add_module(
            group=module.group, name=module.name,
            icon=getattr(module, "icon", ""), display=module.name,
            requires_admin=module.requires_admin,
        )

        if self._active_module is None and enabled:
            self._sidebar.select(module.name)
            self._active_module = module
            self._stack.setCurrentWidget(page)

    def _ensure_built(self, module: BaseModule) -> None:
        """Build the module's widget into its page, once."""
        if module.name in self._built:
            return
        self._built.add(module.name)
        try:
            widget = module.create_widget()
        except Exception:
            logger.exception("Module '%s' failed to build its widget", module.name)
            widget = QLabel(f"{module.name} failed to load — see the log for details.")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._module_pages[module.name].layout().addWidget(widget)
        self._module_widgets[module.name] = widget
```

Add `self._built: set[str] = set()` and `self._module_pages: Dict[str, QWidget] = {}` to `__init__`, and call `self._ensure_built(module)` at the top of `_on_module_selected` (before `on_activate`) and in `showEvent`'s first-show branch (before `on_activate`).

Keep `_module_widgets` populated — `_navigate_to_module` and the composite tab routing read it.

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_lazy_module_widgets.py tests/test_module_smoke.py -q`
Expected: PASS

Run the full suite: `QT_QPA_PLATFORM=offscreen python -m pytest` — expect `0 failed`.

- [ ] **Step 5: Measure the change**

Run the app from source and read the `[STARTUP]` lines: `python src/main.py`. Record the before (1.78s in widget construction) and after in the commit message.

- [ ] **Step 6: Commit**

```bash
git add src/ui/main_window.py tests/test_lazy_module_widgets.py
git commit -m "perf(ui): build module widgets on first selection, not at launch (audit #09)"
```

---

## Task 9: Find and cut the Tweaks build cost (audit #10) — RE-SCOPED after measurement

**Status: measured, then deliberately not done. The premise did not survive
the profiler.**

The audit reported `TweaksModule.create_widget()` at 1.28s, 72% of the
whole widget-build budget. That figure came from a probe that built all 33
module widgets in a loop; profiling `create_widget()` on its own gives
**0.30s**, and the 1.28s was dominated by one-time costs (PyQt enum class
creation, Qt style resolution) that the loop attributed to whichever module
ran first.

The profile, on this machine, after Task 8:

    create_widget total: 0.30s
      0.251s   20 x TweakTab.__init__            (tweaks_module.py:333)
      0.099s   5,031 addWidget calls
      0.093s   696 x TweakRow.__init__           (tweaks_module.py:232)
      0.068s   20 x setWidget
      0.046s   1,396 setStyleSheet calls
      0.005s   32 json.load calls

Two things follow.

**The plan's hypothesis was wrong.** It assumed the cost was parsing 20
definition files plus `debloat.json` at build time. Parsing is 0.005s —
1.7% of the total, and unmeasurable next to widget construction. Deferring
the JSON would have bought nothing.

**The remaining lever is not worth its risk.** The real cost is building
all 20 category tabs and their 696 rows eagerly. Deferring per-tab
construction would buy roughly 0.25s, but `self._tab_widgets` is read in
nine places — status detection sweeps, filtering, select-all, queued
changes — each of which would silently see only the tabs the user had
opened. A status sweep that covers only visited tabs is a behaviour change
the user would notice long before they noticed 0.25s.

**What the profile did surface** is that one Tweaks build makes 1,396
inline `setStyleSheet` calls — per-row styling that bypasses both theme
sheets. That is audit #27 (Task 25), it is a correctness problem rather
than only a speed one, and it is the better target in this file.

- [x] **Step 1: Measure before guessing** — done; profile above.
- [x] **Step 2: Decide from the measurement** — re-scoped; the work moves
      to Task 25, which now names `tweaks_module.py` as its first target.

---

## Task 10: Finish the light theme (audit #26)

`light.qss` is 184 lines against `dark.qss`'s 416. Anything styled only in the dark sheet falls back to the platform default on light — which is how a light theme ends up with dark-theme text on a white ground in isolated panes. The dark sheet is the specification; the light one has to answer every rule in it.

**Files:**
- Modify: `src/ui/styles/light.qss`
- Test: `tests/test_theme_light_coverage.py` (extend — the file already exists)

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_theme_light_coverage.py
"""Every selector the dark sheet styles, the light sheet styles too.

light.qss was 184 lines against dark.qss's 416. A selector present in only
one sheet is a widget that keeps the platform default in the other theme —
the mechanism behind dark text on a white pane.
"""
import re
from pathlib import Path

STYLES = Path(__file__).resolve().parent.parent / "src" / "ui" / "styles"


def _selectors(sheet: str) -> set[str]:
    text = (STYLES / sheet).read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return {
        part.strip()
        for block in re.findall(r"([^{}]+)\{", text)
        for part in block.split(",")
        if part.strip() and not part.strip().startswith("@")
    }


def test_the_light_sheet_answers_every_dark_selector():
    missing = sorted(_selectors("dark.qss") - _selectors("light.qss"))
    assert missing == [], (
        "these widgets keep the platform default on the light theme:\n  "
        + "\n  ".join(missing))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_theme_light_coverage.py -q`
Expected: FAIL, listing the selectors only `dark.qss` has.

- [ ] **Step 3: Write the missing rules**

For each selector the test names, add a light-theme rule. Derive colours from the light palette rather than inverting the dark values — `core/semantic_colors.py` already documents why an inverted `#4ec9b0` reads at 1.98:1 on a light pane. The light ground is `#f5f5f5` (`PANE_BACKGROUND["light"]`); keep every foreground at ≥4.5:1 against it, which `tests/test_semantic_colors.py` already computes for the semantic colours.

- [ ] **Step 4: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_theme_light_coverage.py tests/test_theme_manager.py tests/test_color_scheme.py -q`
Expected: PASS

- [ ] **Step 5: Look at it**

Run the app, switch to the light theme, and walk every sidebar group. A rule that satisfies the selector test can still be the wrong colour.

- [ ] **Step 6: Commit**

```bash
git add src/ui/styles/light.qss tests/test_theme_light_coverage.py
git commit -m "fix(ui): give the light theme a rule for every selector the dark one has (audit #26)"
```

---

## Task 11: Stop the hardcoded-colour count growing, then bring it down (audit #25)

`core/semantic_colors.py` exists for exactly this and its docstring names the failure mode: *"A pane that writes #4ec9b0 has picked a colour for the dark theme and frozen it. That reads 7.7:1 on the dark pane and 1.98:1 on the light one."* There are 400 such literals across 49 files. The module is right, its tests are right, adoption is the gap.

**Files:**
- Create: `tests/test_no_frozen_colours.py`
- Modify: the highest-count files, one commit's worth at a time
- Test: `tests/test_no_frozen_colours.py`

- [ ] **Step 1: Write the ratchet test**

```python
# tests/test_no_frozen_colours.py
"""A colour literal in Python code is a colour frozen to one theme.

core/semantic_colors.py exists to prevent this and states the arithmetic:
#4ec9b0 reads 7.7:1 on the dark pane and 1.98:1 on the light one. There
were 400 literals across 49 files when this test was written.

This is a RATCHET, not a gate. The budget only ever goes down; lower it in
the same commit that removes literals. Do not raise it.
"""
import re
import pathlib

SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")

# The palette module is where colour literals belong.
EXEMPT = {"core/semantic_colors.py"}

BUDGET = 400


def _literals():
    found = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel in EXEMPT:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for match in HEX.finditer(line):
                found.append(f"{rel}:{lineno} {match.group()}")
    return found


def test_the_frozen_colour_count_only_falls():
    literals = _literals()
    assert len(literals) <= BUDGET, (
        f"{len(literals)} colour literals, budget is {BUDGET}. "
        "Use core.semantic_colors.semantic('success'|'warning'|'error'|'info'|'match') "
        "or a .qss rule."
    )
```

- [ ] **Step 2: Run it — it passes at 400, which is the point**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_no_frozen_colours.py -q`
Expected: PASS. Commit this first, on its own: the ratchet's value is that it exists before the cleanup starts.

- [ ] **Step 3: Find the worst files**

Run:

```bash
grep -rno "#[0-9a-fA-F]\{6\}\b" src --include=*.py | cut -d: -f1 | sort | uniq -c | sort -rn | head -15
```

- [ ] **Step 4: Convert, file by file**

For a status colour, use the palette:

```python
# before
item.setForeground(QColor("#4ec9b0"))

# after
from core.semantic_colors import semantic
item.setForeground(QColor(semantic("success")))
```

For chrome (backgrounds, borders, panel colours) the answer is a `.qss` rule keyed on `objectName`, not a Python literal:

```python
banner.setObjectName("adminBanner")   # styled in dark.qss and light.qss
```

Lower `BUDGET` in the same commit, by exactly the number removed.

- [ ] **Step 5: Run the tests after each file**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_no_frozen_colours.py tests/test_semantic_colors.py tests/test_theme_light_coverage.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_no_frozen_colours.py
git commit -m "test: ratchet the frozen-colour count at 400 (audit #25)"
# then, per batch:
git add src tests/test_no_frozen_colours.py
git commit -m "refactor(ui): use the semantic palette in <area>, budget 400 -> NNN (audit #25)"
```

---

## Task 12: Break up `LogViewerWidget.__init__` (audit #20)

480 lines in one `__init__`; the class is 105 methods and 2,136 lines — the largest single unit in the codebase, and nothing about it can be tested in isolation. The module already has the right instinct: `cmtrace_parser.py` and `log_reader.py` are Qt-free and separately tested.

**Files:**
- Modify: `src/modules/log_viewer/log_viewer_module.py`
- Create: `src/modules/log_viewer/view_state.py`
- Test: `tests/test_log_viewer_construction.py`

**Interfaces:**
- Produces: `LogViewState` — a plain dataclass holding filter text, severity selection, follow flag, column visibility and the highlight rules; no Qt import. `LogViewerWidget.state: LogViewState`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_log_viewer_construction.py
"""The Log Viewer's construction is readable in pieces.

__init__ was 480 lines. The parser and reader beside it are Qt-free and
separately tested; the widget's own state should be too.
"""
import ast
import pathlib

MODULE = (pathlib.Path(__file__).resolve().parent.parent
          / "src" / "modules" / "log_viewer" / "log_viewer_module.py")


def _function_lengths():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return {
        node.name: node.end_lineno - node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }


def test_no_function_in_the_log_viewer_runs_past_eighty_lines():
    long = {name: n for name, n in _function_lengths().items() if n > 80}
    assert long == {}, f"still long: {long}"


def test_the_view_state_carries_no_qt():
    source = (MODULE.parent / "view_state.py").read_text(encoding="utf-8")
    assert "PyQt6" not in source, (
        "view_state.py must stay Qt-free, like cmtrace_parser and log_reader")


def test_the_state_round_trips():
    from modules.log_viewer.view_state import LogViewState
    state = LogViewState()
    state.filter_text = "error"
    state.following = True
    restored = LogViewState.from_dict(state.to_dict())
    assert restored.filter_text == "error"
    assert restored.following is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_log_viewer_construction.py -q`
Expected: FAIL — `__init__` at 480, `view_state.py` missing.

- [ ] **Step 3: Extract the state**

```python
# src/modules/log_viewer/view_state.py
"""What the Log Viewer is currently showing — with no Qt in it.

The same split cmtrace_parser.py and log_reader.py keep, and for the same
reason: this is the part worth testing without a display, and it was
buried inside a 480-line __init__.
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List


@dataclass
class LogViewState:
    filter_text: str = ""
    severities: List[str] = field(default_factory=lambda: ["Info", "Warning", "Error"])
    following: bool = False
    wrap: bool = False
    visible_columns: Dict[str, bool] = field(default_factory=dict)
    highlight_rules: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LogViewState":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
```

- [ ] **Step 4: Split the construction**

Break `__init__` into `_build_toolbar()`, `_build_table()`, `_build_detail_panel()`, `_build_status_bar()`, `_wire_signals()` and `_restore_state()`, each under 80 lines, called in that order from a short `__init__`. Move nothing else; this is a mechanical split, and the full suite is the proof it changed nothing.

- [ ] **Step 5: Run the tests**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/ -k "log_viewer or cmtrace or log_model" -q`
Expected: PASS

Full suite: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add src/modules/log_viewer tests/test_log_viewer_construction.py
git commit -m "refactor(log_viewer): split the 480-line __init__ and extract LogViewState (audit #20)"
```

---

## Task 13: Make the cleanup scanners a data table (audit #14) - PILOT SHIPPED

**Status: engine, tooling and a 41-scanner verified pilot shipped. The
remaining 480 are staged behind the verifier and deliberately not
converted.**

The census held up: of 538 `scan_*` functions, 430 were a plain path list
and 79 more differed only by a glob. `tools/convert_cleanup_scanners.py`
could mechanically convert **521 of 538**.

Then `tools/verify_scanner_conversion.py` ran each original and its
generated spec side by side against this machine and compared what each
found:

    agree (both found the same paths):    65
    agree (neither found anything here): 428
    DISAGREE:                             28

**28 of the 93 that could actually be checked disagreed - a 30% error
rate.** Some were harmless (a spec picking up a parent directory the
original filtered). One was not: `duplicate_files` originally offered four
specific duplicate installers, and the generated spec offered
`C:\Users\iorda\Documents`, `\Downloads` and `\Videos` - three entire user
folders, on a list with a delete button attached. `dmf_logs` produced paths
relative to the working directory.

The consequence is the important part: **"neither found anything on this
machine" is not evidence of equivalence.** With a 30% failure rate on
everything checkable, the 428 unchecked conversions cannot be trusted, and
shipping them would have meant shipping 428 unreviewed changes to a delete
button.

So what ships is the 41 scanners verified against real data present on this
machine - `temp_files` at 16.9 GB, `driver_store` at 6.6 GB, `event_logs`
across 248 paths - each also read by eye. That removed 778 lines from
`scanners_system.py`, and every hardcoded `C:\Windows` among them became
`%windir%` (audit #16, as a side effect).

Two things the data form made visible immediately, which 538 functions did
not: `user_crash_dumps` includes the whole of `%LOCALAPPDATA%\Temp`, and
`network_adapter_cache` points at the `hosts` file and calls itself "safe".
Both are faithful conversions of the originals - they are pre-existing, and
they are now legible.

- [x] **Step 1: engine** - `catalog.py`, with `ScannerSpec`,
      `load_catalog`, `run_spec` and `scanner_for` keeping the old
      `scan_x(min_age_days=0)` signature the tabs pass around.
- [x] **Step 2: extractor** - `tools/convert_cleanup_scanners.py`. Skips
      anything it cannot prove it understands rather than guessing.
- [x] **Step 3: verifier** - `tools/verify_scanner_conversion.py`. This is
      the real deliverable: it makes each batch checkable.
- [x] **Step 4: verified pilot** - 41 scanners, `definitions/system.json`.
- [ ] **Step 5: the remaining batches.** Run the verifier, take only what
      agrees *with real data present*, read each spec by eye, delete the
      originals. The apps/games/dev categories will need a machine with the
      relevant software installed - where Steam is absent, a Steam scanner
      cannot be verified at all.

---

# P2 — Medium impact

Each of these follows the same shape as P1: a failing test that states the rule, the smallest change that satisfies it, the full suite, one commit.

## Task 14: Report the real ShellExecuteEx failure code (audit #04)

**Files:** `src/modules/security_dashboard/security_module.py:434-472`; test `tests/test_elevated_batch_launch.py`

`ctypes.get_last_error()` reads ctypes' private copy, which is only populated when the library was created with `use_last_error=True`. `ctypes.windll.shell32` is not, so the logged number is zero or stale, and the commonest real cause — the user declining UAC — is indistinguishable from a genuine failure. `dashboard/procengine/actions.py:50-52` already does it correctly.

- [ ] Test: patching a fake `ShellExecuteExW` that fails with `ERROR_CANCELLED` (1223) makes `run_elevated_batch` log "cancelled" and return `None`, not an unknown-error code.
- [ ] Replace `ctypes.windll.shell32` with a module-level `_shell32 = ctypes.WinDLL("shell32", use_last_error=True)`, and read `ctypes.get_last_error()` from it.
- [ ] Distinguish `ERROR_CANCELLED` (1223) in the log message: declining a prompt is not an error.
- [ ] Commit: `fix(security): read the real error code from ShellExecuteExW (audit #04)`

## Task 15: Clean up the elevated-batch temp directory (audit #05)

**Files:** `src/modules/security_dashboard/security_module.py:448-472`; test `tests/test_elevated_batch_launch.py`

Every apply leaves a `tempfile.mkdtemp()` behind holding `batch.json` — the staged changes *including their previous values* — and `result.json`.

- [ ] Test: after `run_elevated_batch` returns, the folder it created no longer exists, on both the success and the declined-prompt paths.
- [ ] Wrap the body in `try/finally` with `shutil.rmtree(folder, ignore_errors=True)`. Read the result file inside the `try`, before the cleanup.
- [ ] Commit: `fix(security): remove the staged-batch temp directory after applying (audit #05)`

## Task 16: EventBus dispatches over a copy (audit #06)

**Files:** `src/core/event_bus.py`; test `tests/test_event_bus.py`

- [ ] Test: a subscriber that calls `unsubscribe` on itself during `publish` does not cause a later subscriber to be skipped.
- [ ] Test: a subscriber that calls `subscribe` during `publish` is not invoked for the event already in flight.
- [ ] `for callback in list(self._subscribers.get(event_type, ())):`, and take a `threading.RLock` around subscribe/unsubscribe/publish — `publish` is reachable from worker threads, and only `publish_async` marshals to the GUI thread.
- [ ] Commit: `fix(core): dispatch events over a snapshot of the subscriber list (audit #06)`

## Task 17: Qt event overrides chain to super() (audit #07)

**Files:** `src/ui/main_window.py:264,271,511`; `src/modules/log_viewer/log_viewer_module.py:733,741`; `src/modules/treesize/ui/views/chart.py:135,147,152,308`; `src/modules/treesize/ui/panels.py:173`; test `tests/test_event_handlers_chain.py`

- [ ] Test: an AST pass over `src/` asserting that every override of a non-paint Qt event handler contains a `super()` call. `paintEvent` is exempt and the test says why — a custom-painted widget deliberately does not chain.
- [ ] Add the `super().<handler>(event)` call to each of the nine.
- [ ] Commit: `fix(ui): chain Qt event handlers to super() (audit #07)`

## Task 18: Auto-refresh off the GUI thread (audit #11)

**Files:** `src/ui/main_window.py:245-262`; `src/core/base_module.py`; test `tests/test_auto_refresh_threading.py`

`_tick` calls `refresh_data()` synchronously, so any module whose refresh reaches WMI, the registry or a subprocess freezes the UI for that duration, once per interval, forever.

- [ ] Test: a module whose `refresh_data` blocks for 200ms does not block the Qt event loop — measured by a `QTimer` that must still fire during it.
- [ ] Add `BaseModule.refresh_is_blocking: bool = False`. When a module sets it, `_tick` runs `refresh_data` on a `Worker` and marshals the result back through its `result` signal; otherwise it stays synchronous. Set it on the modules that reach the machine: Dashboard, Services, Startup, Disk Health, Network Diagnostics.
- [ ] Commit: `perf(ui): run blocking module refreshes on a worker (audit #11)`

## Task 19: A shared cache for machine facts (audit #12) - NOT DONE, measured

**Status: the premise does not survive measurement. No cache built.**

Audit #12 inferred repeated uncached reads from a proxy - two `lru_cache`
uses in 92,078 lines, against 23 files importing `winreg` and 19 touching
WMI. Two measurements say the inference is wrong.

**The OS facts are read in exactly one place.** `CurrentBuildNumber`,
`EditionID` and the rest appear only in `modules/tweaks/os_context.py`.
`platform.machine()` appears in three files and `sys.getwindowsversion()`
in two, both of which are microseconds. The 23 `winreg` importers read
their OWN keys - the registry explorer reads what the user navigated to,
the startup reader reads Run keys - not the same keys as each other.

**The redundancy that does exist is cheap.** Instrumenting `winreg.OpenKey`
across a 280-tweak detection sweep:

    detected 280 tweaks in 1.2s
    distinct registry keys opened:  53
    total OpenKey calls:           181
    redundant opens:               128   (71%)
    most re-opened: SOFTWARE\Policies\Microsoft\Edge, 49 times

71% redundant looks alarming and is worth almost nothing: 181 opens inside
1.2s. CLAUDE.md already records where that sweep's time actually goes -
process launches (schtasks, powercfg, PowerShell), which is why
`detect_many` parallelises them and took the 696-tweak sweep from ~17s to
~6s. A registry cache would save a few milliseconds of the six seconds.

The one caching that WAS worth doing is already done and already
documented: `security_reader._wmi_namespace` caches WMI namespace denials,
because being refused costs a fixed ~5s per namespace. That took Device &
Boot from 16.79s to 1.26s. It is the counter-example that shows the
codebase caches where caching pays.

- [x] **Step 1: measure before building** - done, above.
- [x] **Step 2: decide** - no cache. `os_context.py` stays where it is;
      moving 398 lines to `core/` would be churn with no user-visible
      effect, and nothing outside `tweaks/` currently wants it.

---

## Task 20: No hardcoded drive letters (audit #16)

**Files:** 31 files, led by `src/modules/cleanup/cleanup_scanner/scanners_system.py:23,56,66,89,138,147` and `src/modules/cbs_log/cbs_module.py:18`; test `tests/test_no_hardcoded_drive.py`

136 hardcoded `C:\` paths against 141 sites that correctly read `%windir%` — sometimes in the same file.

- [ ] Test: a ratchet like Task 11's, counting `C:\` literals in `src/**/*.py` outside test fixtures, budget starting at the measured count and only falling.
- [ ] Replace with `os.environ.get("windir", ...)` / `os.path.expandvars("%windir%\\...")`. Task 13's catalog already removes the largest cluster; this task covers the rest.
- [ ] Commit: `fix: read the Windows directory from the environment, not C:\ (audit #16)`

## Task 21: One ConfigManager (audit #17)

**Files:** `src/modules/config/config_manager.py`; its callers; test `tests/test_config_manager.py`

`core/config_manager.py` is the real one — versioned, migratable, autosaving, event-bus aware. `modules/config/config_manager.py` is an unrelated class of the same name mixing JSON persistence, `QSettings` and Qt widget imports, and is the only `QSettings` user in the tree.

- [ ] Test: `grep`-style assertion that `QSettings` appears nowhere in `src/`.
- [ ] Move the cleanup-rule/preset persistence onto `app.config` under a `cleanup.*` key namespace, with a migration registered via `ConfigManager.register_migration` that reads any existing `QSettings` values once and writes them across.
- [ ] Delete `modules/config/config_manager.py`; update its callers.
- [ ] Commit: `refactor(config): one persistence mechanism (audit #17)`

## Task 22: Shorten the twenty longest functions (audit #21)

**Files:** `src/modules/scheduled_tasks/tasks_module.py:66` (278 lines), `src/modules/windows_features/features_module.py:111` (225), `src/modules/power_boot/power_module.py:179` (208), `src/modules/network_diagnostics/network_module.py:288` (175), `src/modules/software_inventory/software_module.py:120` (141), `src/modules/firewall_rules/firewall_manager_module.py:453` (141); test `tests/test_function_lengths.py`

- [ ] Test: an AST ratchet — no function in `src/` over 120 lines, budget lowered as each is split. Start the budget at the current maximum outside `log_viewer` (Task 12 handles that one).
- [ ] Split each `create_widget` into `_build_<area>` helpers, mechanically. The full suite is the proof nothing changed.
- [ ] Commit one module per commit: `refactor(<module>): split create_widget (audit #21)`

## Task 23: Split `security_reader.py` (audit #22)

**Files:** `src/modules/security_dashboard/security_reader.py` (4,084 lines / 210 KB) → `readers/<category>.py`; test `tests/test_security_reader_*.py` (existing)

The `catalog/` package beside it is already split by category; the readers should follow the same seams.

- [ ] Test: each new `readers/<category>.py` is under 600 lines, and `security_reader` still re-exports every name the catalog binds so no `reader=` reference breaks.
- [ ] Move readers by category — defender, device_boot, network, account, app_browser, audit, update — keeping `security_reader.py` as the façade that re-exports them.
- [ ] Run `tools/security_refusal_sweep.py` **unelevated** afterwards: it asks all 149 controls whether any answers with a value after being refused. Expect zero.
- [ ] Commit: `refactor(security): split the readers by category (audit #22)`

## Task 24: Break the two module import cycles (audit #23)

**Files:** `src/modules/process_explorer/` ↔ `src/modules/dashboard/`; `src/modules/ui/` ↔ `src/modules/cleanup/`; test `tests/test_no_module_cycles.py`

`process_explorer` imports `dashboard` 15 times and back 3; `modules/ui` imports `cleanup` 13 times and back once.

- [ ] Test: build the import graph over `src/modules/` with AST and assert it is acyclic. The test prints the cycle it found.
- [ ] Move `dashboard/procengine/` — which both modules use — to `src/core/procengine/`. It is engine code with no Qt dependency and belongs to neither pane.
- [ ] Move the shared cleanup tab widgets out of `modules/ui` per Task 33.
- [ ] Commit: `refactor: break the process_explorer/dashboard and ui/cleanup import cycles (audit #23)`

## Task 25: Theme-aware chrome instead of inline stylesheets (audit #27)

**Files:** `src/ui/main_window.py:146-148` and the other 203 sites; test `tests/test_no_inline_stylesheets.py`

Per-widget stylesheets override the theme and cannot follow a theme change at runtime — which is what makes Task 10 hard to finish.

- [ ] Test: a ratchet on `setStyleSheet` call count, starting at 204.
- [ ] Convert each to an `objectName` plus a rule in both `.qss` sheets. Start with `_create_admin_banner`, which hardcodes `background-color: #805500` and `color: white`.
- [ ] Commit: `refactor(ui): style chrome from the sheets, budget 204 -> NNN (audit #27)`

## Task 26: Remember the window's geometry (audit #28)

**Files:** `src/ui/main_window.py:141-143,529-530`; test `tests/test_window_geometry.py`

Only `[width, height]` is saved, so maximise-quit-reopen comes back windowed in the middle of the primary display.

- [ ] Test: `saveGeometry`/`restoreGeometry` round-trip through config, and a maximised window reopens maximised.
- [ ] Store `bytes(self.saveGeometry().toBase64()).decode()` under `app.window_geometry`; keep reading the old `app.window_size` as a fallback so an existing config still works.
- [ ] Guard against a geometry that lands off-screen when a monitor is gone: if `restoreGeometry` leaves the frame outside every `QScreen`'s available area, fall back to the default size centred on the primary screen.
- [ ] Commit: `feat(ui): remember window geometry and maximised state (audit #28)`

## Task 27: Keyboard and screen-reader access (audit #29)

**Files:** `src/ui/main_window.py`, `src/ui/sidebar_nav.py`, `src/ui/search_bar.py`, the table-owning modules; test `tests/test_shortcuts_and_labels.py`

Three `setShortcut` calls in 92,078 lines; zero `setAccessibleName`, so a screen reader reads tables of unlabelled cells.

- [ ] Test: the main window registers Ctrl+R (refresh), Ctrl+F (search bar), Ctrl+1…9 (sidebar groups) and Escape (clear filter), and no two shortcuts collide.
- [ ] Test: every `QTableWidget`/`QTableView` reachable from a built module has a non-empty `accessibleName`.
- [ ] Add the shortcuts in `_setup_shortcuts`; add `setAccessibleName`/`setAccessibleDescription` on tables and on the icon-only toolbar buttons.
- [ ] Commit: `feat(ui): keyboard shortcuts and accessible names (audit #29)`

## Task 28: No silently swallowed exceptions (audit #35)

**Files:** 49 sites, led by `src/modules/startup_manager/startup_reader.py:43,66,127,185,250,291`; test `tests/test_no_silent_swallow.py`

CLAUDE.md forbids this in as many words. The heaviest concentration is in `startup_reader.py`, where a swallowed registry error means a startup entry the user never learns about.

- [ ] Test: an AST pass finding every `ExceptHandler` whose entire body is `pass`/`continue`/`break`, asserting the list is empty.
- [ ] Add a `logger.debug`/`logger.warning` line to each, naming what was being read. `debug` is right for a genuinely expected miss (a registry key that is normally absent); `warning` for anything else.
- [ ] Where the swallow hides a *refusal*, make the caller able to tell — `None` for "could not look", per the global constraint.
- [ ] Commit: `fix: log every swallowed exception (audit #35)`

## Task 29: Smoke-test the seventeen untested modules (audit #36)

**Files:** create `tests/test_module_smoke_all.py`; the 17 named packages

Never imported by any test: about, boot_analyzer, config, debloat, diagnose, driver_manager, env_vars, hosts_editor, local_users, network_diagnostics, power_boot, quick_fix, registry_explorer, remote_tools, scheduled_tasks, shared_resources, software_inventory. Several write to the machine.

- [ ] Test: parameterised over every module class registered in `main.register_all_modules` — each imports, instantiates, reports `name`/`icon`/`group`, and builds its widget without raising. Follow the collection-time caveat in CLAUDE.md: build the real `App` in a fixture, never at module level.
- [ ] Test: for the four that perform destructive actions unelevated — Quick Fix, Registry Explorer, Local Users, Shared Resources — that the destructive entry points call `require_admin()` before doing anything. `tools/admin_requirement_audit.py` already asks this question of the real tree; make it a test.
- [ ] Commit: `test: smoke coverage for the seventeen untested modules (audit #36)`

## Task 30: Coverage, and a parallel suite (audit #37)

**Files:** `pyproject.toml`, `requirements.txt`, `.github/workflows/ci.yml`

- [ ] Add `pytest-cov` to the dev extra and `--cov=src --cov-report=term-missing:skip-covered` to a `coverage` CI step (not to the default `addopts` — it slows every local run).
- [ ] Add `-n auto` via `pytest-xdist` to the CI test step. Verify locally first: the `qapp` session fixture and the catalog-restoring autouse fixture in `conftest.py` must both survive being run in parallel workers.
- [ ] Record the resulting wall clock in the commit message (3m46s serial before).
- [ ] Commit: `ci: measure coverage and run the suite in parallel (audit #37)`

## Task 31: One version number (audit #38)

**Files:** `src/_version.py`, `version_info.txt`, `pyinstaller_common.py`, `src/core/logging_service.py:11`; test `tests/test_version_is_single_sourced.py`

`_version.py` calls itself the single source of truth and is read by one file — the About pane. `version_info.txt` carries a hand-maintained `1,0,0,0`. `logging_service.py` carries a stray `__version__ = "0.1.0"` that means nothing.

- [ ] Test: the `filevers`/`prodvers`/`FileVersion`/`ProductVersion` in the generated `version_info.txt` all equal `_version.__version__`, and no other module in `src/` defines `__version__`.
- [ ] Generate `version_info.txt` from `_version.py` in `pyinstaller_common.py` at build time, from a `version_info.txt.in` template.
- [ ] Delete the stray in `logging_service.py`.
- [ ] Commit: `build: derive the exe version from _version.py (audit #38)`

---

# P3 — Low impact

## Task 32: UTF-8 console logging (audit #08)

**Files:** `src/core/logging_service.py:120-127`; test `tests/test_logging_service.py`

Running from source on a default Windows console, every em-dash in a log line comes out as `?` — observed: *"Module 'Tweaks' requires admin ? disabled"*. `main.py:20-23`'s `_s()` already works around it for its own prints.

- [ ] Test: a `StreamHandler` built by `LoggingService` over a cp1252 stream emits a non-ASCII message without raising and without mangling it into `?`.
- [ ] Call `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` when the stream supports it, guarded — `sys.stdout` is `None` in onefile windowed mode.
- [ ] Commit: `fix(core): log to the console in UTF-8 (audit #08)`

## Task 33: Move `src/modules/ui/` out of the plugin namespace (audit #24)

**Files:** `src/modules/ui/components/*` → `src/ui/components/*`; every importer

It sits in the plugin namespace, registers nothing, and holds shared widgets — including the 1,190-line `quick_cleanup_tab.py` that `cleanup` depends on.

- [ ] Test: `src/modules/` contains only real module packages — every subdirectory has a `*_module.py` defining a `BaseModule` subclass.
- [ ] Move the package; update the imports; add the new paths to `HIDDEN_IMPORTS` in `pyinstaller_common.py` if any are imported lazily.
- [ ] Commit: `refactor(ui): move shared components out of the plugin namespace (audit #24)`

## Task 34: One byte formatter (audit #18)

**Files:** `src/modules/treesize/ui/formatting.py` (keep), `cleanup_scanner/_common.py:39`, `store_apps_module.py:152`, `updates/report_generator.py:21`, `updates/stage_runners.py:21` (delete); test `tests/test_formatting.py`

They do not all round the same way, so the same folder can read differently in two panes.

- [ ] Test: the same byte count formats identically wherever it is displayed.
- [ ] Move `format_bytes` to `src/core/formatting.py` (it must not stay under `treesize/ui`, which is a Qt package the non-Qt callers should not import), re-export from its old home, delete the four duplicates.
- [ ] Commit: `refactor: one byte formatter (audit #18)`

## Task 35: Explicit exports from `cleanup_scanner` (audit #19)

**Files:** `src/modules/cleanup/cleanup_scanner/__init__.py:5-13`; test `tests/test_cleanup_catalog.py`

Nine star-imports: nothing can tell you what the package exports without importing it, two scanners with the same name silently shadow each other, and no linter can find a dead one.

- [ ] Test: `cleanup_scanner.__all__` is non-empty and every name in it resolves.
- [ ] Replace the star-imports with an explicit `__all__`. Task 13 removes most of the need; this closes what remains. Then drop the `F403`/`F405` entries from `pyproject.toml`'s ruff `ignore`.
- [ ] Commit: `refactor(cleanup): explicit exports instead of star-imports (audit #19)`

## Task 36: Shutdown on `aboutToQuit` (audit #13)

**Files:** `src/main.py`, `src/app.py`; test `tests/test_shutdown_paths.py`

`App.shutdown()` runs only from `MainWindow.closeEvent`, so a session logoff or any `qApp.quit()` path skips config save and the thread-pool drain.

- [ ] Test: `shutdown()` is idempotent, and emitting `aboutToQuit` runs it exactly once even when `closeEvent` already did.
- [ ] Add an `_shut_down` guard to `App.shutdown()`; connect `qt_app.aboutToQuit` to it in `main()`.
- [ ] Commit: `fix(core): run shutdown on aboutToQuit as well as window close (audit #13)`

## Task 37: `print()` out of `src/` (audit #39)

**Files:** `cleanup/trash/__init__.py:76,111,134,160`, `modules/config/config_manager.py:94,277`, `core/logging_service.py:117,128`, `core/update_checker.py:8`; test `tests/test_no_prints.py`

In a windowed PyInstaller build `sys.stdout` is `None` — CLAUDE.md says so — so these write nowhere and the error is lost.

- [ ] Test: an AST pass finding `print()` in `src/`, exempting `main.py`'s `_s()` (which deliberately prints before logging exists and handles the encoding failure) and `unattended_runner.py` (headless, stderr is its only channel).
- [ ] Replace each with `logger.warning(..., exc_info=True)`. The trash module's four are failed move, failed restore, failed delete and unreadable item — exactly the failures worth having in the log.
- [ ] Commit: `fix: log instead of printing (audit #39)`

## Task 38: `.gitattributes` (audit #40)

**Files:** create `.gitattributes`

Every `git diff` prints a wall of *"LF will be replaced by CRLF"*, which trains you to stop reading git's output.

- [ ] Create:

```gitattributes
* text=auto
*.py    text eol=lf
*.qss   text eol=lf
*.json  text eol=lf
*.md    text eol=lf
*.ps1   text eol=crlf
*.bat   text eol=crlf
*.spec  text eol=lf
```

- [ ] Run `git add --renormalize .` and commit the normalisation separately from the `.gitattributes` file, so the renormalisation commit can be skipped with `git blame --ignore-rev`.
- [ ] Commit: `chore: normalise line endings (audit #40)`

## Task 39: Decide about translation (audit #30)

**Files:** `CLAUDE.md`

Zero `self.tr()` calls; every string is baked in English. This is a legitimate scope decision for a personal tool — but worth making deliberately, because retrofitting across 378 files later is far larger than wrapping strings as new panes are written.

- [ ] Decide, and record the decision in CLAUDE.md under "Important Gotchas" either way. If the answer is "English only", say so explicitly so nobody half-starts it. If the answer is "eventually", add the `tr()` requirement to the module-authoring section so new panes are born translatable.
- [ ] Commit: `docs: record the i18n decision (audit #30)`

---

## Self-review

**Spec coverage.** All forty audit items map to a task: P1 items 01, 02, 03, 09, 10, 14, 15, 20, 25, 26, 31, 32, 33, 34 → Tasks 1–13 (Task 2 closes both #31 and #34). P2 items 04, 05, 06, 07, 11, 12, 16, 17, 21, 22, 23, 27, 28, 29, 35, 36, 37, 38 → Tasks 14–31. P3 items 08, 13, 18, 19, 24, 30, 39, 40 → Tasks 32–39.

**Ordering.** Tooling (1–3) precedes everything, so every later task runs the same lint and the same test command and can see its own verdict. `core/run.py` (6) precedes the timeout sweep (7) that consumes it. Lazy widgets (8) precedes the Tweaks profiling (9), because the fix changes when that cost is paid. The light-theme sheet (10) precedes the colour-literal migration (11), because a converted literal needs a light rule to land in. The two largest refactors (12, 13) are last in P1.

**Interface consistency.** `core.run.run`/`run_ps` — defined Task 6, consumed Tasks 7, 14. `ScannerSpec`/`load_catalog`/`run_spec`/`scanner_for` — defined Task 13, consumed Task 35. `LogViewState` — Task 12. `machine_facts.*` returning `Optional[bool]` — Task 19, matching the `service_exists` convention already in `tweak_engine.py`. Markers `slow`/`real_machine`/`needs_admin` — registered Task 2, applied Tasks 3, 9, 29.

**Ratchets, not gates.** Tasks 11, 20, 22 and 25 introduce budget tests over counts that are too large to fix in one commit. Each one's budget only ever falls, in the same commit that removes instances.
