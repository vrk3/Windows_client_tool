# Security Dashboard Actionable Controls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Security Dashboard from a pane that can see 171 things and change 24 into one that can change everything Windows permits, through a declarative catalog, with staged batches, verified writes and real revert.

**Architecture:** One `SecurityControl` entry per control binds an existing `check_*` reader to `TweakEngine` writer steps plus risk metadata. Tabs, search, baselines, profiles and the Overview verdict all become filters and aggregates over that single table. Writes stage into a `ChangeSet`, apply as one elevated batch through `TweakEngine`/`BackupService`, and are verified by re-reading.

**Tech Stack:** Python 3.12, PyQt6, `winreg`, `win32service`, PowerShell via `subprocess`, SQLite (through the existing `BackupService`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-security-dashboard-controls-design.md`

## Global Constraints

- **Branch:** `feat/security-dashboard-controls`, already created off `master` at `d57cdf2`. Do not commit to `master`.
- **Python entry point for every command:** `.\.venv\Scripts\python.exe` — PowerShell refuses a relative executable without the `.\` prefix.
- **Never write Python containing backslashes through a shell heredoc.** Use the Write tool. A quoted heredoc turns `\\` into `\`, which still runs and surfaces only as `SyntaxWarning: invalid escape sequence` on a cold compile. Registry paths guarantee backslashes.
- **Clear `__pycache__` before counting warnings.** Baseline is **1 warning** (a pre-existing `PytestCollectionWarning` in `tests/test_integration.py`), not 0.
- **Suite baseline at branch point: `2035 passed, 4 skipped, 1 warning`, pytest exit 0.** Every task ends green against that floor, with the count only going up.
- **Never treat a return code as a success signal for a Windows admin cmdlet.** `netsh` and `dism` write their real complaint to **stdout**; `Get-BitLockerVolume` writes it to stderr with empty stdout; `Get-Tpm` answers `TpmPresent: null` and exits 0. Read the payload.
- **A refused read is never reported as an absent value.** Carry an explicit availability flag; never infer it from an empty result.
- Qt: `QHeaderView.ResizeMode.Fixed` silently refuses a user's drag — use `Interactive`. Use `ElideMiddle` for paths.
- Only `security_module.py` may import Qt. `catalog/`, `staging.py`, `applier.py`, `profile.py`, `elevated_helper.py` stay Qt-free and testable without a `QApplication`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/modules/security_dashboard/catalog/model.py` | `SecurityControl`, `Risk`, `Category`, `ControlState`, `ApplyOutcome` |
| `src/modules/security_dashboard/catalog/__init__.py` | `load_catalog()`, `NOT_A_CONTROL` |
| `src/modules/security_dashboard/catalog/defender.py` | Defender controls |
| `src/modules/security_dashboard/catalog/firewall_network.py` | Firewall + network hardening |
| `src/modules/security_dashboard/catalog/accounts.py` | Accounts, credentials, logon |
| `src/modules/security_dashboard/catalog/device_boot.py` | TPM, Secure Boot, BitLocker, VBS |
| `src/modules/security_dashboard/catalog/services.py` | Service startup controls |
| `src/modules/security_dashboard/catalog/features.py` | Windows optional features |
| `src/modules/security_dashboard/catalog/exploit_cve.py` | Exploit protection + CVE mitigations |
| `src/modules/security_dashboard/catalog/baselines/*.json` | `{control_id: desired}` maps |
| `src/modules/security_dashboard/snapshots.py` | Cached `Get-MpPreference` / `Get-MpComputerStatus` / `Get-Service` / feature snapshots |
| `src/modules/security_dashboard/staging.py` | `PendingChange`, `ChangeSet`, baseline/profile diffing |
| `src/modules/security_dashboard/applier.py` | Batch execution, verify-after-write, result model |
| `src/modules/security_dashboard/elevated_helper.py` | `--apply-security-batch` entry point |
| `src/modules/security_dashboard/profile.py` | Export/import + diff against live readings |
| `src/modules/security_dashboard/security_reader.py` | Existing readers; duplicates resolved, snapshot-backed |
| `src/modules/security_dashboard/security_module.py` | The pane; renders from the catalog, wires nothing by hand |
| `tools/security_catalog_check.py` | Real-machine harness (Task 18) |

---

# Phase 1 — Make the foundations honest

Nothing in Phase 2 onward is trustworthy until these three land. Task 1 fixes an answer decided by file order; Task 2 makes a failed write visible; Task 3 stops a 155-control read from taking a minute.

---

### Task 1: One definition per name, across all of `src/`

`security_reader.py` binds ten function names twice. The second shadows the first, and the two implementations disagree because they sit on helpers with opposite polarity. There is already a test for this shape, but it covers `src/modules/treesize/ui/` only and only checks **class methods**, so it cannot see a module-level function defined twice.

**Files:**
- Create: `tests/test_no_duplicate_definitions.py`
- Modify: `src/modules/security_dashboard/security_reader.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a single live definition for each of `check_service_dnscache`, `check_service_dhcp`, `check_service_wsearch`, `check_service_sysmain`, `check_service_fax`, `check_service_xbox_live`, `check_service_wpn`, `check_service_fdphost`, `check_service_webclient`, `check_fast_startup`. Every later task's catalog binds to these names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_no_duplicate_definitions.py`:

```python
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
```

- [ ] **Step 2: Run it and confirm it fails with exactly the ten known names**

```
.\.venv\Scripts\python.exe -m pytest tests/test_no_duplicate_definitions.py -v
```

Expected: FAIL listing 10 entries, all in `modules/security_dashboard/security_reader.py`: `check_service_dnscache` (2632), `check_service_dhcp` (2633), `check_service_wsearch` (2634), `check_service_sysmain` (2635), `check_service_fax` (2636), `check_service_xbox_live` (2637), `check_service_wpn` (2639), `check_service_fdphost` (2641), `check_service_webclient` (2642), `check_fast_startup` (2742).

If a name appears that is **not** in that list, stop and report it — it is a defect nobody has seen yet.

- [ ] **Step 3: Decide the correct semantics per service, then delete the loser**

Do not simply keep the second one because it currently wins. For each pair, read both and decide which polarity is right, then delete the other:

| Service | Correct expectation | Keep |
|---|---|---|
| `Dnscache` (DNS Client) | should be **running** — breaking it breaks name resolution | the `good_running=False`… variant that treats *running* as good |
| `Dhcp` (DHCP Client) | should be **running** | same |
| `WSearch` (Windows Search) | optional; running is not a security problem | the variant that treats it as optional, not "bad" |
| `SysMain` | optional | as above |
| `Fax` | should be **stopped** | the `running_bad=True` variant |
| `XboxNetApiSvc` | should be **stopped** | `running_bad=True` |
| `WpnService` | push notifications; **stopped** is the hardened state | `running_bad=True` |
| `fdPHost` | function discovery; **stopped** on an untrusted network | `running_bad=True` |
| `WebClient` (WebDAV) | should be **stopped** — WebDAV is a known lateral-movement path | `running_bad=True` |
| `check_fast_startup` | read both; keep the one that reports the `HiberbootEnabled` value honestly when the value is absent | see Step 4 |

Write a one-line comment above each survivor saying why that polarity is the correct one. `Dnscache` and `Dhcp` are the two where the *currently live* definition is wrong: `_svc_check(running_bad=False)` at 2632-2633 is correct, and `_check_service(good_running=True)` at 2192-2195 is also correct — verify they agree before deleting either, and if they disagree, keep the one matching the table.

- [ ] **Step 4: Resolve `check_fast_startup`**

Read both definitions (2441 and 2742). The correct one returns "Not Configured" — not "Enabled" and not "Disabled" — when `HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Power\HiberbootEnabled` is absent, because an absent value means the default, and the default differs by build. If neither does that, keep one and fix it to.

- [ ] **Step 5: Run the new test and the full suite**

```
.\.venv\Scripts\python.exe -m pytest tests/test_no_duplicate_definitions.py -v
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the new test PASSES; suite `2036 passed, 4 skipped, 1 warning`.

- [ ] **Step 6: Commit**

```bash
git add tests/test_no_duplicate_definitions.py src/modules/security_dashboard/security_reader.py
git commit -m "fix(security): ten checks were defined twice and file order picked the answer"
```

---

### Task 2: A command step that failed must be able to say so

`TweakEngine._apply_command` and `_apply_script` run with `check=False, capture_output=True` and then read neither the return code nor the output. Every command-shaped write is recorded as applied whether Windows did it or not.

**Files:**
- Modify: `src/core/backup_service.py` (the `StepRecord` dataclass, ~line 18)
- Modify: `src/modules/tweaks/tweak_engine.py:334-349`
- Test: `tests/test_tweak_engine_command_capture.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `StepRecord.rc: Optional[int]`, `StepRecord.stdout: str`, `StepRecord.stderr: str`, all defaulting so existing construction sites are untouched. `applier.py` (Task 11) reads these to build a refusal reason.

- [ ] **Step 1: Write the failing test**

Create `tests/test_tweak_engine_command_capture.py`:

```python
"""A command step that failed must be able to say so.

_apply_command and _apply_script ran with check=False, capture_output=True and
then read neither the return code nor the output, building a StepRecord either
way. Windows admin commands exit 0 while refusing and write the reason to
stdout -- netsh and dism both do -- so "applied" meant "we ran something".
"""
import pytest

from core.backup_service import StepRecord
from modules.tweaks.tweak_engine import TweakEngine


class _FakeBackup:
    def record_steps(self, *a, **k): pass
    def backup_registry_key(self, *a, **k): pass


@pytest.fixture
def engine():
    return TweakEngine(_FakeBackup())


def test_a_failing_command_records_its_return_code_and_output(engine):
    record = engine._apply_command(
        {"type": "command", "cmd": "cmd /c echo refused by policy& exit /b 5"})
    assert record.rc == 5
    assert "refused by policy" in record.stdout


def test_a_command_that_exits_zero_while_complaining_keeps_its_stdout(engine):
    """netsh and dism both do exactly this."""
    record = engine._apply_command(
        {"type": "command", "cmd": "cmd /c echo No rules match the specified criteria."})
    assert record.rc == 0
    assert "No rules match" in record.stdout


def test_a_script_step_records_stderr_too(engine):
    record = engine._apply_script(
        {"type": "script", "command": "cmd /c echo boom 1>&2& exit /b 1"})
    assert record.rc == 1
    assert "boom" in record.stderr
```

- [ ] **Step 2: Run it to verify it fails**

```
.\.venv\Scripts\python.exe -m pytest tests/test_tweak_engine_command_capture.py -v
```

Expected: FAIL — `AttributeError: 'StepRecord' object has no attribute 'rc'`.

- [ ] **Step 3: Add the fields to `StepRecord`**

In `src/core/backup_service.py`, extend the dataclass. New fields go **last** with defaults so every existing positional construction still works:

```python
@dataclass
class StepRecord:
    step_type: str   # registry | service | appx | command | script | file | scheduled_task
    target: str
    before_value: Any
    after_value: Any
    revert_command: Optional[str] = None
    value_name: str = ""        # registry only — the value name under `target` (the key path)
    reg_kind: Optional[int] = None  # registry only — winreg.REG_* type, needed to write before_value back
    rc: Optional[int] = None    # command/script only — the process exit code
    stdout: str = ""            # command/script only — netsh and dism put refusals HERE, not on stderr
    stderr: str = ""            # command/script only
```

- [ ] **Step 4: Capture in both apply methods**

Replace `_apply_command` and `_apply_script` in `src/modules/tweaks/tweak_engine.py`:

```python
    def _apply_command(self, step: Dict) -> StepRecord:
        cmd = step["cmd"]
        proc = subprocess.run(
            cmd, shell=True, check=False, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return StepRecord("command", cmd, None, None,
                          rc=proc.returncode,
                          stdout=(proc.stdout or "").strip(),
                          stderr=(proc.stderr or "").strip())

    def _apply_script(self, step: Dict) -> StepRecord:
        cmd = step.get("command", step.get("cmd", ""))
        proc = subprocess.run(
            cmd, shell=True, check=False, capture_output=True, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        revert_cmd = step.get("revert_command")
        return StepRecord("script", cmd, None, None, revert_command=revert_cmd,
                          rc=proc.returncode,
                          stdout=(proc.stdout or "").strip(),
                          stderr=(proc.stderr or "").strip())
```

Note `text=True` — without it `stdout` is `bytes` and every `in` check against a `str` raises.

- [ ] **Step 5: Persist the new fields**

`BackupService.record_steps` writes `StepRecord`s to SQLite. Add `rc`, `stdout`, `stderr` columns to the `tweak_steps` table in `_create_tables`, and include them in the INSERT in `record_steps`. Use `ALTER TABLE ... ADD COLUMN` guarded by a `PRAGMA table_info` check so an existing `perfmon.db`/backup DB on a user's machine migrates instead of breaking:

```python
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(tweak_steps)")}
        for name in ("rc", "stdout", "stderr"):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE tweak_steps ADD COLUMN {name} TEXT")
```

- [ ] **Step 6: Run tests**

```
.\.venv\Scripts\python.exe -m pytest tests/test_tweak_engine_command_capture.py tests/test_backup_service.py -v
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: new tests PASS; `test_backup_service.py` still passes (migration is additive); suite green.

- [ ] **Step 7: Commit**

```bash
git add src/core/backup_service.py src/modules/tweaks/tweak_engine.py tests/test_tweak_engine_command_capture.py
git commit -m "fix(tweaks): a command step recorded itself as applied without reading rc or output"
```

---

### Task 3: Stop paying 0.54s per PowerShell field read

Measured on this machine at branch point: one `_ps()` call costs **0.54 s**, and **57 of the 171 readers use it**. Worse, they are redundant — **19 separate call sites each run `Get-MpPreference`** to pull one field from a cmdlet that returns all of them, plus 7 × `Get-MpComputerStatus`, 6 × `Get-Service`, 4 × `Get-WindowsOptionalFeature`. Reading 155 controls this way is a 40–60 second tab: the Overview 37.3 s defect, at ten times the scale.

`_reg_read` is the same shape more cheaply — it shells out to `reg query` at **21.1 ms** where `winreg` reads the same value in **0.015 ms** (1383×).

**Files:**
- Create: `src/modules/security_dashboard/snapshots.py`
- Modify: `src/modules/security_dashboard/security_reader.py`
- Test: `tests/test_security_snapshots.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `snapshots.mp_preference() -> Dict[str, Any]`, `snapshots.mp_computer_status() -> Dict[str, Any]`, `snapshots.service_states() -> Dict[str, Dict[str, Any]]`, `snapshots.optional_features() -> Dict[str, str]`, `snapshots.invalidate() -> None`. Each returns `{}` when the underlying call was refused, and `snapshots.availability() -> Dict[str, Optional[str]]` maps snapshot name → refusal reason or `None`. Task 15's Refresh calls `invalidate()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_security_snapshots.py`:

```python
"""One cmdlet call, many readers.

Measured at branch point: one _ps() call costs 0.54s and 57 of the 171 readers
use it -- 19 of them each running Get-MpPreference to pull ONE field out of a
cmdlet that returns all of them. 155 controls read that way is a minute-long
tab, which is the Overview 37.3s defect at ten times the scale.

A refused snapshot must be distinguishable from an empty one. Get-MpPreference
on a machine with Defender replaced by a third-party AV does not fail -- it
answers with fewer fields.
"""
import pytest

from modules.security_dashboard import snapshots


@pytest.fixture(autouse=True)
def _clean():
    snapshots.invalidate()
    yield
    snapshots.invalidate()


def test_the_cmdlet_runs_once_for_many_reads(monkeypatch):
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"DisableRealtimeMonitoring":false,"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    for _ in range(10):
        snapshots.mp_preference()
    assert len(calls) == 1, f"ran the cmdlet {len(calls)} times, not once"


def test_invalidate_forces_a_refetch(monkeypatch):
    calls = []

    def fake_ps(cmd, timeout=30):
        calls.append(cmd)
        return 0, '{"PUAProtection":1}', ""

    monkeypatch.setattr(snapshots, "_ps", fake_ps)
    snapshots.mp_preference()
    snapshots.invalidate()
    snapshots.mp_preference()
    assert len(calls) == 2


def test_a_refusal_is_recorded_as_a_reason_not_as_an_empty_answer(monkeypatch):
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (1, "", "Access is denied."))
    assert snapshots.mp_preference() == {}
    assert "Access is denied" in snapshots.availability()["mp_preference"]


def test_a_cmdlet_that_exits_zero_with_a_complaint_on_stdout_is_a_refusal(monkeypatch):
    """dism exits 740 with its complaint on STDOUT; netsh exits 0 and says
    'No rules match'. rc alone is not a success signal."""
    monkeypatch.setattr(
        snapshots, "_ps",
        lambda cmd, timeout=30: (0, "Elevated permissions are required.", ""))
    assert snapshots.mp_preference() == {}
    assert snapshots.availability()["mp_preference"] is not None
```

- [ ] **Step 2: Run to verify it fails**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_snapshots.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'modules.security_dashboard.snapshots'`.

- [ ] **Step 3: Write `snapshots.py`**

```python
"""One cmdlet call feeding many readers, with refusals kept separate from
empty answers.

Measured at branch point: _ps() costs 0.54s a call, and the readers made 19
separate Get-MpPreference calls, 7 Get-MpComputerStatus, 6 Get-Service and 4
Get-WindowsOptionalFeature -- about 36 PowerShell launches, ~19s, to read
fields that four calls return in full.

Refusal, not emptiness: a Windows admin cmdlet exits 0 while refusing (Get-Tpm
answers TpmPresent: null; dism exits 740 with its complaint on stdout). Each
snapshot therefore records WHY it is empty, and callers must ask.
"""
import json
import logging
import threading
from typing import Any, Dict, Optional

from .security_reader import _ps

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Dict[str, Any] = {}
_reasons: Dict[str, Optional[str]] = {}

#: Phrases a Windows cmdlet uses to refuse while still exiting 0.
_REFUSAL_MARKERS = (
    "access is denied", "elevated permissions are required",
    "requires elevation", "not recognized", "no rules match",
    "unauthorizedaccess", "requested registry access is not allowed",
)


def _looks_refused(rc: int, out: str, err: str) -> Optional[str]:
    """Return a reason string if this was a refusal, else None.

    rc is one signal among several and NOT the deciding one.
    """
    blob = f"{out}\n{err}".strip()
    low = blob.lower()
    if any(marker in low for marker in _REFUSAL_MARKERS):
        return blob.splitlines()[0] if blob else "refused"
    if rc != 0:
        return blob.splitlines()[0] if blob else f"exit code {rc}"
    if not out.strip():
        return "empty response"
    return None


def _fetch_json(name: str, command: str, timeout: int = 30) -> Any:
    rc, out, err = _ps(command, timeout=timeout)
    reason = _looks_refused(rc, out, err)
    if reason:
        logger.warning("snapshot %s unavailable: %s", name, reason)
        _reasons[name] = reason
        return None
    try:
        _reasons[name] = None
        return json.loads(out)
    except (ValueError, TypeError) as exc:
        _reasons[name] = f"unparseable response: {exc}"
        return None


def _cached(name: str, command: str, empty, transform=None, timeout: int = 30):
    with _lock:
        if name in _cache:
            return _cache[name]
        data = _fetch_json(name, command, timeout=timeout)
        value = empty if data is None else (transform(data) if transform else data)
        _cache[name] = value
        return value


def mp_preference() -> Dict[str, Any]:
    """Every Get-MpPreference field, in one call instead of nineteen."""
    return _cached("mp_preference",
                   "Get-MpPreference | ConvertTo-Json -Compress -Depth 3", {})


def mp_computer_status() -> Dict[str, Any]:
    return _cached("mp_computer_status",
                   "Get-MpComputerStatus | ConvertTo-Json -Compress -Depth 3", {})


def service_states() -> Dict[str, Dict[str, Any]]:
    """name (lowercased) -> {'status': ..., 'start_type': ...} for every service."""
    def _index(rows):
        rows = rows if isinstance(rows, list) else [rows]
        return {str(r.get("Name", "")).lower():
                {"status": r.get("Status"), "start_type": r.get("StartType")}
                for r in rows}

    return _cached(
        "service_states",
        "Get-Service | Select-Object Name,Status,StartType | ConvertTo-Json -Compress",
        {}, transform=_index, timeout=60)


def optional_features() -> Dict[str, str]:
    """feature name (lowercased) -> state string."""
    def _index(rows):
        rows = rows if isinstance(rows, list) else [rows]
        return {str(r.get("FeatureName", "")).lower(): str(r.get("State"))
                for r in rows}

    return _cached(
        "optional_features",
        "Get-WindowsOptionalFeature -Online | "
        "Select-Object FeatureName,State | ConvertTo-Json -Compress",
        {}, transform=_index, timeout=120)


def availability() -> Dict[str, Optional[str]]:
    """snapshot name -> refusal reason, or None if it was read successfully.

    A caller that finds an empty snapshot MUST consult this before reporting
    a setting as absent. An empty dict here means "we could not look", not
    "there was nothing there".
    """
    return dict(_reasons)


def invalidate() -> None:
    """Drop every snapshot. Called by the pane's Refresh, never on a timer."""
    with _lock:
        _cache.clear()
        _reasons.clear()
```

- [ ] **Step 4: Run the snapshot tests**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_snapshots.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Point the 19 `Get-MpPreference` readers at the snapshot**

For each reader that currently calls `_ps("Get-MpPreference | Select-Object X ...")`, replace the body's read with `snapshots.mp_preference().get("X")`, and distinguish the two empty cases. Worked example — replace `check_defender_behavior_monitoring`:

```python
def check_defender_behavior_monitoring() -> Dict[str, Any]:
    prefs = snapshots.mp_preference()
    if not prefs:
        reason = snapshots.availability().get("mp_preference") or "unavailable"
        return {"status": "Unknown", "color": "amber", "available": False,
                "details": [("Behavior Monitoring", f"Could not read: {reason}")]}
    enabled = not bool(prefs.get("DisableBehaviorMonitoring", 0))
    return {"status": "On" if enabled else "Off",
            "color": "green" if enabled else "red",
            "available": True, "enabled": enabled,
            "details": [("Behavior Monitoring", "On" if enabled else "Off")]}
```

Note the new `"available"` key: "we could not look" is now distinct from "it is off". Apply the same shape to the 7 `Get-MpComputerStatus` readers, the 6 `Get-Service` readers (via `service_states()`), and the 4 `Get-WindowsOptionalFeature` readers (via `optional_features()`).

- [ ] **Step 6: Replace `_reg_read`'s subprocess with `winreg`**

Measured 21.1 ms → 0.015 ms. Keep the signature and the `None`-on-absent contract exactly, so no caller changes:

```python
_HIVES = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER,
    "HKCR": winreg.HKEY_CLASSES_ROOT, "HKU": winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
}


def _reg_read(key: str, value: str, kind: str = "REG_DWORD") -> Optional[Any]:
    """Read a registry value. Returns None if key or value is absent.

    Was `reg query` in a subprocess at 21.1 ms a call, measured; winreg reads
    the same value in 0.015 ms. With ~150 controls to read that is the
    difference between a responsive pane and the Overview defect again.
    """
    hive_name, _, sub = key.partition("\\")
    hive = _HIVES.get(hive_name.upper())
    if hive is None:
        return None
    try:
        with winreg.OpenKey(hive, sub) as handle:
            raw, _ = winreg.QueryValueEx(handle, value)
    except OSError:
        return None
    if kind == "REG_DWORD" and isinstance(raw, str):
        try:
            return int(raw, 16) if raw.startswith("0x") else int(raw)
        except ValueError:
            return raw
    return raw
```

**Watch the 32/64-bit view.** `reg query` and `winreg.OpenKey` default to the same view for a 64-bit process, so this is a like-for-like swap here — but if any existing reader depended on WOW6432Node redirection, it would change behaviour. Task 18's harness diffs every reader's answer before and after, which is what proves this.

- [ ] **Step 7: Prove the readers still agree, then measure**

Before committing, capture every reader's output on the old code and the new, and diff. Write `tools/reader_parity_check.py` that imports `security_reader`, calls all 171 `check_*` functions, and dumps `{name: result}` to JSON. Run it on `HEAD` (via a worktree — **`git stash` does not stash untracked files** and would run the new tests against old source), run it on the working tree, and diff. Any reader whose answer changed is either a bug you just introduced or a duplicate you just fixed — account for every difference by name.

```
.\.venv\Scripts\python.exe tools\reader_parity_check.py before.json
.\.venv\Scripts\python.exe tools\reader_parity_check.py after.json
.\.venv\Scripts\python.exe tools\reader_parity_check.py --compare before.json after.json
```

Expected differences: the 10 from Task 1 and nothing else, plus wall-clock for a full sweep dropping from ~35 s to under 5 s. **Record the measured before/after number in the commit message.**

- [ ] **Step 8: Run the suite and commit**

```
.\.venv\Scripts\python.exe -m pytest -q
git add src/modules/security_dashboard/snapshots.py src/modules/security_dashboard/security_reader.py tests/test_security_snapshots.py tools/reader_parity_check.py
git commit -m "perf(security): nineteen readers each ran Get-MpPreference to read one field"
```

---

# Phase 2 — The catalog

---

### Task 4: `SecurityControl` and the catalog loader

**Files:**
- Create: `src/modules/security_dashboard/catalog/__init__.py`, `src/modules/security_dashboard/catalog/model.py`
- Test: `tests/test_security_catalog_model.py`

**Interfaces:**
- Consumes: `snapshots` (Task 3) indirectly through readers.
- Produces: `SecurityControl` (frozen dataclass), `Risk` (`LOW`/`MEDIUM`/`HIGH`), `Category` (enum of the eight tabs), `ControlState`, `load_catalog() -> Dict[str, SecurityControl]`, `NOT_A_CONTROL: Dict[str, str]`. Every later task imports these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_security_catalog_model.py`:

```python
"""The catalog is one table; everything else is a filter over it."""
import pytest

from modules.security_dashboard.catalog import load_catalog
from modules.security_dashboard.catalog.model import (
    Category, Risk, SecurityControl,
)


def _control(**over):
    base = dict(id="x", title="X", category=Category.DEFENDER,
                description="d", why_it_matters="w", reader=lambda: {})
    base.update(over)
    return SecurityControl(**base)


def test_a_control_with_no_writer_must_say_why_it_is_read_only():
    with pytest.raises(ValueError, match="read_only_reason"):
        _control()


def test_a_control_with_a_writer_needs_no_reason():
    c = _control(on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                            "data": 1, "kind": "DWORD"},))
    assert c.writable


def test_a_read_only_control_is_not_writable():
    assert not _control(read_only_reason="TPM presence is hardware").writable


def test_reading_defaults_to_the_enabled_key():
    c = _control(read_only_reason="r", reader=lambda: {"enabled": True})
    assert c.read() is True


def test_a_reader_that_could_not_look_reads_as_none_not_as_false():
    """A refused read is not an unset value."""
    c = _control(read_only_reason="r",
                 reader=lambda: {"available": False, "status": "Unknown"})
    assert c.read() is None


def test_a_control_may_supply_its_own_value_extractor():
    c = _control(read_only_reason="r",
                 reader=lambda: {"available": True, "level": 3},
                 read_value=lambda d: d["level"])
    assert c.read() == 3


def test_ids_are_unique_across_the_whole_catalog():
    catalog = load_catalog()
    assert len(catalog) == len({c.id for c in catalog.values()})
```

- [ ] **Step 2: Run to verify it fails**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_model.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'modules.security_dashboard.catalog'`.

- [ ] **Step 3: Write `catalog/model.py`**

```python
"""One entry per security control: what it reads, what it writes, what it costs
to get wrong."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Tuple


class Category(Enum):
    DEFENDER = "Defender"
    FIREWALL_NETWORK = "Firewall & Network"
    ACCOUNTS = "Accounts & Credentials"
    DEVICE_BOOT = "Device & Boot"
    SERVICES = "Services"
    FEATURES = "Windows Features"
    EXPLOIT_CVE = "Exploit & CVE"


class Risk(Enum):
    LOW = "low"          # reversible, no reboot, nothing depends on it
    MEDIUM = "medium"    # may break a workflow; confirm before applying
    HIGH = "high"        # boot, disk encryption, credential handling, VBS.
                         # Forces a Windows restore point on the batch.


class ControlState(Enum):
    APPLIED_VERIFIED = "applied_verified"
    APPLIED_PENDING_REBOOT = "applied_pending_reboot"
    APPLIED_UNVERIFIED = "applied_unverified"
    REFUSED = "refused"


@dataclass(frozen=True)
class SecurityControl:
    id: str
    title: str
    category: Category
    description: str
    why_it_matters: str
    reader: Callable[[], Dict[str, Any]]
    on_steps: Tuple[Dict, ...] = ()
    off_steps: Tuple[Dict, ...] = ()
    desired: Optional[Any] = None
    risk: Risk = Risk.LOW
    requires_admin: bool = True
    requires_reboot: bool = False
    read_only_reason: Optional[str] = None
    docs_url: Optional[str] = None
    #: Pull the comparable value out of the reader's dict. Defaults to the
    #: "enabled" key; multi-valued controls (NTLM level, cached logon count,
    #: cloud block level) supply their own.
    read_value: Optional[Callable[[Dict[str, Any]], Any]] = None

    def __post_init__(self):
        if not self.on_steps and not self.off_steps and not self.read_only_reason:
            raise ValueError(
                f"control {self.id!r} has no on_steps/off_steps and no "
                "read_only_reason: a control we cannot write must say why")

    @property
    def writable(self) -> bool:
        return bool(self.on_steps or self.off_steps)

    def read(self) -> Optional[Any]:
        """Current value, or None if the machine could not be asked.

        None means "we could not look" and is never collapsed into False.
        """
        try:
            result = self.reader() or {}
        except Exception:
            return None
        if result.get("available") is False:
            return None
        if self.read_value is not None:
            try:
                return self.read_value(result)
            except (KeyError, TypeError):
                return None
        return result.get("enabled")

    def steps_for(self, desired_value: Any) -> Tuple[Dict, ...]:
        return self.on_steps if desired_value else self.off_steps
```

- [ ] **Step 4: Write `catalog/__init__.py`**

```python
"""Assemble the catalog from its category modules."""
from typing import Dict

from .model import Category, ControlState, Risk, SecurityControl

#: check_* functions in security_reader.py that are deliberately NOT controls,
#: each with the reason. The binding test (test_security_catalog_binding.py)
#: fails on any reader that is neither bound nor listed here, so a check
#: cannot quietly fail to reach the pane.
NOT_A_CONTROL: Dict[str, str] = {}


def load_catalog() -> Dict[str, SecurityControl]:
    """id -> control, across every category module."""
    from . import (accounts, defender, device_boot, exploit_cve, features,
                   firewall_network, services)

    catalog: Dict[str, SecurityControl] = {}
    for module in (defender, firewall_network, accounts, device_boot,
                   services, features, exploit_cve):
        for control in module.CONTROLS:
            if control.id in catalog:
                raise ValueError(f"duplicate control id: {control.id}")
            catalog[control.id] = control
    return catalog
```

Create each of the seven category modules now with `CONTROLS: Tuple[SecurityControl, ...] = ()` so the import resolves. Tasks 6-8 fill them.

- [ ] **Step 5: Run the tests**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_model.py -v
```

Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/modules/security_dashboard/catalog tests/test_security_catalog_model.py
git commit -m "feat(security): a control is a row, not a hand-wired widget"
```

---

### Task 5: The binding test that makes 147 missing controls impossible

This is the task that makes catalog completeness machine-checkable instead of a matter of diligence.

**Files:**
- Create: `tests/test_security_catalog_binding.py`

**Interfaces:**
- Consumes: `load_catalog`, `NOT_A_CONTROL` (Task 4).
- Produces: the failing gate that Tasks 6-8 close.

- [ ] **Step 1: Write the test**

```python
"""Every reader either reaches the pane or is named as deliberately not a control.

The pane could see 171 things and change 24. The other 147 were not blocked by
Windows -- they were never wired, and nothing anywhere said so. This test is
the thing that makes that impossible to repeat: a check_* function that is
neither bound to a control nor listed in NOT_A_CONTROL with a reason fails the
suite.
"""
import inspect

from modules.security_dashboard import security_reader
from modules.security_dashboard.catalog import NOT_A_CONTROL, load_catalog


def _all_readers():
    return {name for name, obj in inspect.getmembers(security_reader, inspect.isfunction)
            if name.startswith("check_") and obj.__module__ == security_reader.__name__}


def test_every_reader_is_bound_or_explicitly_excluded():
    bound = {c.reader.__name__ for c in load_catalog().values()
             if hasattr(c.reader, "__name__")}
    unaccounted = sorted(_all_readers() - bound - set(NOT_A_CONTROL))
    assert not unaccounted, (
        f"{len(unaccounted)} readers reach nothing and are not listed in "
        f"NOT_A_CONTROL:\n  " + "\n  ".join(unaccounted))


def test_every_exclusion_names_a_real_reader():
    stale = sorted(set(NOT_A_CONTROL) - _all_readers())
    assert not stale, f"NOT_A_CONTROL names readers that no longer exist: {stale}"


def test_every_exclusion_gives_a_reason():
    empty = sorted(k for k, v in NOT_A_CONTROL.items() if not v or not v.strip())
    assert not empty, f"excluded with no reason given: {empty}"


def test_every_control_has_a_reader_that_is_callable():
    assert all(callable(c.reader) for c in load_catalog().values())


def test_every_writable_controls_steps_have_a_known_type():
    known = {"registry", "registry_delete", "service", "command",
             "script", "appx", "scheduled_task"}
    bad = []
    for control in load_catalog().values():
        for step in tuple(control.on_steps) + tuple(control.off_steps):
            if step.get("type") not in known:
                bad.append(f"{control.id}: {step.get('type')!r}")
    assert not bad, f"unknown step types: {bad}"


def test_every_registry_step_is_fully_specified():
    bad = []
    for control in load_catalog().values():
        for step in tuple(control.on_steps) + tuple(control.off_steps):
            if step.get("type") != "registry":
                continue
            if not step.get("key") or "data" not in step:
                bad.append(f"{control.id}: {step}")
    assert not bad, f"registry steps missing key or data: {bad}"
```

- [ ] **Step 2: Run it and record the starting number**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_binding.py -v
```

Expected: `test_every_reader_is_bound_or_explicitly_excluded` FAILS listing **161** unaccounted readers (171 minus the 10 resolved in Task 1). The other five pass trivially. Record that number — Tasks 6-8 drive it to zero.

- [ ] **Step 3: Commit the failing gate**

Commit it failing, marked `xfail` with a reason, so the suite stays green while the catalog is populated:

```python
import pytest

@pytest.mark.xfail(reason="catalog population in progress, Tasks 6-8", strict=False)
def test_every_reader_is_bound_or_explicitly_excluded():
```

Task 8's final step removes the `xfail`. A `strict=False` xfail that starts passing does not fail the suite, which is what lets Tasks 6 and 7 make partial progress.

```bash
git add tests/test_security_catalog_binding.py
git commit -m "test(security): 161 readers reach nothing, and now the suite says so"
```

---

### Task 6: Populate Defender and Exploit/CVE

**Files:**
- Modify: `src/modules/security_dashboard/catalog/defender.py`, `src/modules/security_dashboard/catalog/exploit_cve.py`
- Modify: `src/modules/security_dashboard/catalog/__init__.py` (`NOT_A_CONTROL`)

**Interfaces:**
- Consumes: `SecurityControl`, `Risk`, `Category` (Task 4); `snapshots` (Task 3).
- Produces: `defender.CONTROLS`, `exploit_cve.CONTROLS`.

- [ ] **Step 1: List what this task must account for**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_binding.py::test_every_reader_is_bound_or_explicitly_excluded -v --runxfail
```

Take from the failure list every reader matching `check_defender_*`, `check_exploit_protection_*`, `check_elam`, `check_pua_protection`, `check_controlled_folder_access`, `check_cloud_protection`, `check_tamper_protection`, `check_network_protection_defender`, `check_applocker`, plus the eleven CVE cards. Each one gets either a control or a `NOT_A_CONTROL` entry in this task.

- [ ] **Step 2: Write the Defender controls**

`Set-MpPreference` is the only writer for most of these, so they are `script` steps. Worked examples covering all three shapes in this category:

```python
"""Defender controls.

Most are Set-MpPreference only -- there is no registry equivalent that
Defender honours -- so they are script steps whose revert_command is computed
at stage time from the reader's current value (spec 2.2). Where a registry
equivalent DOES exist and Defender honours it, the registry step wins, because
BackupService can restore a registry value exactly and cannot revert a command.
"""
from typing import Tuple

from ..security_reader import (
    check_controlled_folder_access, check_defender_behavior_monitoring,
    check_defender_archive_scanning, check_defender_cloud_block_level,
    check_defender_email_scanning, check_defender_engine_version,
    check_defender_ioav, check_defender_removable_drive,
    check_defender_script_scanning, check_pua_protection,
    check_tamper_protection,
)
from .model import Category, Risk, SecurityControl

CONTROLS: Tuple[SecurityControl, ...] = (

    # -- a plain two-state cmdlet control ---------------------------------
    SecurityControl(
        id="defender_behavior_monitoring",
        title="Behaviour monitoring",
        category=Category.DEFENDER,
        description="Watches running processes for malicious behaviour rather "
                    "than matching known file signatures.",
        why_it_matters="Signature scanning cannot see fileless malware or a "
                       "living-off-the-land attack driven entirely through "
                       "PowerShell and WMI. Behaviour monitoring is what does.",
        reader=check_defender_behavior_monitoring,
        on_steps=({"type": "script",
                   "command": "powershell -NoProfile -Command "
                              "Set-MpPreference -DisableBehaviorMonitoring $false"},),
        off_steps=({"type": "script",
                    "command": "powershell -NoProfile -Command "
                               "Set-MpPreference -DisableBehaviorMonitoring $true"},),
        desired=True,
        risk=Risk.MEDIUM,
    ),

    # -- a multi-valued control: read_value pulls the level, not a bool ----
    SecurityControl(
        id="defender_cloud_block_level",
        title="Cloud-delivered protection level",
        category=Category.DEFENDER,
        description="How aggressively Defender blocks files its cloud service "
                    "is unsure about. 0 default, 2 high, 4 high+, 6 zero tolerance.",
        why_it_matters="At the default level a brand-new sample is allowed to "
                       "run while the cloud makes up its mind.",
        reader=check_defender_cloud_block_level,
        read_value=lambda d: d.get("level"),
        on_steps=({"type": "script",
                   "command": "powershell -NoProfile -Command "
                              "Set-MpPreference -CloudBlockLevel 2"},),
        off_steps=({"type": "script",
                    "command": "powershell -NoProfile -Command "
                               "Set-MpPreference -CloudBlockLevel 0"},),
        desired=2,
        risk=Risk.MEDIUM,
    ),

    # -- read-only, and it says why ---------------------------------------
    SecurityControl(
        id="defender_engine_version",
        title="Defender engine version",
        category=Category.DEFENDER,
        description="The version of the Defender scanning engine currently loaded.",
        why_it_matters="An engine well behind the current one is a sign that "
                       "updates are not reaching this machine.",
        reader=check_defender_engine_version,
        read_only_reason="The engine version is set by Windows Update and "
                         "Defender platform updates. Update definitions from "
                         "the Defender tab instead of setting this.",
    ),
)
```

Continue in this shape for every Defender reader from Step 1. **Tamper Protection gets `read_only_reason`** if the reader shows it enabled — Tamper Protection exists specifically to refuse programmatic changes to Defender settings, and a button that silently does nothing is worse than no button. State that as the reason.

- [ ] **Step 3: Write the CVE controls**

The eleven CVE cards. Registry-settable mitigations get real controls; the rest say what actually fixes them:

```python
    SecurityControl(
        id="cve_printnightmare",
        title="PrintNightmare (CVE-2021-34527)",
        category=Category.EXPLOIT_CVE,
        description="Restricts driver installation through the Print Spooler "
                    "to administrators.",
        why_it_matters="Unpatched, any authenticated user on the network can "
                       "load a driver as SYSTEM on this machine.",
        reader=check_cve_printnightmare,
        on_steps=({"type": "registry",
                   "key": r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT"
                          r"\Printers\PointAndPrint",
                   "value": "RestrictDriverInstallationToAdministrators",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry",
                    "key": r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT"
                           r"\Printers\PointAndPrint",
                    "value": "RestrictDriverInstallationToAdministrators",
                    "data": 0, "kind": "DWORD"},),
        desired=True,
        risk=Risk.MEDIUM,
    ),

    SecurityControl(
        id="cve_meltdown",
        title="Meltdown (CVE-2017-5754)",
        category=Category.EXPLOIT_CVE,
        description="Kernel page-table isolation.",
        why_it_matters="Lets an unprivileged process read kernel memory, "
                       "including credentials belonging to other users.",
        reader=check_cve_meltdown,
        read_only_reason="Mitigated by CPU microcode plus the Windows kernel. "
                         "It is not a setting: it is fixed by installing "
                         "firmware and Windows updates.",
    ),
```

- [ ] **Step 4: Add `NOT_A_CONTROL` entries for the aggregates**

In `catalog/__init__.py`:

```python
NOT_A_CONTROL: Dict[str, str] = {
    "check_defender_signatures":
        "A freshness reading, not a setting. The Defender tab's "
        "'Update definitions' action is the thing that changes it.",
    "check_defender_threats":
        "A count of detections. Read-only by nature.",
    "check_defender_quarantine":
        "Lists quarantined items; acting on them is a separate operation.",
    "check_defender_last_scan":
        "A timestamp. 'Run quick scan' is the action that changes it.",
    "check_defender_scanning_history":
        "History, not configuration.",
    "check_defender_av_mode":
        "Reports whether Defender is primary, passive or disabled. That is "
        "decided by which AV products are installed, not by a setting.",
}
```

- [ ] **Step 5: Run the binding test and the suite**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_binding.py -v --runxfail
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: the unaccounted count drops from 161 by the number of Defender + CVE readers. Suite green.

- [ ] **Step 6: Commit**

```bash
git add src/modules/security_dashboard/catalog
git commit -m "feat(security): Defender and the CVE mitigations become catalog rows"
```

---

### Task 7: Populate Firewall & Network, and Accounts & Credentials

**Files:**
- Modify: `src/modules/security_dashboard/catalog/firewall_network.py`, `src/modules/security_dashboard/catalog/accounts.py`, `catalog/__init__.py`

**Interfaces:**
- Consumes: Task 4's model.
- Produces: `firewall_network.CONTROLS`, `accounts.CONTROLS`.

- [ ] **Step 1: List what this task must account for**

From the binding-test failure list: `check_firewall*`, `check_llmnr`, `check_netbios_tcpip`, `check_wpad`, `check_mdns`, `check_winrm`, `check_remote_registry`, `check_telnet`, `check_smb_signing`, `check_smbv1`, `check_ntlm_level`, `check_network_profile`, `check_rdp`, `check_listening_ports`, and every `check_*` in the accounts group (`check_uac`, `check_guest_account`, `check_autologon`, `check_last_username_hidden`, `check_screensaver_secure`, `check_wdigest`, `check_cached_logons`, `check_account_lockout`, `check_password_min_length`, `check_lsass_protection`, `check_credential_guard`, `check_windows_hello`, `check_ctrl_alt_del`, `check_ps_*`).

- [ ] **Step 2: Write the network controls, registry-first**

These mostly have registry representations, so they get exact revert for free:

```python
    SecurityControl(
        id="llmnr",
        title="LLMNR (Link-Local Multicast Name Resolution)",
        category=Category.FIREWALL_NETWORK,
        description="Legacy name resolution used when DNS has no answer.",
        why_it_matters="Anyone on the same network can answer an LLMNR query "
                       "and receive this machine's NTLMv2 hash. It is the "
                       "first thing Responder does, and almost nothing needs it.",
        reader=check_llmnr,
        on_steps=({"type": "registry",
                   "key": r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient",
                   "value": "EnableMulticast", "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry",
                    "key": r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\DNSClient",
                    "value": "EnableMulticast", "data": 0, "kind": "DWORD"},),
        desired=False,
        risk=Risk.LOW,
    ),

    SecurityControl(
        id="wdigest_credential_caching",
        title="WDigest credential caching",
        category=Category.ACCOUNTS,
        description="Whether WDigest keeps plaintext credentials in LSASS memory.",
        why_it_matters="With this on, mimikatz reads your password in "
                       "cleartext out of memory rather than a hash it has to "
                       "crack. There is no modern reason to enable it.",
        reader=check_wdigest,
        on_steps=({"type": "registry",
                   "key": r"HKLM\SYSTEM\CurrentControlSet\Control"
                          r"\SecurityProviders\WDigest",
                   "value": "UseLogonCredential", "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry",
                    "key": r"HKLM\SYSTEM\CurrentControlSet\Control"
                           r"\SecurityProviders\WDigest",
                    "value": "UseLogonCredential", "data": 0, "kind": "DWORD"},),
        desired=False,
        risk=Risk.LOW,
    ),
```

`check_uac` and `check_credential_guard` are `Risk.HIGH` — UAC because turning it off removes the elevation boundary entirely, Credential Guard because it is VBS-backed and `requires_reboot=True`.

- [ ] **Step 3: `check_listening_ports` and `check_firewall_stealth`**

`check_listening_ports` is an inventory, not a setting: `NOT_A_CONTROL["check_listening_ports"] = "An inventory of what is listening. The Firewall Rules module is where a port is closed."`

- [ ] **Step 4: Run the binding test and the suite**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_binding.py -v --runxfail
.\.venv\Scripts\python.exe -m pytest -q
```

- [ ] **Step 5: Commit**

```bash
git add src/modules/security_dashboard/catalog
git commit -m "feat(security): network and credential hardening become catalog rows"
```

---

### Task 8: Populate Device & Boot, Services, Features — and close the gate

**Files:**
- Modify: `catalog/device_boot.py`, `catalog/services.py`, `catalog/features.py`, `catalog/__init__.py`
- Modify: `tests/test_security_catalog_binding.py` (remove the `xfail`)

**Interfaces:**
- Consumes: Task 4's model; `snapshots.service_states()` and `snapshots.optional_features()` (Task 3).
- Produces: the remaining `CONTROLS` tuples, and a passing binding test.

- [ ] **Step 1: Services, from the resolved names**

Every service control is a `service` step, which `BackupService` reverts exactly by restoring the prior start type:

```python
    SecurityControl(
        id="service_webclient",
        title="WebClient (WebDAV)",
        category=Category.SERVICES,
        description="Lets Windows mount WebDAV shares as drives.",
        why_it_matters="A live WebDAV client turns a UNC path in a document "
                       "into an outbound authenticated request to an attacker's "
                       "server. Almost nothing on a workstation needs it.",
        reader=check_service_webclient,
        on_steps=({"type": "service", "name": "WebClient", "start_type": "manual"},),
        off_steps=({"type": "service", "name": "WebClient", "start_type": "disabled"},),
        desired=False,
        risk=Risk.LOW,
    ),
```

- [ ] **Step 2: Windows features**

`dism` is the writer. It exits 740 with its complaint on **stdout** when unelevated, which Task 2's capture now records:

```python
    SecurityControl(
        id="feature_smb1",
        title="SMB 1.0/CIFS File Sharing Support",
        category=Category.FEATURES,
        description="The original SMB protocol, from 1983.",
        why_it_matters="SMBv1 is what WannaCry spread over. It has no signing "
                       "worth the name and Microsoft removed it by default in 2017.",
        reader=check_smbv1,
        on_steps=({"type": "command",
                   "cmd": "dism /online /enable-feature "
                          "/featurename:SMB1Protocol /norestart"},),
        off_steps=({"type": "command",
                    "cmd": "dism /online /disable-feature "
                           "/featurename:SMB1Protocol /norestart"},),
        desired=False,
        risk=Risk.MEDIUM,
        requires_reboot=True,
    ),
```

- [ ] **Step 3: Device & Boot — mostly read-only, each saying why**

```python
    SecurityControl(
        id="tpm_present",
        title="TPM",
        category=Category.DEVICE_BOOT,
        description="Trusted Platform Module presence, version and readiness.",
        why_it_matters="BitLocker, Credential Guard and Windows Hello all rest "
                       "on it. Without one they fall back to weaker protection.",
        reader=check_tpm_details,
        read_only_reason="A TPM is hardware, enabled in firmware. Nothing "
                         "Windows can write turns one on.",
    ),

    SecurityControl(
        id="secure_boot",
        title="Secure Boot",
        category=Category.DEVICE_BOOT,
        description="Firmware refuses to load a bootloader it cannot verify.",
        why_it_matters="Without it a bootkit loads before Windows and before "
                       "any protection Windows could offer.",
        reader=check_secure_boot_tpm,
        read_only_reason="Secure Boot is a UEFI firmware setting. Windows can "
                         "read it and cannot change it; use the firmware setup "
                         "screen.",
    ),
```

BitLocker **is** writable (`manage-bde`), and is `Risk.HIGH` with `requires_reboot=True`. A control that could lock a user out of their data if the recovery key is not saved must say so in `why_it_matters`.

- [ ] **Step 4: Account for every remaining reader**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_binding.py -v --runxfail
```

Repeat until the unaccounted list is empty. Any reader you are unsure about goes in `NOT_A_CONTROL` with an honest reason — "I do not know a safe writer for this" is a legitimate reason and is better than a button that does nothing.

- [ ] **Step 5: Remove the `xfail` and run everything**

Delete the `@pytest.mark.xfail` decorator added in Task 5.

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_catalog_binding.py -v
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: binding test PASSES with no marker. Record the final catalog size.

- [ ] **Step 6: Commit**

```bash
git add src/modules/security_dashboard/catalog tests/test_security_catalog_binding.py
git commit -m "feat(security): every reader now reaches the pane or says why it does not"
```

---

# Phase 3 — The write path

---

### Task 9: Staging

**Files:**
- Create: `src/modules/security_dashboard/staging.py`
- Test: `tests/test_security_staging.py`

**Interfaces:**
- Consumes: `SecurityControl`, `load_catalog`.
- Produces: `PendingChange(control_id, from_value, to_value, control)`, `ChangeSet` with `.add(control, to_value)`, `.remove(control_id)`, `.clear()`, `.changes -> Tuple[PendingChange, ...]`, `.needs_admin -> bool`, `.highest_risk -> Risk`, `.needs_reboot -> bool`, and `diff_against(catalog, target: Dict[str, Any]) -> ChangeSet`. Task 11 executes a `ChangeSet`; Tasks 16-17 build one from a baseline or profile.

- [ ] **Step 1: Write the failing test**

```python
"""Toggling stages; nothing touches the machine until Apply."""
import pytest

from modules.security_dashboard.catalog.model import (
    Category, Risk, SecurityControl)
from modules.security_dashboard.staging import ChangeSet, diff_against


def _control(cid, current, **over):
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w", reader=lambda: {"available": True, "enabled": current},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_staging_a_change_records_where_it_came_from():
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)
    change = cs.changes[0]
    assert (change.from_value, change.to_value) == (True, False)


def test_staging_the_value_it_already_has_is_not_a_change():
    cs = ChangeSet()
    cs.add(_control("llmnr", True), True)
    assert cs.changes == ()


def test_staging_the_same_control_twice_keeps_one_entry():
    cs = ChangeSet()
    control = _control("llmnr", True)
    cs.add(control, False)
    cs.add(control, False)
    assert len(cs.changes) == 1


def test_staging_back_to_the_original_value_removes_the_change():
    cs = ChangeSet()
    control = _control("llmnr", True)
    cs.add(control, False)
    cs.add(control, True)
    assert cs.changes == ()


def test_the_batch_reports_its_highest_risk():
    cs = ChangeSet()
    cs.add(_control("a", True), False)
    cs.add(_control("b", True, risk=Risk.HIGH), False)
    assert cs.highest_risk is Risk.HIGH


def test_a_batch_with_a_reboot_control_says_so():
    cs = ChangeSet()
    cs.add(_control("a", True, requires_reboot=True), False)
    assert cs.needs_reboot


def test_a_control_that_could_not_be_read_is_still_stageable():
    """A refused read must not silently make a control unstageable -- the
    user may be staging it precisely because it could not be read."""
    unreadable = _control("x", None, reader=lambda: {"available": False})
    cs = ChangeSet()
    cs.add(unreadable, True)
    assert cs.changes[0].from_value is None


def test_diff_against_a_target_stages_only_what_differs():
    catalog = {"a": _control("a", True), "b": _control("b", False)}
    cs = diff_against(catalog, {"a": True, "b": True})
    assert [c.control_id for c in cs.changes] == ["b"]


def test_diff_ignores_ids_the_catalog_does_not_have():
    catalog = {"a": _control("a", True)}
    cs = diff_against(catalog, {"a": False, "ghost": True})
    assert [c.control_id for c in cs.changes] == ["a"]
```

- [ ] **Step 2: Run to verify it fails**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_staging.py -v
```

Expected: FAIL — no module `staging`.

- [ ] **Step 3: Write `staging.py`**

```python
"""Changes stage, then apply as one batch. Nothing here touches the machine."""
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .catalog.model import Risk, SecurityControl


@dataclass(frozen=True)
class PendingChange:
    control_id: str
    control: SecurityControl
    from_value: Optional[Any]
    to_value: Any


class ChangeSet:
    """Staged changes, keyed by control id. Staging a control back to the
    value it already has removes it rather than queueing a no-op."""

    def __init__(self) -> None:
        self._changes: Dict[str, PendingChange] = {}

    def add(self, control: SecurityControl, to_value: Any) -> None:
        current = control.read()
        if current == to_value:
            self._changes.pop(control.id, None)
            return
        self._changes[control.id] = PendingChange(
            control_id=control.id, control=control,
            from_value=current, to_value=to_value)

    def remove(self, control_id: str) -> None:
        self._changes.pop(control_id, None)

    def clear(self) -> None:
        self._changes.clear()

    @property
    def changes(self) -> Tuple[PendingChange, ...]:
        return tuple(self._changes.values())

    def __len__(self) -> int:
        return len(self._changes)

    @property
    def needs_admin(self) -> bool:
        return any(c.control.requires_admin for c in self._changes.values())

    @property
    def needs_reboot(self) -> bool:
        return any(c.control.requires_reboot for c in self._changes.values())

    @property
    def highest_risk(self) -> Risk:
        order = {Risk.LOW: 0, Risk.MEDIUM: 1, Risk.HIGH: 2}
        return max((c.control.risk for c in self._changes.values()),
                   key=lambda r: order[r], default=Risk.LOW)


def diff_against(catalog: Dict[str, SecurityControl],
                 target: Dict[str, Any]) -> ChangeSet:
    """Stage everything in `target` that differs from the live machine.

    Ids the catalog does not know are ignored, not an error: a profile from a
    newer build of the app names controls this one has not got.
    """
    changes = ChangeSet()
    for control_id, desired in target.items():
        control = catalog.get(control_id)
        if control is None or not control.writable:
            continue
        changes.add(control, desired)
    return changes
```

- [ ] **Step 4: Run the tests**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_staging.py -v
```

Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/security_dashboard/staging.py tests/test_security_staging.py
git commit -m "feat(security): changes stage before they apply"
```

---

### Task 10: Computed revert commands for cmdlet-only controls

**Files:**
- Modify: `src/modules/security_dashboard/staging.py`
- Test: `tests/test_security_staging.py` (extend)

**Interfaces:**
- Consumes: `PendingChange`.
- Produces: `PendingChange.resolved_steps() -> Tuple[Dict, ...]` — the control's steps with `revert_command` filled in from `from_value` for `script` steps. Task 11 applies `resolved_steps()`, never raw `on_steps`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_script_step_gets_a_revert_command_built_from_the_current_value():
    """BackupService cannot revert a script step without one, and a static
    revert command in the catalog cannot know what it is reverting TO."""
    control = _control(
        "rt", True,
        on_steps=({"type": "script",
                   "command": "Set-MpPreference -DisableRealtimeMonitoring $false",
                   "revert_template": "Set-MpPreference -DisableRealtimeMonitoring ${old}",
                   "revert_values": {"True": "$false", "False": "$true"}},),
        off_steps=({"type": "script",
                    "command": "Set-MpPreference -DisableRealtimeMonitoring $true",
                    "revert_template": "Set-MpPreference -DisableRealtimeMonitoring ${old}",
                    "revert_values": {"True": "$false", "False": "$true"}},))
    cs = ChangeSet()
    cs.add(control, False)
    step = cs.changes[0].resolved_steps()[0]
    assert step["revert_command"] == (
        "Set-MpPreference -DisableRealtimeMonitoring $false")


def test_a_registry_step_needs_no_revert_command():
    """BackupService restores the recorded before_value exactly, including
    deleting a value that did not exist. Do not invent one."""
    cs = ChangeSet()
    cs.add(_control("llmnr", True), False)
    assert "revert_command" not in cs.changes[0].resolved_steps()[0]


def test_an_unreadable_current_value_yields_no_revert_command():
    """Better no revert than a revert to a value we guessed."""
    control = _control(
        "rt", None, reader=lambda: {"available": False},
        on_steps=({"type": "script", "command": "x",
                   "revert_template": "y ${old}",
                   "revert_values": {"True": "$false"}},))
    cs = ChangeSet()
    cs.add(control, True)
    assert cs.changes[0].resolved_steps()[0].get("revert_command") is None
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — `PendingChange` has no `resolved_steps`.

- [ ] **Step 3: Implement**

Add to `PendingChange`:

```python
    def resolved_steps(self) -> Tuple[Dict, ...]:
        """The steps to run, with script reverts computed from from_value.

        A static revert_command in the catalog cannot know what it is
        reverting to. An unreadable from_value yields no revert command at
        all -- better none than one aimed at a guess.
        """
        resolved = []
        for step in self.control.steps_for(self.to_value):
            step = dict(step)
            template = step.pop("revert_template", None)
            values = step.pop("revert_values", None)
            if template and values is not None and self.from_value is not None:
                old = values.get(str(self.from_value))
                step["revert_command"] = (
                    template.replace("${old}", old) if old is not None else None)
            resolved.append(step)
        return tuple(resolved)
```

Note `step.pop` on a **copy** — the catalog's dicts are shared and must not be mutated.

- [ ] **Step 4: Run tests, then commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_staging.py -v
.\.venv\Scripts\python.exe -m pytest -q
git add src/modules/security_dashboard/staging.py tests/test_security_staging.py
git commit -m "feat(security): a cmdlet control's revert is computed, not guessed"
```

---

### Task 11: Apply a batch, and verify every write

The centre of the design. `_apply_command` reported success without reading rc or output (fixed in Task 2); this task makes the *pane* stop believing the writer.

**Files:**
- Create: `src/modules/security_dashboard/applier.py`
- Test: `tests/test_security_applier.py`

**Interfaces:**
- Consumes: `ChangeSet`, `PendingChange.resolved_steps()`, `TweakEngine`, `BackupService`, `ControlState`.
- Produces: `ControlResult(control_id, state, requested, observed, reason)`, `BatchResult(rp_id, results, windows_restore_point)`, `apply_batch(changeset, engine, backup, *, create_windows_restore_point=None) -> BatchResult`. Task 14 renders a `BatchResult`; Task 12 serialises one.

- [ ] **Step 1: Write the failing test**

```python
"""Applying is not believing.

TweakEngine reports success when its writer returned. That is not evidence the
machine changed: this project has four separate cmdlets on record that exit 0
while refusing. Every control is therefore re-read after its write, and a
writer that "succeeded" against a reader that disagrees is its own state --
APPLIED_UNVERIFIED -- which is the state that today does not exist and is
reported as success.
"""
import pytest

from modules.security_dashboard.applier import apply_batch
from modules.security_dashboard.catalog.model import (
    Category, ControlState, Risk, SecurityControl)
from modules.security_dashboard.staging import ChangeSet


class _Backup:
    def __init__(self): self.points = []
    def create_restore_point(self, label, module):
        self.points.append((label, module)); return "rp-1"
    def record_steps(self, *a, **k): pass
    def backup_registry_key(self, *a, **k): pass


class _Engine:
    def __init__(self, ok=True): self.ok, self.applied = ok, []
    def apply_tweak(self, tweak, rp_id, on_error=None):
        self.applied.append(tweak["id"])
        if not self.ok and on_error:
            on_error("Access is denied.")
        return self.ok


def _control(cid, readings, **over):
    """readings: a list popped one per read, so before/after can differ."""
    base = dict(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": readings.pop(0)},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},),
        off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                    "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_a_write_the_reader_confirms_is_verified():
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)     # reads True, then False
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_VERIFIED


def test_a_write_the_reader_contradicts_is_not_reported_as_success():
    cs = ChangeSet()
    cs.add(_control("a", [True, True]), False)      # asked for False, still True
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_UNVERIFIED
    assert result.results[0].observed is True
    assert result.results[0].requested is False


def test_a_refused_write_carries_the_reason():
    cs = ChangeSet()
    cs.add(_control("a", [True, True]), False)
    result = apply_batch(cs, _Engine(ok=False), _Backup())
    assert result.results[0].state is ControlState.REFUSED
    assert "Access is denied" in result.results[0].reason


def test_a_reboot_control_is_not_marked_unverified_before_the_reboot():
    cs = ChangeSet()
    cs.add(_control("a", [True, True], requires_reboot=True), False)
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_PENDING_REBOOT


def test_one_refusal_does_not_abandon_the_rest_of_the_batch():
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    cs.add(_control("b", [True, False]), False)
    result = apply_batch(cs, _Engine(), _Backup())
    assert len(result.results) == 2


def test_every_batch_takes_an_app_restore_point():
    backup = _Backup()
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    apply_batch(cs, _Engine(), backup)
    assert backup.points and backup.points[0][1] == "Security Dashboard"


def test_only_a_high_risk_batch_takes_a_windows_restore_point():
    calls = []
    cs = ChangeSet()
    cs.add(_control("a", [True, False]), False)
    apply_batch(cs, _Engine(), _Backup(),
                create_windows_restore_point=lambda d: calls.append(d) or (True, ""))
    assert calls == [], "a low-risk batch must not spend 30s on a restore point"

    cs2 = ChangeSet()
    cs2.add(_control("b", [True, False], risk=Risk.HIGH), False)
    apply_batch(cs2, _Engine(), _Backup(),
                create_windows_restore_point=lambda d: calls.append(d) or (True, ""))
    assert len(calls) == 1


def test_a_reader_that_throws_after_the_write_is_unverified_not_a_crash():
    def boom():
        raise OSError("registry unavailable")
    cs = ChangeSet()
    control = _control("a", [True])
    cs.add(control, False)
    object.__setattr__(control, "reader", boom)
    result = apply_batch(cs, _Engine(), _Backup())
    assert result.results[0].state is ControlState.APPLIED_UNVERIFIED
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — no module `applier`.

- [ ] **Step 3: Write `applier.py`**

```python
"""Execute a staged batch, and believe the reader rather than the writer."""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

from .catalog.model import ControlState, Risk
from .staging import ChangeSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ControlResult:
    control_id: str
    state: ControlState
    requested: Any
    observed: Any
    reason: str = ""


@dataclass
class BatchResult:
    rp_id: str
    results: List[ControlResult] = field(default_factory=list)
    windows_restore_point: Optional[str] = None

    @property
    def verified(self) -> int:
        return sum(1 for r in self.results
                   if r.state is ControlState.APPLIED_VERIFIED)

    @property
    def problems(self) -> Tuple[ControlResult, ...]:
        return tuple(r for r in self.results
                     if r.state in (ControlState.APPLIED_UNVERIFIED,
                                    ControlState.REFUSED))


def apply_batch(changeset: ChangeSet, engine, backup,
                create_windows_restore_point: Optional[Callable] = None
                ) -> BatchResult:
    """Apply every staged change, then re-read each control to check.

    A restore point is always taken in the app's own backup store; a Windows
    restore point costs 30+ seconds and is taken only when the batch carries a
    high-risk control.
    """
    rp_id = backup.create_restore_point(
        f"Security Dashboard: {len(changeset)} change(s)", "Security Dashboard")

    windows_rp = None
    if (create_windows_restore_point is not None
            and changeset.highest_risk is Risk.HIGH):
        ok, message = create_windows_restore_point(
            "Before Security Dashboard changes")
        windows_rp = message if ok else None
        if not ok:
            logger.warning("Windows restore point refused: %s", message)

    result = BatchResult(rp_id=rp_id, windows_restore_point=windows_rp)

    for change in changeset.changes:
        errors: List[str] = []
        tweak = {"id": change.control_id, "steps": list(change.resolved_steps())}
        try:
            ok = engine.apply_tweak(tweak, rp_id, on_error=errors.append)
        except Exception as exc:            # a writer that raised is a refusal
            ok, _ = False, errors.append(str(exc))

        if not ok:
            result.results.append(ControlResult(
                change.control_id, ControlState.REFUSED,
                change.to_value, change.from_value,
                reason="; ".join(errors) or "the writer reported failure"))
            continue

        if change.control.requires_reboot:
            result.results.append(ControlResult(
                change.control_id, ControlState.APPLIED_PENDING_REBOOT,
                change.to_value, change.from_value,
                reason="takes effect after a restart"))
            continue

        observed = change.control.read()
        if observed == change.to_value:
            state, reason = ControlState.APPLIED_VERIFIED, ""
        else:
            state = ControlState.APPLIED_UNVERIFIED
            reason = ("the write reported success but the setting still reads "
                      f"{observed!r}. Something is overriding it: a Group "
                      "Policy, Tamper Protection, an MDM enrolment, or another "
                      "security product.")
        result.results.append(ControlResult(
            change.control_id, state, change.to_value, observed, reason))

    return result
```

- [ ] **Step 4: Run the tests**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_applier.py -v
```

Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/modules/security_dashboard/applier.py tests/test_security_applier.py
git commit -m "feat(security): a write is not believed until the reader confirms it"
```

---

### Task 12: The elevated helper, and a command line that survives a space

**Files:**
- Create: `src/modules/security_dashboard/elevated_helper.py`
- Modify: `src/main.py` (argv handling, before the `QApplication` is built)
- Test: `tests/test_security_elevated_helper.py`

**Interfaces:**
- Consumes: `apply_batch`, `load_catalog`.
- Produces: `write_batch_file(changeset, path)`, `run_from_file(batch_path, result_path) -> int`, `read_result_file(path) -> BatchResult`, `build_elevated_command(batch_path, result_path) -> Tuple[str, str]` returning `(executable, argument_string)`. Task 14 calls these.

- [ ] **Step 1: Write the failing test**

```python
"""One UAC prompt for the batch, and a command line that survives a space.

core.admin_utils.restart_as_admin builds its command line with
" ".join(sys.argv) and no quoting. The batch file lives under
C:\\Users\\<name>\\AppData\\Local\\... -- a path with a space in it is not
hypothetical here, it is the normal case.

A ShellExecuteW-launched process cannot have its stdout captured by the
parent, so the helper writes its own result file. This project has already
paid for that lesson once with elevated PowerShell.
"""
import json

from modules.security_dashboard.elevated_helper import (
    build_elevated_command, read_result_file, write_batch_file)


def test_the_command_line_quotes_a_path_containing_spaces():
    _, args = build_elevated_command(
        r"C:\Users\a b\AppData\batch.json", r"C:\Users\a b\result.json")
    assert '"C:\\Users\\a b\\AppData\\batch.json"' in args
    assert '"C:\\Users\\a b\\result.json"' in args


def test_a_batch_round_trips_through_the_file(tmp_path, monkeypatch):
    batch = tmp_path / "b.json"
    write_batch_file([("llmnr", False), ("wdigest", False)], str(batch))
    assert json.loads(batch.read_text())["changes"] == [
        ["llmnr", False], ["wdigest", False]]


def test_a_missing_result_file_is_reported_not_assumed(tmp_path):
    result = read_result_file(str(tmp_path / "nope.json"))
    assert result is None, "no result must mean unknown, never success"


def test_a_truncated_result_file_is_unknown_not_success(tmp_path):
    path = tmp_path / "r.json"
    path.write_text('{"results": [')
    assert read_result_file(str(path)) is None
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — no module `elevated_helper`.

- [ ] **Step 3: Implement**

```python
"""Run one batch elevated, and report back through a file.

ShellExecuteW cannot redirect the child's output, so the child writes its own
result file and the parent waits on it. `subprocess.list2cmdline` does the
quoting; " ".join(sys.argv) -- which core.admin_utils.restart_as_admin still
uses -- breaks on the first path containing a space.
"""
import json
import logging
import subprocess
import sys
from typing import Any, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

FLAG = "--apply-security-batch"
RESULT_FLAG = "--result"


def build_elevated_command(batch_path: str, result_path: str) -> Tuple[str, str]:
    """(executable, argument string) for ShellExecuteW(..., "runas", ...)."""
    args: List[str] = []
    if not getattr(sys, "frozen", False):
        args.append(sys.argv[0])        # the script; the frozen exe needs none
    args += [FLAG, batch_path, RESULT_FLAG, result_path]
    return sys.executable, subprocess.list2cmdline(args)


def write_batch_file(changes: Sequence[Tuple[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"version": 1, "changes": [list(c) for c in changes]}, handle)


def read_result_file(path: str) -> Optional[dict]:
    """The helper's report, or None if it never wrote one.

    None means the outcome is UNKNOWN. The caller re-reads the controls and
    shows what the machine actually says; it must never treat a missing
    result as either success or failure.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("no usable result file at %s: %s", path, exc)
        return None


def run_from_file(batch_path: str, result_path: str) -> int:
    """Entry point for the elevated child process."""
    from core.backup_service import BackupService
    from modules.tweaks.tweak_engine import TweakEngine

    from .applier import apply_batch
    from .catalog import load_catalog
    from .staging import ChangeSet

    with open(batch_path, encoding="utf-8") as handle:
        batch = json.load(handle)

    catalog = load_catalog()
    changeset = ChangeSet()
    for control_id, desired in batch["changes"]:
        control = catalog.get(control_id)
        if control is not None:
            changeset.add(control, desired)

    from app import _get_app_data_dir   # src/app.py:18 -- there is no core/paths.py
    backup = BackupService(data_dir=_get_app_data_dir())
    try:
        result = apply_batch(changeset, TweakEngine(backup), backup)
        payload = {
            "version": 1,
            "rp_id": result.rp_id,
            "results": [
                {"control_id": r.control_id, "state": r.state.value,
                 "requested": r.requested, "observed": r.observed,
                 "reason": r.reason}
                for r in result.results],
        }
    finally:
        backup.close()

    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return 0
```

The only other construction site is `src/app.py:93`, `BackupService(data_dir=self._app_data_dir)`, where `_app_data_dir` comes from `_get_app_data_dir()` at `src/app.py:18`. The helper must resolve the same directory or it will write its records to a store the pane never reads.

- [ ] **Step 4: Wire the entry point into `src/main.py`**

Before any Qt object is created — the helper must not build a `QApplication`:

```python
if __name__ == "__main__":
    if "--apply-security-batch" in sys.argv:
        from modules.security_dashboard.elevated_helper import run_from_file
        idx = sys.argv.index("--apply-security-batch")
        batch = sys.argv[idx + 1]
        result = sys.argv[sys.argv.index("--result") + 1]
        sys.exit(run_from_file(batch, result))
```

- [ ] **Step 5: Run tests and commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_elevated_helper.py -v
.\.venv\Scripts\python.exe -m pytest -q
git add src/modules/security_dashboard/elevated_helper.py src/main.py tests/test_security_elevated_helper.py
git commit -m "feat(security): one UAC prompt per batch, through a helper that reports back"
```

---

### Task 13: Revert through the recorded prior value

**Files:**
- Create: `src/modules/security_dashboard/reverting.py`
- Test: `tests/test_security_revert.py`

**Interfaces:**
- Consumes: `BackupService.revert_step` / `revert_tweak` / `restore_point`, `load_catalog`.
- Produces: `revert_control(control_id, backup, catalog) -> ControlResult`, `revert_batch(rp_id, backup, catalog) -> BatchResult`. Both verify afterwards.

- [ ] **Step 1: Write the failing test**

```python
"""Revert restores what was recorded, and is then checked like any other write.

_ToggleCard.configure defaulted revert_fn to toggle_fn, so Revert called the
setter with the opposite argument -- a guess about the previous value, and
simply wrong for anything multi-valued. BackupService already records the real
before_value and deletes a value that did not exist before.
"""
from modules.security_dashboard.catalog.model import Category, ControlState, SecurityControl
from modules.security_dashboard.reverting import revert_control


class _Backup:
    def __init__(self, ok=True): self.ok, self.reverted = ok, []
    def revert_tweak(self, tweak_id):
        self.reverted.append(tweak_id)
        return type("R", (), {"success": self.ok, "partial": False,
                              "failed_steps": [], "errors": ["denied"]})()


def _control(cid, readings):
    return SecurityControl(
        id=cid, title=cid, category=Category.SERVICES, description="d",
        why_it_matters="w",
        reader=lambda: {"available": True, "enabled": readings.pop(0)},
        on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                   "data": 1, "kind": "DWORD"},))


def test_revert_delegates_to_the_recorded_steps():
    backup = _Backup()
    revert_control("llmnr", backup, {"llmnr": _control("llmnr", [True])})
    assert backup.reverted == ["llmnr"]


def test_a_revert_that_did_not_take_is_reported_not_assumed():
    catalog = {"llmnr": _control("llmnr", [False])}
    result = revert_control("llmnr", _Backup(ok=False), catalog)
    assert result.state is ControlState.REFUSED
```

- [ ] **Step 2: Run to verify it fails, then implement**

```python
"""Revert is a write, and gets the same verification as any other."""
from typing import Dict

from .applier import BatchResult, ControlResult
from .catalog.model import ControlState, SecurityControl


def revert_control(control_id: str, backup, catalog: Dict[str, SecurityControl]
                   ) -> ControlResult:
    outcome = backup.revert_tweak(control_id)
    control = catalog.get(control_id)
    observed = control.read() if control else None
    if not outcome.success:
        return ControlResult(
            control_id, ControlState.REFUSED, None, observed,
            reason="; ".join(getattr(outcome, "errors", [])) or "revert failed")
    return ControlResult(control_id, ControlState.APPLIED_VERIFIED, None, observed)


def revert_batch(rp_id: str, backup, catalog: Dict[str, SecurityControl]
                 ) -> BatchResult:
    outcome = backup.restore_point(rp_id)
    result = BatchResult(rp_id=rp_id)
    for control_id in getattr(outcome, "reverted_ids", []) or []:
        result.results.append(revert_control(control_id, backup, catalog))
    return result
```

`RestoreResult` is `(success, partial, failed_steps, errors)` — it carries **no** list of what was reverted, so `revert_batch` cannot verify anything without one. Add `reverted_ids: List[str]` to the dataclass (last, with `field(default_factory=list)`) and populate it in `_revert_steps`. Guessing which controls a restore point covered is not an option: a batch revert that cannot name what it reverted cannot be verified.

- [ ] **Step 3: Run tests and commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_revert.py -q
git add src/modules/security_dashboard/reverting.py tests/test_security_revert.py
git commit -m "feat(security): revert restores the recorded value instead of guessing the opposite"
```

---

# Phase 4 — The pane

---

### Task 14: `ControlCard`, rendered from a catalog entry

**Files:**
- Modify: `src/modules/security_dashboard/security_module.py`
- Test: `tests/test_security_control_card.py`

**Interfaces:**
- Consumes: `SecurityControl`, `ControlState`.
- Produces: `ControlCard(control, parent=None)` with `set_reading(value)`, `set_staged(to_value)`, `clear_staged()`, `set_result(ControlResult)`, and signal `staged = pyqtSignal(str, object)`. Task 15 lays these out.

- [ ] **Step 1: Write the failing test**

```python
"""A card is a rendering of a catalog entry, not a hand-wired widget."""
import pytest

from modules.security_dashboard.catalog.model import Category, SecurityControl
from modules.security_dashboard.security_module import ControlCard


def _control(**over):
    base = dict(id="llmnr", title="LLMNR", category=Category.FIREWALL_NETWORK,
                description="d", why_it_matters="w",
                reader=lambda: {"available": True, "enabled": True},
                on_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                           "data": 1, "kind": "DWORD"},),
                off_steps=({"type": "registry", "key": "HKLM\\A", "value": "V",
                            "data": 0, "kind": "DWORD"},))
    base.update(over)
    return SecurityControl(**base)


def test_a_read_only_control_offers_no_toggle_and_shows_the_reason(qapp):
    card = ControlCard(_control(on_steps=(), off_steps=(),
                                read_only_reason="TPM presence is hardware"))
    assert not card.toggle_button.isVisible() or not card.toggle_button.isEnabled()
    assert "hardware" in card.reason_label.text()


def test_a_control_that_could_not_be_read_does_not_render_as_off(qapp):
    """A refused read is not an unset value."""
    card = ControlCard(_control())
    card.set_reading(None)
    assert "Unknown" in card.status_badge.text()
    assert "Off" not in card.status_badge.text()


def test_toggling_emits_a_staging_request_and_writes_nothing(qapp):
    card = ControlCard(_control())
    card.set_reading(True)
    seen = []
    card.staged.connect(lambda cid, value: seen.append((cid, value)))
    card.toggle_button.click()
    assert seen == [("llmnr", False)]


def test_a_staged_card_says_what_it_will_become(qapp):
    card = ControlCard(_control())
    card.set_reading(True)
    card.set_staged(False)
    assert "will be" in card.staged_label.text().lower()


def test_no_colour_is_hardcoded_in_the_card(qapp):
    """40 hardcoded hex colours is how 13 of 34 panes rendered dark under the
    light theme. The #999 description text measured ~2.8:1 on white."""
    import inspect
    source = inspect.getsource(ControlCard)
    assert "#999" not in source and "#3c3c3c" not in source
```

- [ ] **Step 2: Run to verify it fails, then implement `ControlCard`**

Replace `_ToggleCard`. Colours come from `core/semantic_colors.py` — `semantic(meaning)` resolves a token against the current theme, and `set_theme` / `current_theme` are how the pane follows a theme change. No hex literals. Requirements the tests encode:

- `set_reading(None)` renders "Unknown", never "Off".
- A control with `read_only_reason` shows it and offers no working toggle.
- `toggle_button.click()` emits `staged` and touches nothing else.
- `set_result` renders the four `ControlState`s distinctly, with `APPLIED_UNVERIFIED` in the theme's warning colour showing observed beside requested.

- [ ] **Step 3: Run tests and commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_control_card.py -v
git add src/modules/security_dashboard/security_module.py tests/test_security_control_card.py
git commit -m "feat(security): the card renders a catalog entry, including why it cannot be changed"
```

---

### Task 15: Tabs, the filter bar, and a read strategy that does not repeat the Overview defect

**Files:**
- Modify: `src/modules/security_dashboard/security_module.py`
- Test: `tests/test_security_tabs_and_filter.py`

**Interfaces:**
- Consumes: `load_catalog`, `ControlCard`, `snapshots.invalidate`.
- Produces: `SecurityDashboardModule.filter_controls(text, only_problems, only_changed, only_actionable) -> List[SecurityControl]`, and per-tab lazy loading.

- [ ] **Step 1: Write the failing test**

```python
"""Ten tabs, one filter, and no sweep the pane did not ask for.

Measured at branch point: 57 of the readers launch PowerShell at 0.54s each.
Reading every control on tab open is the Overview 37.3s defect at ten times
the scale, so a tab reads only its own controls and only when shown, and
refresh is a button, never a timer.
"""
import pytest

from modules.security_dashboard.security_module import SecurityDashboardModule


@pytest.fixture
def module(qapp):
    mod = SecurityDashboardModule()
    mod.on_start(None)
    widget = mod.create_widget()
    mod._held = widget          # dropping it deletes the Qt children
    yield mod
    mod.on_stop()


def test_the_grab_bag_tabs_are_gone(module):
    titles = [module._tabs.tabText(i) for i in range(module._tabs.count())]
    assert "Advanced" not in titles and "Controls" not in titles


def test_filtering_matches_description_not_only_title(module):
    hits = module.filter_controls("multicast")
    assert any(c.id == "llmnr" for c in hits)


def test_only_actionable_hides_the_read_only_controls(module):
    hits = module.filter_controls("", only_actionable=True)
    assert all(c.writable for c in hits)


def test_opening_a_tab_reads_only_that_tabs_controls(module, monkeypatch):
    read = []
    for control in module.catalog.values():
        object.__setattr__(control, "reader",
                           lambda c=control: read.append(c.id) or {"available": True,
                                                                   "enabled": True})
    module.show_category_tab("Services")
    assert read, "the tab read nothing"
    assert all(module.catalog[cid].category.value == "Services" for cid in read)


def test_the_pane_starts_no_auto_refresh_timer(module):
    """The Overview pane ran a 30s timer against a 37.3s sweep and relaunched
    the unfinished one, so it sat on 'Loading...' for over half a minute."""
    from PyQt6.QtCore import QTimer
    timers = module._held.findChildren(QTimer)
    assert not [t for t in timers if t.isActive()]
```

- [ ] **Step 2: Run to verify it fails, then implement**

- Build tabs from `Category`, plus Overview, History and Events.
- `filter_controls` matches `title`, `description` and `why_it_matters`, case-insensitively.
- Each tab reads its own controls in a `Worker` when first shown; the result is cached with an "as of" timestamp shown in the tab header. **Refresh is a button and calls `snapshots.invalidate()` first.** No `QTimer`.
- Guard re-entry: a tab whose read is still in flight does not start a second one — the same guard `test_security_overview_inflight.py` already asserts for Overview.

- [ ] **Step 3: Run tests and commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_tabs_and_filter.py -v
git add src/modules/security_dashboard/security_module.py tests/test_security_tabs_and_filter.py
git commit -m "feat(security): themed tabs, one filter bar, and no timer racing an unfinished sweep"
```

---

### Task 16: The pending bar, the review dialog and the result report

**Files:**
- Modify: `src/modules/security_dashboard/security_module.py`
- Test: `tests/test_security_pending_and_report.py`

**Interfaces:**
- Consumes: `ChangeSet`, `apply_batch`, `elevated_helper`, `BatchResult`.
- Produces: `PendingBar`, `ReviewDialog(changeset)`, `ResultDialog(batch_result)`.

- [ ] **Step 1: Write the failing test**

```python
"""Nothing applies until Apply, and the report tells the truth about what did."""
import pytest

from modules.security_dashboard.applier import BatchResult, ControlResult
from modules.security_dashboard.catalog.model import ControlState
from modules.security_dashboard.security_module import ResultDialog, ReviewDialog


def test_the_review_shows_the_literal_steps_that_will_run(qapp, staged_changeset):
    dialog = ReviewDialog(staged_changeset)
    text = dialog.details_text()
    assert "EnableMulticast" in text, "the user must see what will be written"


def test_a_partly_successful_batch_does_not_look_like_a_successful_one(qapp):
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult("a", ControlState.APPLIED_VERIFIED, False, False),
        ControlResult("b", ControlState.REFUSED, False, True, "Access is denied."),
        ControlResult("c", ControlState.APPLIED_UNVERIFIED, False, True,
                      "still reads True"),
    ])
    dialog = ResultDialog(result)
    summary = dialog.summary_text()
    assert "1" in summary and "3" in summary
    assert "Access is denied" in dialog.details_text()


def test_an_unverified_control_shows_both_values(qapp):
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult("c", ControlState.APPLIED_UNVERIFIED, False, True, "r")])
    text = ResultDialog(result).details_text()
    assert "False" in text and "True" in text


def test_a_reboot_batch_asks_once_at_the_end_not_once_per_control(qapp):
    result = BatchResult(rp_id="rp-1", results=[
        ControlResult(cid, ControlState.APPLIED_PENDING_REBOOT, False, True, "")
        for cid in ("a", "b", "c")])
    dialog = ResultDialog(result)
    assert dialog.reboot_prompts() == 1
```

- [ ] **Step 2: Implement, run, commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_pending_and_report.py -v
git add src/modules/security_dashboard/security_module.py tests/test_security_pending_and_report.py
git commit -m "feat(security): review before applying, and a report that distinguishes 9 of 12 from 12"
```

---

### Task 17: History, baselines and profiles

**Files:**
- Create: `src/modules/security_dashboard/profile.py`, `catalog/baselines/*.json`
- Modify: `src/modules/security_dashboard/security_module.py`
- Test: `tests/test_security_profile.py`, `tests/test_security_baselines.py`

**Interfaces:**
- Consumes: `BackupService.list_restore_points`, `diff_against`, `PresetManager`.
- Produces: `export_profile(catalog) -> dict`, `import_profile(dict, catalog) -> ChangeSet`, `load_baseline(name) -> Dict[str, Any]`, and a History tab.

- [ ] **Step 1: Write the failing tests**

```python
"""A baseline stages a diff and says what it skips; a profile does the same."""
import json

import pytest

from modules.security_dashboard.profile import export_profile, import_profile


def test_an_exported_profile_records_the_build_it_came_from(catalog):
    data = export_profile(catalog)
    assert data["os_build"] and data["app_version"]


def test_importing_stages_only_what_differs(catalog):
    data = export_profile(catalog)
    assert len(import_profile(data, catalog)) == 0, (
        "exporting and reimporting the same machine must stage nothing")


def test_an_unreadable_control_is_omitted_from_the_export(catalog_with_unreadable):
    """Exporting None as a value would import as 'set it to nothing'."""
    data = export_profile(catalog_with_unreadable)
    assert "unreadable_one" not in data["controls"]


def test_a_baseline_reports_what_it_will_skip_and_why(catalog):
    from modules.security_dashboard.profile import plan_baseline
    plan = plan_baseline("recommended", catalog)
    assert all(entry["reason"] for entry in plan["skipped"])
```

- [ ] **Step 2: Implement**

- `export_profile` omits controls whose `read()` is `None` — exporting "could not read" as a value would import as an instruction.
- `plan_baseline` returns `{"staged": ChangeSet, "skipped": [{"id", "reason"}]}` with reasons drawn from: already compliant, no writer (`read_only_reason`), could not read, requires reboot.
- The History tab renders `list_restore_points()` filtered to `module == "Security Dashboard"`, with per-step detail and Revert buttons calling Task 13.
- Write `recommended.json` from the catalog's own `desired` fields; `hardened.json` and `developer.json` by hand.

- [ ] **Step 3: Run tests and commit**

```
.\.venv\Scripts\python.exe -m pytest tests/test_security_profile.py tests/test_security_baselines.py -v
.\.venv\Scripts\python.exe -m pytest -q
git add src/modules/security_dashboard tests/test_security_profile.py tests/test_security_baselines.py
git commit -m "feat(security): baselines, profiles, and a history of what this app changed"
```

---

# Phase 5 — The part that actually proves it works

---

### Task 18: Drive the real catalog against this machine

A green suite has proved nothing here eight times. Every serious defect in this project was found by running the real thing and disbelieving a plausible number, or by rendering the pane and looking at it.

**Files:**
- Create: `tools/security_catalog_check.py`
- Modify: whatever it finds

- [ ] **Step 1: Write the harness**

Reads every control in the real catalog, reports per control: the value, the time the read took, and whether it was refused. Prints a summary: total controls, how many read successfully, how many were refused with reasons grouped, and total wall clock. Modelled on `tools/admin_requirement_audit.py`, and like it, **it never presses a button** — `--apply` is a separate opt-in flag naming one control id.

- [ ] **Step 2: Run it unelevated, then elevated, and diff**

`Start-Process -Verb RunAs` cannot redirect output — write a wrapper `.ps1` that redirects to a file itself, then read the file.

```
.\.venv\Scripts\python.exe tools\security_catalog_check.py unelevated.json
# then via the elevating wrapper:
.\.venv\Scripts\python.exe tools\security_catalog_check.py --compare unelevated.json elevated.json
```

A control whose unelevated answer matches its elevated one does not need admin to be **read**, and its `requires_admin` should reflect that — the flag gates the write, not the read.

- [ ] **Step 3: Answer these, with numbers, before claiming anything works**

- How many of the controls can this machine actually answer? Anything reading "Unknown" is either a defect or an honest refusal — say which, per control.
- How long does a full catalog read take, and how long does the slowest single tab take? If any tab exceeds ~3 s, say which readers are responsible.
- Which controls disagree between elevated and unelevated? Each one is either a `requires_admin` flag that is wrong or a refusal being read as a value.

- [ ] **Step 4: Round-trip one low-risk control on this machine**

Pick `llmnr`. Read it, note the raw registry value with `winreg` directly. Stage, apply, verify. **Read the registry value directly again** — not through the reader you just used to decide. Revert. Verify. Read directly a third time and confirm it is back to exactly what it was, including absent if it was absent.

- [ ] **Step 5: Render the pane and look at it**

In **both** themes, at a small window and a large one, in these five states: nothing staged; several staged; mid-apply; a report containing a refusal and an unverified control; and the History tab with real entries. Measure column widths with `fontMetrics().horizontalAdvance(item.text())` against the real catalog — the Firewall table's guessed defaults clipped 393 of 544 real rows.

Watch for the layout trap from `d57cdf2`: a new widget added to a `QVBoxLayout` with no stretch factor and nothing `Expanding` gets an equal share of the surplus. The pending bar is exactly that shape.

- [ ] **Step 6: Read the session log**

```
.\.venv\Scripts\python.exe src\main.py
```

Then read the newest `VRK_*.log` in the repo root. Zero WARNING and zero ERROR lines, or explain each one. That log is where the 2026-08-21 and 2026-08-22 defects came from.

- [ ] **Step 7: Full suite, cold, and commit the findings**

```
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Get-ChildItem -Recurse -Directory -Filter __pycache__).FullName
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: green, 4 skipped, **1 warning** (the pre-existing `PytestCollectionWarning`). Any new warning is a cold-compile `SyntaxWarning` you introduced — fix it, do not cache it away.

```bash
git add tools/security_catalog_check.py
git commit -m "test(security): drive the real catalog against this machine"
```

---

## Self-Review

**Spec coverage.** §1.3 A → Task 1. §1.3 B → Task 2. §1.3 C → Tasks 13, 14. §2.1 model → Task 4. §2.1 read-only invariant → Tasks 4, 5. §2.2 writer selection → Tasks 6-8, 10. §3.1 staging → Task 9. §3.2 apply/elevation → Tasks 11, 12. §3.3 verify → Task 11. §3.4 report → Task 16. §4.1 revert → Task 13. §4.2 history → Task 17. §4.3 baselines → Task 17. §4.4 profiles → Task 17. §5.1 tabs → Task 15. §5.2 filter bar → Task 15. §5.3 Overview → Task 15. §5.4 CVE → Task 6. §5.5 theme → Task 14. §6 error handling → Tasks 11, 12, 14. §7.1-7.3 → Tasks 4, 5, 9, 11. §7.4 → Task 18.

**Gap found and closed:** the spec's performance implications were not a spec section at all — they emerged from measuring `_ps` at 0.54 s × 57 readers. Task 3 was added ahead of the catalog because populating 155 controls on top of a read path that costs 31 s would bake the Overview defect into the design.

**Type consistency.** `ControlState` (Task 4) is used unchanged in Tasks 11, 13, 14, 16. `ControlResult`/`BatchResult` (Task 11) are consumed by Tasks 13, 16. `ChangeSet.add(control, to_value)` (Task 9) is called the same way in Tasks 10, 11, 12, 17. `PendingChange.resolved_steps()` (Task 10) is what Task 11 applies. `snapshots.invalidate()` (Task 3) is called by Task 15's Refresh.

**Placeholder scan.** No "TBD"/"TODO"/"handle edge cases". Two tasks deliberately do not enumerate every entry — Tasks 6-8, where the catalog holds ~155 controls. That is not a placeholder: Task 5's binding test makes completeness machine-checkable, so each of those tasks has a mechanical pass/fail condition and worked examples of every shape it needs.
