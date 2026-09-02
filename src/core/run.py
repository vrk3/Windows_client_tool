"""The one way this app shells out.

Before this existed, 42 of 378 files declared their own `CREATE_NO_WINDOW`
and 112 call sites each re-decided creation flags, encoding, error handling
and — in 31 cases, not at all — the timeout. A `sc`, `netsh` or `dism` that
never returns pins a `QThreadPool` slot for the life of the process, and the
pane waiting on it shows a spinner that never stops with nothing in the log
to explain why.

Three rules this module exists to enforce:

* **Every call has a timeout.** It is a keyword argument with a default, not
  something a caller has to remember.

* **A timeout is a result, not an exception.** Callers overwhelmingly want to
  show "that took too long" in the same place they show "that failed", so a
  timeout comes back as `returncode == -1` with the reason in `stderr`.
  `check=True` still raises, for the callers that want it.

* **`argv` is a list.** This function does not take `shell=True`. The seven
  call sites that legitimately need a shell are enumerated in CLAUDE.md and
  stay where they are; a new one should not be added casually.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

#: Suppress the console window a subprocess would otherwise flash up in a
#: windowed build. Windows-only, and the whole reason 42 separate files each
#: carried their own copy of this constant.
CREATE_NO_WINDOW = 0x08000000

#: Long enough for a `netsh`/`sc`/`reg` call that is working, short enough
#: that a wedged one is noticed. Anything genuinely slower — dism, sfc,
#: Compact-WinSxS — passes its own and says why.
DEFAULT_TIMEOUT = 60.0

#: PowerShell pays for its own start-up before it runs anything.
PS_DEFAULT_TIMEOUT = 120.0

#: Timed out. Chosen because Windows exit codes are unsigned, so no real
#: process reports -1, and because a caller checking `rc != 0` treats it as
#: a failure without having to know about this module.
TIMED_OUT = -1


def run(
    argv: Sequence[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    cwd: Optional[str] = None,
    check: bool = False,
    input_text: Optional[str] = None,
) -> "subprocess.CompletedProcess[str]":
    """Run `argv` and return its result. Never hangs.

    Output is decoded as UTF-8 with `errors="replace"`: several of the tools
    this app drives emit characters cp1252 cannot represent, and losing the
    whole reading to a UnicodeDecodeError is worse than one replacement
    character in a message.
    """
    if isinstance(argv, str):  # pragma: no cover - programmer error
        raise TypeError("run() takes a list of arguments, not a command string")

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
            returncode=TIMED_OUT,
            stdout=_as_text(exc.stdout),
            stderr=f"timed out after {timeout}s",
        )


def run_ps(script: str, *, timeout: float = PS_DEFAULT_TIMEOUT) -> "subprocess.CompletedProcess[str]":
    r"""Run a PowerShell script block.

    `-NoProfile` because a user's profile can print banners, change the
    culture or fail outright, none of which belongs in a reading this app
    takes. `-NonInteractive` so a cmdlet that wants confirmation fails
    rather than waiting for a keypress nobody can give it.

    Any value interpolated into `script` must go through
    `core.windows_utils.ps_quote` first.
    """
    return run(
        ["powershell", "-NoProfile", "-NonInteractive",
         "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )


def timed_out(result: "subprocess.CompletedProcess[str]") -> bool:
    """Whether `result` came back from a timeout rather than the process."""
    return result.returncode == TIMED_OUT


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)
