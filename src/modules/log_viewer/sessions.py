r"""Servicing sessions: who asked for the work, and did it fail.

CBS does its work in sessions, and it says so:

    Session: 31275276_4079573531 initialized by client WindowsUpdateAgent

The client is the useful half. It names the component that asked for the
servicing -- `WindowsUpdateAgent`, `DISM Package Manager Provider`, `SPP`,
`Arbiter`, `CbsTask` -- so "which of these failed, and who wanted it" becomes
a question the log can answer directly.

**The marker was found by reading this machine's logs, not assumed.** The
plan for this feature guessed at "Beginning/Ending TrustedInstaller"; that
phrase appears nowhere in either CBS log here, and a detector built on it
would have reported zero sessions on every file while looking perfectly
healthy. What is really there: 12 sessions in `CBS.log` across three clients,
9 in the 138,683-record archive across six.

There is no explicit end marker, so a session runs until the next one begins
or until the records run out. That is what the log supports; inventing an end
would be inventing information.

No Qt.
"""
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .cmtrace_parser import UNKNOWN_TIME

#: `Session: <id> initialized by client <name>`. Anchored on "initialized by
#: client" so a line merely mentioning a session is not mistaken for the
#: start of one. The client name runs to the end of the line because real
#: ones contain spaces -- `DISM Package Manager Provider`.
_SESSION = re.compile(
    r"Session:\s*(\S+)\s+initialized by client\s+(.+?)\s*$")


@dataclass(frozen=True)
class Session:
    """One servicing session, as a span of record indices."""
    start: int
    end: int
    session_id: str
    client: str
    errors: int
    when: Optional[datetime]

    @property
    def failed(self) -> bool:
        return self.errors > 0

    def label(self) -> str:
        """How the session reads in a list."""
        state = f"{self.errors} error(s)" if self.errors else "clean"
        return f"{self.client} — {state}"


def sessions(entries) -> list:
    """Every servicing session in `entries`, in order.

    Records before the first marker belong to no session: a tail slice
    routinely opens mid-session, and inventing one to hold the preamble
    would attribute it to a client that never asked for it.
    """
    entries = list(entries or ())
    starts = []
    for index, entry in enumerate(entries):
        match = _SESSION.search(entry.message or "")
        if match:
            starts.append((index, match.group(1), match.group(2)))

    found = []
    for position, (index, session_id, client) in enumerate(starts):
        # No end marker exists, so a session runs to the next one or to the
        # end of what is loaded.
        end = (starts[position + 1][0] - 1 if position + 1 < len(starts)
               else len(entries) - 1)
        errors = sum(1 for entry in entries[index:end + 1]
                     if entry.level == "Error")
        when = entries[index].timestamp
        found.append(Session(start=index, end=end, session_id=session_id,
                             client=client, errors=errors,
                             when=None if when == UNKNOWN_TIME else when))
    return found
