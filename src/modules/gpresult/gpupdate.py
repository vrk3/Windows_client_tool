"""Run `gpupdate` and say honestly what came back.

The trap this file exists to avoid is the one this codebase keeps meeting:
**a Windows admin command that exits 0 while refusing to do the work, and
writes its real complaint to stdout rather than stderr.** `gpresult`, `netsh`,
`dism` and `Get-Tpm` have each done it here. `gpupdate` does it too --
refreshing *computer* policy needs an elevated token, and without one it
prints a failure paragraph in the middle of otherwise normal output::

    Updating policy...

    Computer policy could not be updated successfully. The following errors
    were encountered:

    The processing of Group Policy failed. ...

    User Policy update has completed successfully.

That run is not a failure and it is not a success. It is the *common* case on
an unelevated desktop, and reporting it as either extreme is a lie. So the
verdict here comes from parsing the output text; `returncode` is recorded and
offered as one signal among several, never as the answer.

Two more things this module is careful about:

* **Streaming.** A policy refresh takes many seconds. Output is handed to a
  callback line by line as it arrives, so the pane can show progress instead
  of looking hung.
* **Not blocking on a prompt.** When an extension needs a logoff or a restart,
  gpupdate *asks*: "Do you want to log off now? (Y/N)". `/logoff` and `/boot`
  do not suppress that question -- they PERFORM the logoff or the reboot, so
  they are never passed. Instead the child's stdin is DEVNULL, so the prompt
  reads EOF and gives up, and the requirement is detected from the wording of
  the output and reported to the caller to act on.

No PyQt6 here on purpose: a background `core.worker.Worker` calls this, and
the tests run headless.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

from core.admin_utils import is_admin

logger = logging.getLogger(__name__)

# gpupdate's own default is to wait 600s for policy processing, so a shorter
# timeout here would kill runs that were going to succeed.
DEFAULT_TIMEOUT = 600

# Targets, matching `gpupdate /target:{Computer | User}` plus "all", which is
# gpupdate's default and is expressed by passing no /target at all.
TARGET_ALL = "all"
TARGET_USER = "user"
TARGET_COMPUTER = "computer"
TARGETS = (TARGET_ALL, TARGET_USER, TARGET_COMPUTER)

# Overall verdicts.
STATUS_SUCCESS = "success"      # every requested half refreshed
STATUS_PARTIAL = "partial"      # some refreshed, some did not
STATUS_FAILURE = "failure"      # every requested half failed
STATUS_UNKNOWN = "unknown"      # gpupdate ran but said nothing we recognise
STATUS_CANCELLED = "cancelled"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"          # could not launch gpupdate at all

# Per-half verdicts.
HALF_SUCCESS = "success"
HALF_FAILED = "failed"
HALF_NOT_REQUESTED = "not requested"
HALF_UNKNOWN = "unknown"

# How often the reader loop wakes up to check cancellation and the deadline.
# gpupdate can be silent for tens of seconds, so waiting on the next line
# would make Cancel feel dead.
_POLL_SECONDS = 0.1

# How long a terminated child gets to die before it is killed.
_TERMINATE_GRACE = 5

# Phrase matching is deliberately loose: lowercase substring, several
# spellings each. Windows has changed the capitalisation of these strings
# between builds ("Computer Policy update" vs "Computer policy update") and an
# exact match would silently stop recognising success one day.
_COMPUTER_OK = ("computer policy update has completed successfully",)
_USER_OK = ("user policy update has completed successfully",)
_COMPUTER_FAIL = ("computer policy could not be updated successfully",)
_USER_FAIL = ("user policy could not be updated successfully",)

# Wording that means "an extension cannot finish until the user logs off".
_LOGOFF_PHRASES = (
    "requires a logoff",
    "require a logoff",
    "requires a log off",
    "require a log off",
    "logoff is required",
    "log off is required",
    "log off now",
    "logoff now",
)

# Wording that means "an extension cannot finish until the machine restarts".
_REBOOT_PHRASES = (
    "requires a restart",
    "require a restart",
    "requires a reboot",
    "require a reboot",
    "restart is required",
    "reboot is required",
    "restart now",
    "reboot now",
    "computer restart",
)

# Hints that the computer half was refused for want of an elevated token
# rather than for a policy-processing reason.
_ELEVATION_PHRASES = (
    "access is denied",
    "access denied",
    "requires elevation",
    "elevated",
    "as an administrator",
    "run as administrator",
    "insufficient privilege",
    "privilege",
)

# Lines that open or close the error paragraph gpupdate prints after a
# "could not be updated" header.
_ERROR_BLOCK_OPENER = "the following errors were encountered"
_ERROR_BLOCK_CLOSER = "to diagnose the failure"

_NEEDS_ELEVATION = (
    "Computer policy was not refreshed: that needs an elevated run. "
    "Restart this tool as administrator to refresh Computer Configuration."
)


def _no_window() -> int:
    """CREATE_NO_WINDOW, or 0 off Windows so this module still imports."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _matches(haystack: str, needles: Sequence[str]) -> bool:
    return any(needle in haystack for needle in needles)


@dataclass
class GpupdateOptions:
    """What to ask gpupdate for.

    `wait` maps to `/wait:<seconds>`. It is None by default and should usually
    stay that way: when gpupdate's wait expires it returns to the prompt
    *while policy processing continues*, which looks exactly like a completed
    run and would make this module report a result it cannot vouch for.
    """

    target: str = TARGET_ALL
    force: bool = False
    timeout: int = DEFAULT_TIMEOUT
    wait: Optional[int] = None


@dataclass
class GpupdateResult:
    """Everything the pane needs to render an honest verdict.

    `status` is the verdict and comes from the output text. `exit_code` is
    kept beside it as a signal, not as the answer -- see `exit_code_agrees`.
    """

    status: str = STATUS_UNKNOWN
    summary: str = ""
    computer: str = HALF_UNKNOWN
    user: str = HALF_UNKNOWN
    logoff_required: bool = False
    reboot_required: bool = False
    needs_elevation: bool = False
    elevated: bool = False
    exit_code: Optional[int] = None
    errors: List[str] = field(default_factory=list)
    lines: List[str] = field(default_factory=list)
    stderr_lines: List[str] = field(default_factory=list)
    command: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def ok(self) -> bool:
        """True only when every requested half actually refreshed."""
        return self.status == STATUS_SUCCESS

    @property
    def cancelled(self) -> bool:
        return self.status == STATUS_CANCELLED

    @property
    def timed_out(self) -> bool:
        return self.status == STATUS_TIMEOUT

    @property
    def output(self) -> str:
        """Streamed stdout, rejoined. stderr is kept separately."""
        return "\n".join(self.lines)

    @property
    def exit_code_agrees(self) -> bool:
        """Whether `exit_code` tells the same story the output text told.

        A False here is worth showing the user: it is the exact shape of bug
        that made this module parse output in the first place.
        """
        if self.exit_code is None:
            return False
        zero = self.exit_code == 0
        if self.status == STATUS_SUCCESS:
            return zero
        if self.status in (STATUS_FAILURE, STATUS_PARTIAL):
            return not zero
        return False


def build_command(options: GpupdateOptions) -> List[str]:
    """The argv for `options`.

    Note what is absent: `/logoff` and `/boot`. Their names suggest they
    suppress the interactive question, but they actually perform the logoff or
    the reboot. Deciding to reboot someone's machine is not this module's
    call, so the question is defused with DEVNULL stdin instead.
    """
    if options.target not in TARGETS:
        raise ValueError(
            "target must be one of %s, got %r"
            % (", ".join(TARGETS), options.target))

    cmd = ["gpupdate"]
    if options.target == TARGET_USER:
        cmd.append("/target:user")
    elif options.target == TARGET_COMPUTER:
        cmd.append("/target:computer")
    # TARGET_ALL passes no /target: both halves are already gpupdate's
    # default, and there is no "/target:both" to pass.
    if options.force:
        cmd.append("/force")
    if options.wait is not None:
        cmd.append("/wait:%d" % options.wait)
    return cmd


def parse_output(lines: Sequence[str], options: GpupdateOptions,
                 elevated: bool) -> GpupdateResult:
    """Turn gpupdate's chatter into a verdict, with no exit code involved.

    Split out from `run_gpupdate` so the interesting half is testable against
    captured text without a subprocess anywhere near it.
    """
    result = GpupdateResult()
    result.lines = list(lines)
    result.elevated = elevated
    result.command = build_command(options)

    wants_computer = options.target in (TARGET_ALL, TARGET_COMPUTER)
    wants_user = options.target in (TARGET_ALL, TARGET_USER)
    result.computer = HALF_UNKNOWN if wants_computer else HALF_NOT_REQUESTED
    result.user = HALF_UNKNOWN if wants_user else HALF_NOT_REQUESTED

    in_error_block = False
    for raw in lines:
        low = raw.strip().lower()
        if not low:
            continue

        if _matches(low, _COMPUTER_OK):
            result.computer = HALF_SUCCESS
            in_error_block = False
        elif _matches(low, _USER_OK):
            result.user = HALF_SUCCESS
            in_error_block = False
        elif _matches(low, _COMPUTER_FAIL):
            result.computer = HALF_FAILED
            in_error_block = True
        elif _matches(low, _USER_FAIL):
            result.user = HALF_FAILED
            in_error_block = True
        elif _ERROR_BLOCK_OPENER in low:
            in_error_block = True
        elif _ERROR_BLOCK_CLOSER in low:
            in_error_block = False
        elif in_error_block:
            # The detail paragraph under a "could not be updated" header:
            # this is the part that actually tells an admin what broke.
            result.errors.append(raw.strip())

        if _matches(low, _LOGOFF_PHRASES):
            result.logoff_required = True
        if _matches(low, _REBOOT_PHRASES):
            result.reboot_required = True

    # A half that was asked for and never spoken about is not a success. It
    # stays HALF_UNKNOWN and drags the verdict down accordingly.
    requested = [half for half in (result.computer, result.user)
                 if half != HALF_NOT_REQUESTED]
    good = [half for half in requested if half == HALF_SUCCESS]
    bad = [half for half in requested if half == HALF_FAILED]

    if not requested:
        result.status = STATUS_UNKNOWN
    elif len(good) == len(requested):
        result.status = STATUS_SUCCESS
    elif good:
        # Some half worked and some did not: the partial case, which must be
        # reported as neither extreme.
        result.status = STATUS_PARTIAL
    elif len(bad) == len(requested):
        result.status = STATUS_FAILURE
    elif bad:
        result.status = STATUS_PARTIAL
    else:
        result.status = STATUS_UNKNOWN

    # The signature case: computer half refused while unelevated. Say so
    # plainly rather than leaving the user to guess.
    blob = "\n".join(lines).lower()
    if result.computer == HALF_FAILED and (
            not elevated or _matches(blob, _ELEVATION_PHRASES)):
        result.needs_elevation = True

    result.summary = _summarise(result)
    return result


def _halves_phrase(result: GpupdateResult, state: str) -> str:
    names = []
    if result.computer == state:
        names.append("Computer")
    if result.user == state:
        names.append("User")
    return " and ".join(names)


def _summarise(result: GpupdateResult) -> str:
    """One sentence a pane can put in a status bar without editing."""
    if result.status == STATUS_SUCCESS:
        text = "%s policy refreshed successfully." % _halves_phrase(
            result, HALF_SUCCESS)
    elif result.status == STATUS_FAILURE:
        text = "%s policy could not be refreshed." % _halves_phrase(
            result, HALF_FAILED)
    elif result.status == STATUS_PARTIAL:
        good = _halves_phrase(result, HALF_SUCCESS)
        bad = (_halves_phrase(result, HALF_FAILED)
               or _halves_phrase(result, HALF_UNKNOWN))
        text = ("Partial refresh: %s policy refreshed, %s policy did not."
                % (good, bad))
    else:
        text = ("gpupdate finished but its output did not say whether policy "
                "was refreshed.")

    if result.needs_elevation:
        text += " " + _NEEDS_ELEVATION
    if result.logoff_required:
        text += " A logoff is required for some settings to take effect."
    if result.reboot_required:
        text += " A restart is required for some settings to take effect."
    return text


def run_gpupdate(options: Optional[GpupdateOptions] = None,
                 on_line: Optional[Callable[[str], None]] = None,
                 is_cancelled: Optional[Callable[[], bool]] = None,
                 elevated: Optional[bool] = None) -> GpupdateResult:
    """Run gpupdate, stream its output, and report what really happened.

    Args:
        options: target / force / timeout. Defaults to both halves, no force.
        on_line: called once per line of gpupdate stdout, as it arrives, from
            the calling thread. Lines are right-stripped and carry no newline.
        is_cancelled: polled about every 100ms; when it returns True the child
            is terminated and the result comes back STATUS_CANCELLED.
            `core.worker.Worker.is_cancelled` is a property, so a pane passes
            `lambda: worker.is_cancelled`.
        elevated: injectable so both the elevated and the unelevated verdicts
            are testable whatever the test runner is running as. Defaults to
            the real `core.admin_utils.is_admin()`.
    """
    options = options or GpupdateOptions()
    if elevated is None:
        elevated = is_admin()
    cmd = build_command(options)

    if is_cancelled is not None and is_cancelled():
        return _terminal(STATUS_CANCELLED,
                         "Cancelled before gpupdate started.", cmd, elevated)

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # gpupdate ASKS "Do you want to log off now? (Y/N)" when an
            # extension needs it. With no stdin the read hits EOF instead of
            # hanging a background worker forever.
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_no_window(),
        )
    except FileNotFoundError:
        return _terminal(STATUS_ERROR,
                         "gpupdate.exe was not found on this system.",
                         cmd, elevated)
    except OSError as exc:
        logger.warning("Could not start gpupdate: %s", exc)
        return _terminal(STATUS_ERROR, "Could not start gpupdate: %s" % exc,
                         cmd, elevated)

    stderr_lines: List[str] = []
    stderr_thread = _drain_stderr(proc, stderr_lines)

    lines, outcome = _pump_stdout(proc, options, on_line, is_cancelled, started)

    if stderr_thread is not None:
        stderr_thread.join(timeout=_TERMINATE_GRACE)

    duration = time.monotonic() - started

    if outcome == STATUS_CANCELLED:
        result = _terminal(
            STATUS_CANCELLED,
            "Cancelled. gpupdate was stopped part-way, so policy may be "
            "partly refreshed.", cmd, elevated)
    elif outcome == STATUS_TIMEOUT:
        result = _terminal(
            STATUS_TIMEOUT,
            "gpupdate did not finish within %ds and was stopped. Policy may "
            "be partly refreshed." % options.timeout, cmd, elevated)
    else:
        result = parse_output(lines, options, elevated)

    result.lines = lines
    result.stderr_lines = stderr_lines
    result.duration_seconds = duration
    result.exit_code = proc.returncode

    # stderr is captured because it must be, but gpupdate's real complaint
    # arrives on stdout; anything here is a bonus and never the verdict.
    for line in stderr_lines:
        text = line.strip()
        if text and text not in result.errors:
            result.errors.append(text)

    logger.debug("gpupdate %s: status=%s exit=%s (agrees=%s)",
                 " ".join(cmd), result.status, result.exit_code,
                 result.exit_code_agrees)
    if result.status in (STATUS_SUCCESS, STATUS_PARTIAL, STATUS_FAILURE) \
            and not result.exit_code_agrees:
        # Exactly the mismatch this module exists for. Worth a line in the
        # session log so the next person sees that it happened.
        logger.warning("gpupdate exit code %s disagrees with parsed status %r",
                       result.exit_code, result.status)
    return result


def _terminal(status: str, summary: str, cmd: List[str],
              elevated: bool) -> GpupdateResult:
    """A result for a run that never produced a parseable verdict."""
    result = GpupdateResult()
    result.status = status
    result.summary = summary
    result.command = list(cmd)
    result.elevated = elevated
    return result


def _drain_stderr(proc, sink: List[str]) -> Optional[threading.Thread]:
    """Read stderr on a side thread so it can never deadlock stdout.

    Both pipes are captured, and a full stderr pipe buffer would block the
    child mid-write while we sat waiting on stdout. A reader thread is the
    only way to hold both open safely.
    """
    if getattr(proc, "stderr", None) is None:
        return None

    def _read() -> None:
        try:
            for line in proc.stderr:
                sink.append(line.rstrip("\r\n"))
        except (ValueError, OSError) as exc:
            # Pipe closed under us because the child was terminated. Expected
            # on cancel; recorded rather than silently dropped.
            logger.debug("gpupdate stderr reader stopped: %s", exc)

    thread = threading.Thread(target=_read, name="gpupdate-stderr", daemon=True)
    thread.start()
    return thread


def _pump_stdout(proc, options: GpupdateOptions,
                 on_line: Optional[Callable[[str], None]],
                 is_cancelled: Optional[Callable[[], bool]],
                 started: float) -> Tuple[List[str], Optional[str]]:
    """Stream stdout to `on_line`, returning (lines, outcome).

    The child's stdout is iterated on a side thread and handed over through a
    queue, so cancellation and the deadline are checked on a timer rather than
    only when gpupdate happens to print something. gpupdate goes quiet for
    long stretches; without this, Cancel would appear not to work.

    `on_line` is called from the *calling* thread -- the background Worker
    thread the pane started -- never from the reader thread.
    """
    lines: List[str] = []
    if getattr(proc, "stdout", None) is None:
        return lines, None

    inbox: "queue.Queue" = queue.Queue()
    sentinel = object()

    def _read() -> None:
        try:
            for line in proc.stdout:
                inbox.put(line.rstrip("\r\n"))
        except (ValueError, OSError) as exc:
            logger.debug("gpupdate stdout reader stopped: %s", exc)
        finally:
            inbox.put(sentinel)

    reader = threading.Thread(target=_read, name="gpupdate-stdout", daemon=True)
    reader.start()

    outcome: Optional[str] = None
    while True:
        if is_cancelled is not None and is_cancelled():
            outcome = STATUS_CANCELLED
            break
        if time.monotonic() - started > options.timeout:
            outcome = STATUS_TIMEOUT
            break
        try:
            item = inbox.get(timeout=_POLL_SECONDS)
        except queue.Empty:
            logger.debug("_pump_stdout: skipping an item that could not be read", exc_info=True)
            continue
        if item is sentinel:
            break
        lines.append(item)
        if on_line is not None:
            on_line(item)

    if outcome is not None:
        _stop(proc)
        # Whatever the reader already pulled off the pipe is real output and
        # belongs in the log the user is looking at.
        while True:
            try:
                item = inbox.get_nowait()
            except queue.Empty:
                logger.debug("_pump_stdout: stopping, nothing more could be read", exc_info=True)
                break
            if item is sentinel:
                continue
            lines.append(item)
            if on_line is not None:
                on_line(item)
    else:
        try:
            proc.wait(timeout=_TERMINATE_GRACE)
        except subprocess.TimeoutExpired:
            logger.warning("gpupdate closed stdout but did not exit; stopping it.")
            _stop(proc)

    reader.join(timeout=_TERMINATE_GRACE)
    return lines, outcome


def _stop(proc) -> None:
    """Terminate the child, then kill it if it will not go."""
    try:
        if proc.poll() is None:
            proc.terminate()
    except OSError as exc:
        logger.warning("Could not terminate gpupdate: %s", exc)
        return
    try:
        proc.wait(timeout=_TERMINATE_GRACE)
    except subprocess.TimeoutExpired:
        logger.warning("gpupdate ignored terminate; killing it.")
        try:
            proc.kill()
            proc.wait(timeout=_TERMINATE_GRACE)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Could not kill gpupdate: %s", exc)
