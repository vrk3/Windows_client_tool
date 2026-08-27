"""The gpupdate wrapper, against the output shapes gpupdate really produces.

Every test here guards something this codebase has already been burned by:
a Windows admin command exiting 0 while refusing to work, a complaint printed
to stdout instead of stderr, a half-done run reported as a clean one, and a
pane that shows nothing until a long command finishes.

Nothing here runs a real `gpupdate`. `/force` reapplies every policy setting
on the machine and takes many seconds; a test suite has no business doing
that. `subprocess.Popen` is replaced wholesale by `FakePopen`.
"""
import subprocess
import threading
import time

import pytest

from modules.gpresult import gpupdate
from modules.gpresult.gpupdate import (
    GpupdateOptions, GpupdateResult, build_command, parse_output, run_gpupdate,
    HALF_FAILED, HALF_NOT_REQUESTED, HALF_SUCCESS, HALF_UNKNOWN,
    STATUS_CANCELLED, STATUS_ERROR, STATUS_FAILURE, STATUS_PARTIAL,
    STATUS_SUCCESS, STATUS_TIMEOUT, STATUS_UNKNOWN,
    TARGET_ALL, TARGET_COMPUTER, TARGET_USER,
)

# ---------------------------------------------------------------------------
# Captured output shapes. gpupdate prints its verdict as prose, and both the
# success and the failure sentences land on stdout.
# ---------------------------------------------------------------------------

BOTH_OK = [
    "Updating policy...",
    "",
    "Computer Policy update has completed successfully.",
    "User Policy update has completed successfully.",
    "",
]

# The everyday unelevated run: the computer half is refused, the user half
# works, and the exit code is 0 the whole time.
COMPUTER_REFUSED = [
    "Updating policy...",
    "",
    "Computer policy could not be updated successfully. The following errors "
    "were encountered:",
    "",
    "The processing of Group Policy failed. Windows could not apply the "
    "registry-based policy settings for the Group Policy object LocalGPO.",
    "",
    "User Policy update has completed successfully.",
    "",
    "To diagnose the failure, review the event log or run GPRESULT /H "
    "GPReport.html from the command line to access information about Group "
    "Policy results.",
]

BOTH_FAILED = [
    "Updating policy...",
    "",
    "Computer policy could not be updated successfully. The following errors "
    "were encountered:",
    "",
    "The processing of Group Policy failed. Access is denied.",
    "",
    "User policy could not be updated successfully. The following errors "
    "were encountered:",
    "",
    "The processing of Group Policy failed. Access is denied.",
]

LOGOFF_WANTED = [
    "Updating policy...",
    "",
    "Computer Policy update has completed successfully.",
    "User Policy update has completed successfully.",
    "",
    "The following settings require a logoff for the changes to take effect:",
    "    Folder Redirection",
    "",
    "Do you want to log off now? (Y/N)",
]

REBOOT_WANTED = [
    "Updating policy...",
    "",
    "Computer Policy update has completed successfully.",
    "User Policy update has completed successfully.",
    "",
    "A restart is required for some settings to take effect.",
    "Do you want to restart your computer now? (Y/N)",
]


class FakePopen:
    """Stands in for a running gpupdate.

    Records terminate/kill so cancellation can be asserted on, and can pace
    its lines so the streaming and cancel tests are not racing a real process.
    """

    instances = []

    def __init__(self, cmd, stdout=None, stderr=None, stdin=None,
                 text=None, encoding=None, errors=None, creationflags=0,
                 out_lines=(), err_lines=(), returncode=0, per_line_delay=0.0,
                 hang=False):
        self.cmd = cmd
        self.kwargs = {
            "stdout": stdout, "stderr": stderr, "stdin": stdin,
            "text": text, "encoding": encoding, "errors": errors,
            "creationflags": creationflags,
        }
        self._out_lines = list(out_lines)
        self._err_lines = list(err_lines)
        self._final_returncode = returncode
        self._per_line_delay = per_line_delay
        self._hang = hang
        self._stopped = threading.Event()
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.stdout = self._iter_out()
        self.stderr = iter([line + "\n" for line in self._err_lines])
        FakePopen.instances.append(self)

    def _iter_out(self):
        for line in self._out_lines:
            if self._per_line_delay:
                time.sleep(self._per_line_delay)
            if self._stopped.is_set():
                return
            yield line + "\n"
        while self._hang and not self._stopped.wait(0.02):
            # A gpupdate that has printed its banner and gone quiet, which is
            # exactly when a user reaches for Cancel.
            pass

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self._hang and not self._stopped.is_set():
            raise subprocess.TimeoutExpired(self.cmd, timeout or 0)
        if self.returncode is None:
            self.returncode = self._final_returncode
        return self.returncode

    def terminate(self):
        self.terminated = True
        self._stopped.set()
        self.returncode = 1

    def kill(self):
        self.killed = True
        self._stopped.set()
        self.returncode = 1


@pytest.fixture(autouse=True)
def _clear_fakes():
    FakePopen.instances.clear()
    yield
    FakePopen.instances.clear()


def install_fake(monkeypatch, **fake_kwargs):
    """Replace subprocess.Popen so no real gpupdate is ever launched."""
    def factory(cmd, **kwargs):
        return FakePopen(cmd, **dict(kwargs, **fake_kwargs))
    monkeypatch.setattr(subprocess, "Popen", factory)


def opts(**kwargs):
    kwargs.setdefault("timeout", 10)
    return GpupdateOptions(**kwargs)


# ---------------------------------------------------------------------------
# Command construction
# ---------------------------------------------------------------------------

def test_both_targets_pass_no_target_switch_because_that_is_the_default():
    assert build_command(opts(target=TARGET_ALL)) == ["gpupdate"]


def test_user_only_asks_for_target_user():
    assert build_command(opts(target=TARGET_USER)) == ["gpupdate", "/target:user"]


def test_computer_only_asks_for_target_computer():
    assert build_command(opts(target=TARGET_COMPUTER)) == [
        "gpupdate", "/target:computer"]


def test_force_is_appended_when_requested():
    assert build_command(opts(target=TARGET_USER, force=True)) == [
        "gpupdate", "/target:user", "/force"]


def test_logoff_and_boot_are_never_passed_because_they_perform_the_action():
    # /logoff and /boot do not suppress gpupdate's question, they carry it
    # out. Logging the user off or rebooting is not this module's decision.
    for target in (TARGET_ALL, TARGET_USER, TARGET_COMPUTER):
        cmd = build_command(opts(target=target, force=True))
        joined = " ".join(cmd).lower()
        assert "/logoff" not in joined
        assert "/boot" not in joined


def test_wait_is_omitted_unless_asked_for():
    assert "/wait:0" not in build_command(opts())
    assert build_command(opts(wait=30))[-1] == "/wait:30"


def test_an_unknown_target_is_rejected_rather_than_silently_meaning_both():
    with pytest.raises(ValueError):
        build_command(opts(target="machine"))


# ---------------------------------------------------------------------------
# The verdict comes from the output text
# ---------------------------------------------------------------------------

def test_both_halves_completing_is_a_success():
    result = parse_output(BOTH_OK, opts(), elevated=True)
    assert result.status == STATUS_SUCCESS
    assert result.ok
    assert result.computer == HALF_SUCCESS
    assert result.user == HALF_SUCCESS


def test_a_refused_computer_half_beside_a_working_user_half_is_partial():
    result = parse_output(COMPUTER_REFUSED, opts(), elevated=False)
    assert result.status == STATUS_PARTIAL
    assert not result.ok
    assert result.computer == HALF_FAILED
    assert result.user == HALF_SUCCESS


def test_a_partial_run_is_not_reported_as_a_success_or_as_a_failure():
    result = parse_output(COMPUTER_REFUSED, opts(), elevated=False)
    assert result.status not in (STATUS_SUCCESS, STATUS_FAILURE)
    assert "refreshed" in result.summary.lower()
    assert "did not" in result.summary.lower()


def test_both_halves_failing_is_a_failure():
    result = parse_output(BOTH_FAILED, opts(), elevated=True)
    assert result.status == STATUS_FAILURE
    assert result.computer == HALF_FAILED
    assert result.user == HALF_FAILED


def test_output_that_says_nothing_recognisable_is_unknown_not_success():
    result = parse_output(["Updating policy...", ""], opts(), elevated=True)
    assert result.status == STATUS_UNKNOWN
    assert not result.ok


def test_a_half_that_was_not_requested_is_marked_so_not_counted_as_failed():
    result = parse_output(
        ["User Policy update has completed successfully."],
        opts(target=TARGET_USER), elevated=False)
    assert result.computer == HALF_NOT_REQUESTED
    assert result.user == HALF_SUCCESS
    assert result.status == STATUS_SUCCESS


def test_a_requested_half_the_output_never_mentions_stays_unknown():
    result = parse_output(
        ["Computer Policy update has completed successfully."],
        opts(target=TARGET_ALL), elevated=True)
    assert result.user == HALF_UNKNOWN
    assert result.status == STATUS_PARTIAL


def test_the_matcher_is_case_insensitive_because_windows_has_changed_the_casing():
    shouty = [line.upper() for line in BOTH_OK]
    assert parse_output(shouty, opts(), elevated=True).status == STATUS_SUCCESS


def test_the_error_detail_under_the_failure_header_is_kept():
    result = parse_output(COMPUTER_REFUSED, opts(), elevated=False)
    assert any("processing of Group Policy failed" in err
               for err in result.errors)


def test_the_diagnose_footer_is_not_collected_as_an_error():
    result = parse_output(COMPUTER_REFUSED, opts(), elevated=False)
    assert not any("GPReport.html" in err for err in result.errors)


# ---------------------------------------------------------------------------
# Elevation
# ---------------------------------------------------------------------------

def test_an_unelevated_computer_refusal_is_explained_as_needing_elevation():
    result = parse_output(COMPUTER_REFUSED, opts(), elevated=False)
    assert result.needs_elevation
    assert "administrator" in result.summary.lower()


def test_an_elevated_computer_refusal_is_not_blamed_on_elevation():
    # Same text, elevated: the cause is something else and saying "run as
    # admin" would send the user down the wrong path.
    lines = [line for line in COMPUTER_REFUSED if "Access is denied" not in line]
    result = parse_output(lines, opts(), elevated=True)
    assert result.computer == HALF_FAILED
    assert not result.needs_elevation


def test_an_access_denied_complaint_still_flags_elevation_even_when_elevated():
    result = parse_output(BOTH_FAILED, opts(), elevated=True)
    assert result.needs_elevation


def test_elevation_state_is_injectable_so_both_paths_test_either_way(monkeypatch):
    install_fake(monkeypatch, out_lines=COMPUTER_REFUSED, returncode=0)
    unelevated = run_gpupdate(opts(), elevated=False)
    install_fake(monkeypatch, out_lines=COMPUTER_REFUSED, returncode=0)
    elevated = run_gpupdate(opts(), elevated=True)
    assert unelevated.needs_elevation is True
    assert elevated.needs_elevation is False
    assert unelevated.elevated is False and elevated.elevated is True


def test_elevation_defaults_to_the_real_admin_check(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    monkeypatch.setattr(gpupdate, "is_admin", lambda: True)
    assert run_gpupdate(opts()).elevated is True
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    monkeypatch.setattr(gpupdate, "is_admin", lambda: False)
    assert run_gpupdate(opts()).elevated is False


# ---------------------------------------------------------------------------
# The exit code is never the verdict
# ---------------------------------------------------------------------------

def test_a_zero_exit_with_a_refusal_in_the_output_is_still_not_a_success(monkeypatch):
    # The whole reason this module parses text: gpupdate exits 0 having
    # refused half the work.
    install_fake(monkeypatch, out_lines=COMPUTER_REFUSED, returncode=0)
    result = run_gpupdate(opts(), elevated=False)
    assert result.exit_code == 0
    assert result.status == STATUS_PARTIAL
    assert not result.ok


def test_a_nonzero_exit_with_success_text_is_still_reported_as_success(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=1)
    result = run_gpupdate(opts(), elevated=True)
    assert result.status == STATUS_SUCCESS
    assert result.exit_code == 1


def test_the_exit_code_is_reported_as_a_signal_and_flagged_when_it_disagrees(monkeypatch):
    install_fake(monkeypatch, out_lines=COMPUTER_REFUSED, returncode=0)
    result = run_gpupdate(opts(), elevated=False)
    assert result.exit_code == 0
    assert result.exit_code_agrees is False


def test_the_exit_code_agrees_on_a_clean_run(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    assert run_gpupdate(opts(), elevated=True).exit_code_agrees is True


def test_the_complaint_is_read_from_stdout_not_stderr(monkeypatch):
    # gpupdate puts its real objection on stdout and leaves stderr empty.
    install_fake(monkeypatch, out_lines=COMPUTER_REFUSED, err_lines=[],
                 returncode=0)
    result = run_gpupdate(opts(), elevated=False)
    assert result.stderr_lines == []
    assert result.errors
    assert result.status == STATUS_PARTIAL


def test_stderr_is_captured_too_and_added_to_the_errors(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_FAILED,
                 err_lines=["ERROR: something on the other pipe"], returncode=1)
    result = run_gpupdate(opts(), elevated=True)
    assert "ERROR: something on the other pipe" in result.stderr_lines
    assert any("other pipe" in err for err in result.errors)


# ---------------------------------------------------------------------------
# Logoff / reboot detection
# ---------------------------------------------------------------------------

def test_a_logoff_requirement_is_detected_from_the_output_wording():
    result = parse_output(LOGOFF_WANTED, opts(), elevated=True)
    assert result.logoff_required
    assert not result.reboot_required
    assert "logoff" in result.summary.lower()


def test_a_restart_requirement_is_detected_from_the_output_wording():
    result = parse_output(REBOOT_WANTED, opts(), elevated=True)
    assert result.reboot_required
    assert "restart" in result.summary.lower()


def test_a_plain_run_asks_for_neither_a_logoff_nor_a_restart():
    result = parse_output(BOTH_OK, opts(), elevated=True)
    assert not result.logoff_required
    assert not result.reboot_required


def test_the_child_gets_no_stdin_so_the_logoff_prompt_cannot_hang_it(monkeypatch):
    install_fake(monkeypatch, out_lines=LOGOFF_WANTED, returncode=0)
    run_gpupdate(opts(), elevated=True)
    assert FakePopen.instances[0].kwargs["stdin"] == subprocess.DEVNULL


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def test_output_reaches_the_callback_line_by_line_not_as_one_blob(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    seen = []
    run_gpupdate(opts(), on_line=seen.append, elevated=True)
    assert seen == BOTH_OK


def test_lines_arrive_while_gpupdate_is_still_running(monkeypatch):
    # A pane that only sees output at the end looks hung for the length of a
    # policy refresh, so the first line must arrive well before the last.
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0,
                 per_line_delay=0.05)
    stamps = []
    started = time.monotonic()
    run_gpupdate(opts(), on_line=lambda line: stamps.append(time.monotonic()),
                 elevated=True)
    assert len(stamps) == len(BOTH_OK)
    assert stamps[0] - started < stamps[-1] - started
    assert stamps[-1] - stamps[0] >= 0.05


def test_the_streamed_lines_are_also_kept_on_the_result(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    result = run_gpupdate(opts(), elevated=True)
    assert result.lines == BOTH_OK
    assert "Updating policy" in result.output


def test_running_without_a_callback_is_fine(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    assert run_gpupdate(opts(), elevated=True).status == STATUS_SUCCESS


def test_the_console_window_is_suppressed(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    run_gpupdate(opts(), elevated=True)
    expected = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert FakePopen.instances[0].kwargs["creationflags"] == expected


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

def test_cancelling_terminates_the_child_process(monkeypatch):
    install_fake(monkeypatch, out_lines=["Updating policy..."], hang=True,
                 returncode=0)
    seen = []

    def cancel_after_first_line():
        return len(seen) >= 1

    result = run_gpupdate(opts(), on_line=seen.append,
                          is_cancelled=cancel_after_first_line, elevated=True)
    assert result.status == STATUS_CANCELLED
    assert result.cancelled
    assert FakePopen.instances[0].terminated


def test_a_cancelled_run_is_not_reported_as_a_success_or_a_failure(monkeypatch):
    install_fake(monkeypatch, out_lines=["Updating policy..."], hang=True,
                 returncode=0)
    seen = []
    result = run_gpupdate(opts(), on_line=seen.append,
                          is_cancelled=lambda: len(seen) >= 1, elevated=True)
    assert result.status == STATUS_CANCELLED
    assert not result.ok
    # The user must be told the machine may be in a half-refreshed state.
    assert "partly refreshed" in result.summary.lower()


def test_cancelling_before_the_run_starts_launches_nothing(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    result = run_gpupdate(opts(), is_cancelled=lambda: True, elevated=True)
    assert result.status == STATUS_CANCELLED
    assert FakePopen.instances == []


def test_lines_already_read_before_the_cancel_are_kept(monkeypatch):
    install_fake(monkeypatch, out_lines=["Updating policy..."], hang=True,
                 returncode=0)
    seen = []
    result = run_gpupdate(opts(), on_line=seen.append,
                          is_cancelled=lambda: len(seen) >= 1, elevated=True)
    assert result.lines == ["Updating policy..."]


def test_no_cancel_callable_means_the_run_is_never_cancelled(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    assert run_gpupdate(opts(), elevated=True).status == STATUS_SUCCESS


# ---------------------------------------------------------------------------
# Timeout and launch failures
# ---------------------------------------------------------------------------

def test_a_run_that_overruns_its_timeout_is_stopped_and_says_so(monkeypatch):
    install_fake(monkeypatch, out_lines=["Updating policy..."], hang=True,
                 returncode=0)
    result = run_gpupdate(opts(timeout=0), elevated=True)
    assert result.status == STATUS_TIMEOUT
    assert result.timed_out
    assert "did not finish within 0s" in result.summary
    assert FakePopen.instances[0].terminated


def test_a_timeout_is_not_reported_as_a_failed_refresh(monkeypatch):
    install_fake(monkeypatch, out_lines=["Updating policy..."], hang=True,
                 returncode=0)
    result = run_gpupdate(opts(timeout=0), elevated=True)
    assert result.status not in (STATUS_SUCCESS, STATUS_FAILURE, STATUS_PARTIAL)


def test_a_missing_gpupdate_exe_is_reported_not_raised(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError()
    monkeypatch.setattr(subprocess, "Popen", boom)
    result = run_gpupdate(opts(), elevated=True)
    assert result.status == STATUS_ERROR
    assert "not found" in result.summary


def test_a_refused_launch_is_reported_not_raised(monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("denied")
    monkeypatch.setattr(subprocess, "Popen", boom)
    result = run_gpupdate(opts(), elevated=True)
    assert result.status == STATUS_ERROR
    assert "denied" in result.summary


# ---------------------------------------------------------------------------
# Wiring details a pane depends on
# ---------------------------------------------------------------------------

def test_the_command_actually_run_is_reported_back(monkeypatch):
    install_fake(monkeypatch, out_lines=BOTH_OK, returncode=0)
    result = run_gpupdate(opts(target=TARGET_USER, force=True), elevated=True)
    assert result.command == ["gpupdate", "/target:user", "/force"]
    assert FakePopen.instances[0].cmd == result.command


def test_the_default_options_refresh_both_halves_without_force():
    assert build_command(GpupdateOptions()) == ["gpupdate"]


def test_a_fresh_result_claims_nothing():
    blank = GpupdateResult()
    assert blank.status == STATUS_UNKNOWN
    assert not blank.ok
    assert blank.exit_code is None
    assert blank.exit_code_agrees is False


def test_the_module_imports_no_pyqt(monkeypatch):
    # This runs on a background Worker thread; importing Qt here would make
    # the logic untestable headless and invite cross-thread widget access.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(gpupdate))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name.startswith("PyQt") for name in imported), imported
