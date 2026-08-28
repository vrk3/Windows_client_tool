"""A command step that failed must be able to say so.

_apply_command and _apply_script ran with check=False, capture_output=True and
then read neither the return code nor the output, building a StepRecord either
way. Windows admin commands exit 0 while refusing and write the reason to
stdout -- netsh and dism both do -- so "applied" meant "we ran something".

Capturing rc/stdout/stderr onto the StepRecord fixes nothing on its own if
nothing reads them: a refused command must also FAIL the step, so that
apply_tweak's existing except-path reports it through on_error instead of
returning True. That means every scenario below where a command is refused
(nonzero exit, or a zero-exit refusal marker like netsh's "No rules match")
now raises StepRefused rather than returning a StepRecord normally --
StepRefused carries the built StepRecord (with its rc/stdout/stderr already
captured) as `.record`, which is how the tests below verify the capture even
on the raising path.
"""
import pytest

from core.backup_service import StepRecord
from modules.tweaks.tweak_engine import StepRefused, TweakEngine


class _FakeBackup:
    def record_steps(self, *a, **k): pass
    def backup_registry_key(self, *a, **k): pass


@pytest.fixture
def engine():
    return TweakEngine(_FakeBackup())


def test_a_failing_command_records_its_return_code_and_output(engine):
    with pytest.raises(StepRefused) as exc_info:
        engine._apply_command(
            {"type": "command", "cmd": "cmd /c echo refused by policy& exit /b 5"})
    record = exc_info.value.record
    assert record.rc == 5
    assert "refused by policy" in record.stdout


def test_a_command_that_exits_zero_while_complaining_keeps_its_stdout(engine):
    """netsh and dism both do exactly this."""
    with pytest.raises(StepRefused) as exc_info:
        engine._apply_command(
            {"type": "command", "cmd": "cmd /c echo No rules match the specified criteria."})
    record = exc_info.value.record
    assert record.rc == 0
    assert "No rules match" in record.stdout


def test_a_script_step_records_stderr_too(engine):
    with pytest.raises(StepRefused) as exc_info:
        engine._apply_script(
            {"type": "script", "command": "cmd /c echo boom 1>&2& exit /b 1"})
    record = exc_info.value.record
    assert record.rc == 1
    assert "boom" in record.stderr


def test_a_successful_command_returns_its_step_record_normally(engine):
    """No refusal, no exception -- the capture is there for a plain success too."""
    record = engine._apply_command({"type": "command", "cmd": "cmd /c echo done"})
    assert isinstance(record, StepRecord)
    assert record.rc == 0
    assert "done" in record.stdout


# -- Ruling 1 addendum: a refused step must fail the tweak, not just record itself --

def test_a_refused_command_fails_the_tweak_and_reports_the_reason(engine):
    """The reason must reach on_error. Before this task apply_tweak returns True here."""
    errors = []
    ok = engine.apply_tweak(
        {"id": "t", "steps": [{"type": "command",
                               "cmd": "cmd /c echo Access is denied.& exit /b 1"}]},
        "rp-1", on_error=errors.append)
    assert ok is False
    assert any("Access is denied" in e for e in errors)


def test_a_command_that_exits_zero_while_refusing_still_fails_the_tweak(engine):
    """netsh exits 0 saying 'No rules match'; dism exits 740 with its
    complaint on stdout. rc alone decides nothing."""
    errors = []
    ok = engine.apply_tweak(
        {"id": "t", "steps": [{"type": "command",
                               "cmd": "cmd /c echo No rules match the specified criteria."}]},
        "rp-1", on_error=errors.append)
    assert ok is False


def test_a_command_that_succeeded_is_not_reported_as_refused(engine):
    ok = engine.apply_tweak(
        {"id": "t", "steps": [{"type": "command", "cmd": "cmd /c echo done"}]},
        "rp-1")
    assert ok is True
