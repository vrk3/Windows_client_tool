"""Spec 8.4: scheduled scans.

schtasks is never actually invoked here. A test suite that registers real
scheduled tasks leaves them behind on the machine that ran it.
"""
import sys


from modules.treesize.actions import scheduler


def _fake_run(result_code=0, output=""):
    calls = []

    def run(args):
        calls.append(args)
        return result_code, output

    return run, calls


def test_the_target_is_never_handed_to_a_shell(monkeypatch):
    """A scan target is user data; it goes in an argument list, not a string."""
    run, calls = _fake_run()
    monkeypatch.setattr(scheduler, "_run", run)
    scheduler.schedule("C:\\Users\\me & co", "DAILY")
    assert isinstance(calls[0], list)
    assert calls[0][0] == "schtasks"


def test_scheduling_passes_the_frequency_and_time(monkeypatch):
    run, calls = _fake_run()
    monkeypatch.setattr(scheduler, "_run", run)
    ok, message = scheduler.schedule("C:\\", "WEEKLY", at="06:30")
    assert ok
    assert "/SC" in calls[0] and "WEEKLY" in calls[0]
    assert "06:30" in calls[0]
    assert "weekly" in message


def test_an_unsupported_frequency_is_refused(monkeypatch):
    run, calls = _fake_run()
    monkeypatch.setattr(scheduler, "_run", run)
    ok, message = scheduler.schedule("C:\\", "HOURLY")
    assert not ok
    assert not calls, "nothing should be executed for a bad frequency"


def test_an_empty_target_is_refused(monkeypatch):
    run, calls = _fake_run()
    monkeypatch.setattr(scheduler, "_run", run)
    assert scheduler.schedule("   ", "DAILY")[0] is False
    assert not calls


def test_access_denied_explains_what_to_do(monkeypatch):
    run, _calls = _fake_run(1, "ERROR: Access is denied.")
    monkeypatch.setattr(scheduler, "_run", run)
    ok, message = scheduler.schedule("C:\\", "DAILY")
    assert not ok
    assert "administrator" in message


def test_other_failures_report_the_output(monkeypatch):
    run, _calls = _fake_run(1, "ERROR: something specific went wrong")
    monkeypatch.setattr(scheduler, "_run", run)
    ok, message = scheduler.schedule("C:\\", "DAILY")
    assert not ok
    assert "something specific" in message


def test_removing_a_task_that_is_not_there_is_not_an_error(monkeypatch):
    run, _calls = _fake_run(1, "ERROR: The system cannot find the file specified.")
    monkeypatch.setattr(scheduler, "_run", run)
    ok, message = scheduler.unschedule()
    assert ok
    assert "no scheduled scan" in message.lower()


def test_removing_an_existing_task_reports_success(monkeypatch):
    run, calls = _fake_run(0, "SUCCESS")
    monkeypatch.setattr(scheduler, "_run", run)
    ok, _message = scheduler.unschedule()
    assert ok
    assert "/Delete" in calls[0]


def test_is_scheduled_reflects_the_query_result(monkeypatch):
    monkeypatch.setattr(scheduler, "_run", _fake_run(0)[0])
    assert scheduler.is_scheduled()
    monkeypatch.setattr(scheduler, "_run", _fake_run(1)[0])
    assert not scheduler.is_scheduled()


def test_the_frozen_build_schedules_itself_not_python(monkeypatch):
    """A task pointing at python.exe would not exist on a machine that only
    has the portable build."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", "C:\\apps\\WinClientTool.exe")
    command = scheduler.command_for("C:\\")
    assert command[0].endswith("WinClientTool.exe")
    assert "--treesize-scan" in command
