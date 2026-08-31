r"""Several logs read as ONE timeline.

A Windows servicing failure is told across CBS, DISM, setupact and
ReportingEvents at once. Reading them one at a time means holding four clocks
in your head, so this interleaves them.

`LogSet` owns a `LogReader` per file and hands back parsed ENTRIES rather than
text, because the merge key is the timestamp and that does not exist until the
text has been parsed. `LogReader` itself is untouched -- it already does
everything one source needs, including sniffing that source's own encoding,
which is why a merged set can span UTF-8 CBS and UTF-16 ReportingEvents at
once.

Two properties of the merge key are load-bearing:

* **A continuation sorts immediately after its parent.** Continuation lines
  carry no timestamp of their own -- 9,185 of the big CBS archive's 90,714
  records are continuations, and one CSI block runs to 1,260. Interleaving
  those on their own absent timestamps would drop the other log's records into
  the middle of an operation list and destroy the block. Each record instead
  carries an EFFECTIVE timestamp: its own, or the one inherited from the
  record above it in the same file.
* **File order is authoritative within a log; timestamps only decide between
  logs.** Real logs are not perfectly monotonic, and what a file says happened
  in what order is the truth about that file. `heapq.merge` preserves each
  input's own order, so a log is never rearranged by its own clock.

No Qt here, like the reader and the parser it sits beside.
"""
import heapq
import os

from . import cmtrace_parser
from .cmtrace_parser import UNKNOWN_TIME
from .log_reader import DEFAULT_MAX_BYTES, LogReader

#: What a folder scan takes. Deliberately not `*.txt`: some installers write
#: logs as .txt, but so does every readme and licence file that would come
#: with them.
LOG_SUFFIXES = (".log", ".lo_")

#: Deliberately duplicated from `log_model` rather than imported: that module
#: imports PyQt6, and importing it here would drag Qt into the merge engine
#: and cost the headless testability this file's docstring claims.
#: `test_log_set.py` pins the two to the same number.
DEFAULT_CAP = 200_000


class LogSet:
    """One or more logs presented as a single, time-ordered timeline."""

    #: A share of the window below this cannot hold a useful slice of a
    #: record, so the split stops here however many logs are open.
    MIN_BYTES = 2 * 1024 * 1024

    def __init__(self, paths, max_bytes: int = DEFAULT_MAX_BYTES,
                 include_rolled: bool = False,
                 min_bytes: int = None, cap: int = DEFAULT_CAP) -> None:
        self.paths = list(paths)
        #: How many records are held. A set has to keep what it has read so
        #: that "load earlier" can re-merge, and unbounded that means
        #: 1,492,772 entries after paging the real 380 MB archive to its
        #: head. The model's deque used to evict for us; a set evicts itself.
        self.cap = cap
        # Every source shares one window rather than taking a whole one each:
        # twelve logs would otherwise read 384 MB and stall Open for the size
        # of the pile rather than the size of the window.
        floor = self.MIN_BYTES if min_bytes is None else min_bytes
        # The floor bounds the SPLIT and must never raise a source above the
        # window it was given: one log has to get exactly `max_bytes`, or a
        # caller asking for a small window silently gets a 2 MB one.
        self.per_source_bytes = max(min(max_bytes, floor),
                                    max_bytes // max(len(self.paths), 1))
        self._readers = [
            LogReader(path, max_bytes=self.per_source_bytes,
                      include_rolled=include_rolled)
            for path in self.paths]
        #: Everything read so far, per source, in file order.
        self._entries = [[] for _ in self.paths]

    # ---- what is open ---------------------------------------------------

    def sources(self) -> list:
        return [os.path.basename(path) for path in self.paths]

    @property
    def truncated(self) -> bool:
        return any(reader.truncated for reader in self._readers)

    def has_earlier(self) -> bool:
        return any(reader.has_earlier() for reader in self._readers)

    def earlier_bytes(self) -> int:
        """How much of the whole set sits before what is loaded."""
        return sum(reader.window_start() for reader in self._readers)

    # ---- reading --------------------------------------------------------

    def read_new(self) -> list:
        """Whatever has been appended to any source since the last call.

        Merged among themselves, so one tick's records are in time order.
        Across ticks they cannot be: a slow-writing log can deliver a record
        older than one already appended, and re-sorting 200,000 records every
        second to correct that is not affordable.
        """
        fresh = []
        for index, reader in enumerate(self._readers):
            text = reader.read_new()
            if not text:
                fresh.append([])
                continue
            parsed = self._tagged(text, index)
            self._entries[index].extend(parsed)
            fresh.append(parsed)
        self._restamp()
        merged_fresh = self._merged(fresh)
        # Following moves forwards, so what the cap drops is the OLDEST.
        self._trim(keep_oldest=False)
        return merged_fresh

    def read_earlier(self) -> list:
        """Step EVERY truncated source back once, and rebuild the timeline.

        A prepend would be wrong here. One source's earlier chunk is older
        than that source's own loaded part, but not necessarily older than
        what is already loaded from another source, so it does not belong at
        the front of the merged list. Rebuilding is also what keeps the
        inherited timestamps right: a chunk that arrives above an orphan
        continuation is exactly the parent that orphan was missing.
        """
        for index, reader in enumerate(self._readers):
            if not reader.has_earlier():
                continue
            text = reader.read_earlier()
            if not text:
                continue
            earlier = self._tagged(text, index)
            self._entries[index][:0] = earlier
        self._restamp()
        # A walk backwards, so what the cap drops is the NEWEST -- the same
        # sliding window `LogModel.prepend` gave a single log in chunk 3.
        self._trim(keep_oldest=True)
        return self.entries()

    def entries(self) -> list:
        """Everything accumulated so far, merged."""
        return self._merged(self._entries)

    # ---- internals ------------------------------------------------------

    def _tagged(self, text: str, index: int) -> list:
        """Parse one source's text and stamp each record with its file."""
        name = self.sources()[index]
        parsed = cmtrace_parser.parse(text)
        for entry in parsed:
            entry.raw["log"] = name
        return parsed

    def _restamp(self) -> None:
        """Give every record the effective timestamp it will be merged on.

        Walked per source in file order, so a record with no clock of its own
        inherits the one above it and therefore sorts immediately after it. An
        orphan at the head of a truncated slice has nothing to inherit and
        keeps the epoch, which sorts it to the front of its own source rather
        than dropping it.
        """
        for source in self._entries:
            carried = UNKNOWN_TIME
            for entry in source:
                if entry.timestamp != UNKNOWN_TIME:
                    carried = entry.timestamp
                entry.raw["merge_time"] = carried

    def _trim(self, keep_oldest: bool) -> None:
        """Hold no more than `cap` records, dropping from one end.

        Trimmed on the MERGED order and then split back out per source, so
        the cut is a straight line across the timeline rather than an
        arbitrary number of records taken from each file. Each source's own
        order survives, because the merge never reorders within a source.
        """
        if self.cap is None:
            return
        total = sum(len(source) for source in self._entries)
        if total <= self.cap:
            return
        merged = self._merged(self._entries)
        kept = merged[:self.cap] if keep_oldest else merged[-self.cap:]
        keep = {id(entry) for entry in kept}
        self._entries = [[entry for entry in source if id(entry) in keep]
                         for source in self._entries]

    @staticmethod
    def _merged(per_source) -> list:
        """Interleave sources that are each already in their own order.

        `heapq.merge` is stable and preserves each input's sequence, which is
        what keeps a log from being rearranged by its own non-monotonic clock:
        the key decides only which source goes next.
        """
        keyed = []
        for index, source in enumerate(per_source):
            if source:
                keyed.append([(entry.raw.get("merge_time", UNKNOWN_TIME),
                               index, position, entry)
                              for position, entry in enumerate(source)])
        if not keyed:
            return []
        if len(keyed) == 1:
            return [row[3] for row in keyed[0]]
        return [row[3] for row in heapq.merge(*keyed, key=lambda row: row[:3])]

    # ---- folders --------------------------------------------------------

    @classmethod
    def logs_in_folder(cls, folder: str) -> list:
        """Every log sitting directly in `folder`, in name order.

        Deliberately NOT recursive. `C:\\Windows\\Logs` has around thirty
        subfolders, and walking it would open several hundred files and a few
        hundred megabytes because someone pointed at the parent directory.
        """
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return []
        found = []
        for name in names:
            if not name.lower().endswith(LOG_SUFFIXES):
                continue
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                found.append(path)
        return found
