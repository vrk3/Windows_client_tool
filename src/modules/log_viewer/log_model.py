"""The table model behind the log viewer.

A `QAbstractTableModel` over a capped deque, not `QTreeWidgetItem`s: a
ConfigMgr log runs to hundreds of thousands of records, and a widget item per
row does not survive that.

Filtering keeps a separate index list rather than copying entries, so turning
"Errors only" on and off costs a pass over integers and never touches the
records themselves.
"""
import re
from collections import deque

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PyQt6.QtGui import QColor

from .cmtrace_parser import UNKNOWN_TIME
from .highlight import matching_rule
from .palette import component_colour, readable_text_on, severity_row_colour

COLUMNS = ("Time", "Severity", "Component", "Thread", "Message")
TIME, SEVERITY, COMPONENT, THREAD, MESSAGE = range(len(COLUMNS))

#: How many records are kept. Past this the oldest go, which is what CMTrace
#: does in practice and what keeps a 300 MB log openable.
DEFAULT_CAP = 200_000


class LogModel(QAbstractTableModel):
    def __init__(self, parent=None, cap: int = DEFAULT_CAP) -> None:
        super().__init__(parent)
        self._entries = deque(maxlen=cap)
        self._visible: list = []
        self._levels = set()            # empty means "show everything"
        self._needle = ""
        self._pattern = ""
        self._component = ""
        self._thread = ""
        self._time_from = None
        self._time_to = None
        self._regex = False
        self._matcher = None            # compiled once per set_filter
        self._rules = []                # highlight rules
        self.dropped = 0                # records aged out of the cap

    # ---- content --------------------------------------------------------

    def append(self, entries) -> None:
        """Add parsed records, keeping the newest when the cap is reached.

        INSERTS rather than resets. A reset clears the view's selection, and
        while following this runs every second -- click a row to read it and
        it deselects under you a tick later.

        A reset is still right in one case: once the cap starts dropping from
        the front, every surviving record's index shifts, and an insert would
        leave the view pointing at the wrong rows.
        """
        if not entries:
            return
        entries = list(entries)
        capacity = self._entries.maxlen
        overflow = 0
        if capacity is not None:
            overflow = max(0, len(self._entries) + len(entries) - capacity)

        if overflow:
            self.dropped += overflow
            self.beginResetModel()
            self._entries.extend(entries)
            self._reindex()
            self.endResetModel()
            return

        first = len(self._entries)
        fresh = [first + offset for offset, entry in enumerate(entries)
                 if self._matches(entry)]
        if not fresh:
            # Everything new is hidden by the current filter: the records go
            # in, but no row appears and the view need not be told.
            self._entries.extend(entries)
            return
        start = len(self._visible)
        self.beginInsertRows(QModelIndex(), start, start + len(fresh) - 1)
        self._entries.extend(entries)
        self._visible.extend(fresh)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._entries.clear()
        self._visible = []
        self.dropped = 0
        self.endResetModel()

    def entry(self, row: int):
        if 0 <= row < len(self._visible):
            return self._entries[self._visible[row]]
        return None

    @property
    def total(self) -> int:
        return len(self._entries)

    def components(self) -> list:
        return sorted({e.source for e in self._entries if e.source})

    # ---- filtering ------------------------------------------------------

    def set_filter(self, levels=None, needle: str = None,
                   component: str = None, thread: str = None,
                   time_from=None, time_to=None, regex: bool = None) -> None:
        """Each argument left as None keeps that axis unchanged.

        `time_from`/`time_to` take the sentinel `False` to mean "clear this
        bound", since None already means "leave it alone" and a range has to
        be removable.
        """
        if levels is not None:
            self._levels = set(levels)
        if needle is not None:
            self._needle = needle.lower()
            self._pattern = needle
        if component is not None:
            self._component = component
        if thread is not None:
            self._thread = thread
        if time_from is not None:
            self._time_from = None if time_from is False else time_from
        if time_to is not None:
            self._time_to = None if time_to is False else time_to
        if regex is not None:
            self._regex = bool(regex)

        # Compiled ONCE here, never inside _matches: at 134,527 records a
        # per-row compile is 134,527 compiles per keystroke.
        self._matcher = None
        if self._regex and self._pattern:
            try:
                self._matcher = re.compile(self._pattern, re.IGNORECASE)
            except re.error:
                # A half-typed pattern is a typo. Nothing matches until it
                # is finished; the pane says so in the status bar.
                self._matcher = False

        self.beginResetModel()
        self._reindex()
        self.endResetModel()

    def set_highlight_rules(self, rules) -> None:
        """Colouring only -- which rows are VISIBLE does not change, so this
        repaints rather than resetting. A reset would clear the selection,
        the same trap `append` documents."""
        self._rules = list(rules or [])
        if self._visible:
            top = self.index(0, 0)
            bottom = self.index(len(self._visible) - 1, len(COLUMNS) - 1)
            self.dataChanged.emit(top, bottom,
                                  [Qt.ItemDataRole.BackgroundRole,
                                   Qt.ItemDataRole.ForegroundRole])

    def _matches(self, entry) -> bool:
        if self._levels and entry.level not in self._levels:
            return False
        if self._component and entry.source != self._component:
            return False
        if self._thread and entry.raw.get("thread", "") != self._thread:
            return False
        # A record with no timestamp of its own -- a continuation line -- is
        # never removed by a time filter. Losing a record is the one outcome
        # a log viewer must not produce.
        if entry.timestamp != UNKNOWN_TIME:
            if self._time_from and entry.timestamp < self._time_from:
                return False
            if self._time_to and entry.timestamp > self._time_to:
                return False
        if self._needle:
            # The whole ROW as the user sees it, not just the message.
            # Typing "warning" has to find the warning row of a CMTrace log,
            # where the word lives in the type attribute rather than the text.
            haystack = f"{entry.message} {entry.level} {entry.source}"
            if self._matcher is False:
                return False
            if self._matcher is not None:
                if not self._matcher.search(haystack):
                    return False
            elif self._needle not in haystack.lower():
                return False
        return True

    def threads(self) -> list:
        """`(thread, count)` ordered by count descending.

        DISM carries 329 distinct thread ids; an alphabetical list of 329
        numbers is not a control anyone can use.
        """
        counts: dict = {}
        for entry in self._entries:
            thread = entry.raw.get("thread", "")
            if thread:
                counts[thread] = counts.get(thread, 0) + 1
        return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))

    def time_span(self):
        """`(first, last)` real timestamp, or None. Used to prefill the range
        boxes so they open on the whole log rather than on the year 1752."""
        stamps = [e.timestamp for e in self._entries
                  if e.timestamp != UNKNOWN_TIME]
        if not stamps:
            return None
        return min(stamps), max(stamps)

    def filter_pattern_is_invalid(self) -> bool:
        """The pane asks, so it can say so rather than showing an empty
        table that reads as "no such records"."""
        return self._matcher is False

    def _reindex(self) -> None:
        self._visible = [i for i, e in enumerate(self._entries)
                         if self._matches(e)]

    # ---- Qt -------------------------------------------------------------

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._visible)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation is Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole
                and 0 <= section < len(COLUMNS)):
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        entry = self.entry(index.row()) if index.isValid() else None
        if entry is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            column = index.column()
            if column == TIME:
                # A record whose date could not be read still has a message;
                # showing "0001-01-01" as though it were a real time would be
                # worse than admitting we do not know.
                if entry.timestamp == UNKNOWN_TIME:
                    return ""
                # Milliseconds only when the log actually wrote them. CBS
                # writes whole seconds, so `%f` gave all 12,598 of its rows a
                # `.000` that reads as a measurement rather than as padding.
                if entry.raw.get("subsecond"):
                    return entry.timestamp.strftime(
                        "%Y-%m-%d %H:%M:%S.%f")[:-3]
                return entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if column == SEVERITY:
                return entry.level
            if column == COMPONENT:
                return entry.source
            if column == THREAD:
                return entry.raw.get("thread", "")
            if column == MESSAGE:
                # One row per record: a stack trace is one entry, and letting
                # its newlines through would break the row height for the
                # whole table.
                return entry.message.replace("\n", " ↵ ")
        elif role == Qt.ItemDataRole.BackgroundRole:
            # The Component column is the one place the row background does
            # not apply: its tint wins there, over severity and over a
            # highlight rule. Otherwise every Error row would lose the
            # component colour, which is the whole point of the column.
            if index.column() == COMPONENT and entry.source:
                return QColor(component_colour(entry.source)[0])
            rule = matching_rule(self._rules, entry)
            if rule is not None:
                return QColor(rule.colour)
            colour = severity_row_colour(entry.level)
            return QColor(colour[0]) if colour else None
        elif role == Qt.ItemDataRole.ForegroundRole:
            if index.column() == COMPONENT and entry.source:
                return QColor(component_colour(entry.source)[1])
            rule = matching_rule(self._rules, entry)
            if rule is not None:
                return QColor(readable_text_on(rule.colour))
            colour = severity_row_colour(entry.level)
            return QColor(colour[1]) if colour else None
        elif role == Qt.ItemDataRole.ToolTipRole:
            # The line as written, then what its error codes mean. This is
            # what people open CMTrace for: a line says 0x80070005 and they
            # need "access denied".
            from .error_codes import annotate

            return annotate(entry.message)
        return None

    # ---- find -----------------------------------------------------------

    def find(self, needle: str, start_row: int = 0, forwards: bool = True) -> int:
        """The next visible row containing `needle`, or -1.

        Wraps, because a search that stops at the end of a log makes the user
        scroll back to the top to carry on. Honours the same Regex flag the
        filter does: one checkbox governs both.
        """
        if not needle or not self._visible:
            return -1
        matcher = None
        if self._regex:
            try:
                matcher = re.compile(needle, re.IGNORECASE)
            except re.error:
                return -1
        lowered = needle.lower()
        count = len(self._visible)
        step = 1 if forwards else -1
        for offset in range(1, count + 1):
            row = (start_row + offset * step) % count
            entry = self.entry(row)
            if entry is None:
                continue
            if matcher is not None:
                if matcher.search(entry.message):
                    return row
            elif lowered in entry.message.lower():
                return row
        return -1
