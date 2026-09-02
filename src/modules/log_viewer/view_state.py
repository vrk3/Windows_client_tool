"""What the Log Viewer is currently showing — with no Qt in it.

The same split `cmtrace_parser.py` and `log_reader.py` keep, and for the
same reason: this is the part worth reasoning about without a display, and
it was buried inside a 480-line `__init__` alongside the widget
construction.

Nothing here knows about a QLineEdit or a QCheckBox. The widget reads its
controls into one of these and writes one back; what "the view is currently
filtered to ERROR, following, with the Thread column hidden" means is
answerable — and testable — without building a pane.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List

#: The severities the pane knows. Anything else in a saved state is dropped
#: rather than trusted — a stale profile must not be able to make the view
#: filter on a severity the model cannot produce.
KNOWN_SEVERITIES = ("Info", "Warning", "Error")


@dataclass
class LogViewState:
    """Everything the reader has chosen about how the log is displayed."""

    #: What Find is looking for. Find JUMPS; it does not hide anything.
    find_text: str = ""
    #: What Filter keeps. Filter HIDES everything that does not match.
    filter_text: str = ""
    #: What Exclude drops, applied after `filter_text`.
    exclude_text: str = ""
    #: Treat the three text boxes as regular expressions.
    regex: bool = False
    severities: List[str] = field(default_factory=lambda: list(KNOWN_SEVERITIES))
    #: "" means every thread.
    thread: str = ""
    #: "" means every component.
    component: str = ""
    #: Whether the reader has actually ASKED for a time range. The range
    #: boxes always hold a value — the log's whole span, or whatever a
    #: manual edit put there — so holding a value is not the same as
    #: wanting one. Without this distinction "Clear range" is undone by the
    #: next touch of any other control, and while following, the upper
    #: bound stays frozen at the moment the log was opened so new lines
    #: silently stop appearing.
    range_active: bool = False
    following: bool = False
    #: Columns the reader turned off, by NAME. Thread is dead weight on CBS
    #: and essential on DISM's 329 threads, so this is a real preference and
    #: not a default anyone can pick for them.
    hidden_columns: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "LogViewState":
        """Rebuild from `to_dict` output, ignoring anything unrecognised.

        Forgiving on purpose: this is read back from a config file that an
        older or newer build wrote, and a key that no longer exists should
        not cost the reader every other preference they set.
        """
        known = set(cls.__dataclass_fields__)
        state = cls(**{k: v for k, v in (data or {}).items() if k in known})
        state.severities = [s for s in state.severities if s in KNOWN_SEVERITIES]
        if not state.severities:
            # Every severity hidden shows an empty pane that looks like an
            # empty log. Fall back rather than display a lie.
            state.severities = list(KNOWN_SEVERITIES)
        return state

    def is_filtering(self) -> bool:
        """Whether anything is being hidden right now.

        The status line needs this to say so — silently showing a subset of
        a log is how someone concludes the log is clean.
        """
        return bool(
            self.filter_text
            or self.exclude_text
            or self.thread
            or self.component
            or self.range_active
            or set(self.severities) != set(KNOWN_SEVERITIES)
        )
