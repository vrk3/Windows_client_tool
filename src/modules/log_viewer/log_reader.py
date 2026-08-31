r"""Incremental reading of a log that is still being written.

Reads bytes, not lines, and keeps a byte offset so that following a file
costs only what was appended. Re-reading a 300 MB log every second is not
tailing.

Four things break naive tailers, and all four happen on a real machine:

* **The file shrinks.** SCCM rolls the log and starts a new one under the
  same name. Keeping the old offset means reading from the middle of the new
  file forever: the view goes silent and looks like a quiet machine.
* **The last line is half-written.** A CMTrace record cut down the middle
  parses as nothing, so a partial tail is held back until its newline lands.
* **A multi-byte character is split across two reads.** An incremental
  decoder keeps the orphaned bytes itself and emits the character once its
  partner arrives.
* **The log is not UTF-8.** `ReportingEvents.log` is UTF-16 LE, and decoding
  it as UTF-8 does not raise -- it returns every character with a NUL beside
  it and every newline as a blank line. The encoding is sniffed from the BOM
  instead, once, and everything after that is decoded through it.

No Qt here: everything below is testable against real temp files.
"""
import codecs
import os

#: Enough of a huge log to be useful without pulling it all into memory. The
#: newest slice is what anyone looks at first anyway.
#:
#: 32 MB is measured, not guessed. Parsing runs at ~26 MB/s here, so this is
#: about 1.2s for an explicit Open -- 64 MB would be 2.7s and 128 MB 5.4s. It
#: also yields ~170k records, just under LogModel's 200k cap, so the two
#: limits are matched rather than one quietly making the other pointless. Any
#: ConfigMgr log fits whole; a 500 MB IIS log still opens at its tail.
DEFAULT_MAX_BYTES = 32 * 1024 * 1024

#: ConfigMgr rolls `foo.log` to `foo.lo_`.
ROLLED_SUFFIX = ".lo_"

#: BOM to (codec, bytes per character). The concrete `-le`/`-be` codecs are
#: deliberate: the plain "utf-16" codec needs to see a BOM to know which way
#: round it is, and the tail of a big file never contains one. The BOM itself
#: decodes to U+FEFF and `_strip_bom` takes it off, which is the same path
#: UTF-8 already used.
#:
#: Only encodings that announce themselves are honoured. Guessing UTF-16 from
#: the shape of the bytes would eventually mis-read a UTF-8 log, and a log
#: viewer that mangles the common case to rescue the rare one is a bad trade.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32-le", 4),
    (codecs.BOM_UTF32_BE, "utf-32-be", 4),
    (codecs.BOM_UTF8, "utf-8", 1),
    (codecs.BOM_UTF16_LE, "utf-16-le", 2),
    (codecs.BOM_UTF16_BE, "utf-16-be", 2),
)

#: UTF-32's BOM starts with UTF-16's, so the four-byte forms are tested
#: first; this is how many bytes that needs.
_SNIFF_BYTES = 4


def sniff_encoding(path: str):
    """`(codec, bytes per character)` for `path`, from its BOM.

    Anything unmarked is UTF-8, which is what Windows writes when it is not
    writing UTF-16.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(_SNIFF_BYTES)
    except OSError:
        return "utf-8", 1
    for marker, codec, width in _BOMS:
        if head.startswith(marker):
            return codec, width
    return "utf-8", 1


class LogReader:
    """Yields whatever has been appended since the last call."""

    def __init__(self, path: str, max_bytes: int = DEFAULT_MAX_BYTES,
                 include_rolled: bool = False) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self.include_rolled = include_rolled
        #: True when the first read skipped the head of an oversized file, so
        #: the UI can say "showing the last N MB" rather than implying it has
        #: the whole thing.
        self.truncated = False
        self._offset = 0
        #: Where the loaded slice BEGINS, as a byte offset, and always on a
        #: real line boundary. `_offset` says how far forward the reader has
        #: got; this says how far back it has been, which is what "load
        #: earlier" walks. Zero means the head of the file is loaded and
        #: there is nothing behind it.
        self._start = 0
        self._identity = None
        self._pending = ""
        self._rolled_done = False
        self._at_start = True
        self._encoding = None
        self._char_width = 1
        self._decoder = None

    # ---- identity -------------------------------------------------------

    @staticmethod
    def _identity_of(path: str):
        """Something that changes when the file is REPLACED, not just grown.

        Size alone cannot tell a rollover from a rewrite of the same length,
        so this uses what the filesystem considers the file's identity.
        """
        try:
            info = os.stat(path)
        except OSError:
            return None
        return (getattr(info, "st_ino", 0), getattr(info, "st_dev", 0),
                info.st_ctime)

    # ---- decoding -------------------------------------------------------

    def _start_decoder(self) -> None:
        """A fresh decoder for the current encoding.

        Called again after a rollover: the replacement file gets its own
        encoding sniff, and any orphaned bytes held by the old decoder belong
        to a file that no longer exists.
        """
        self._encoding, self._char_width = sniff_encoding(self.path)
        # Logs carry whatever the writing process emitted. One bad byte costs
        # one character, never the file.
        self._decoder = codecs.getincrementaldecoder(self._encoding)(
            errors="replace")

    def _reset_position(self) -> None:
        self._offset = 0
        self._start = 0
        self._pending = ""
        self._start_decoder()

    def _first_newline(self, data: bytes) -> int:
        """Index just PAST the first newline in `data`, or -1.

        In BYTES, not characters, because the answer becomes `_start` and
        `_start` has to be a byte offset that can be seeked to.

        The newline is whatever the file's encoding makes of it -- `b"\\n"`
        under UTF-8, `b"\\n\\x00"` under UTF-16 LE, `b"\\x00\\n"` under
        UTF-16 BE. Those last two can also occur straddling two characters,
        which is why a match at an unaligned position is skipped rather than
        believed: taking it would put every character after it out of phase.
        """
        newline = "\n".encode(self._encoding)
        position = data.find(newline)
        while position != -1 and position % self._char_width:
            position = data.find(newline, position + 1)
        return -1 if position == -1 else position + len(newline)

    # ---- reading --------------------------------------------------------

    def _rolled_path(self) -> str:
        base, _extension = os.path.splitext(self.path)
        return base + ROLLED_SUFFIX

    def _read_whole(self, path: str) -> str:
        """A whole sibling file, decoded with its OWN encoding.

        The rolled half is a separate file and can have been written by a
        different version of the writer; decoding it with the live file's
        codec is a guess with nothing behind it.
        """
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError:
            return ""
        if not data:
            return ""
        codec, _width = sniff_encoding(path)
        return data.decode(codec, errors="replace").lstrip("\ufeff")

    def read_new(self) -> str:
        """Everything appended since the previous call, as text."""
        chunks = []

        if self.include_rolled and not self._rolled_done:
            # The rolled sibling is the OLDER half of one timeline, so it goes
            # first: reading them the other way round puts yesterday after
            # today. Once only -- it does not grow again.
            self._rolled_done = True
            rolled = self._read_whole(self._rolled_path())
            if rolled:
                chunks.append(rolled)

        try:
            size = os.path.getsize(self.path)
        except OSError:
            return self._strip_bom("".join(chunks))

        if self._decoder is None:
            self._start_decoder()

        identity = self._identity_of(self.path)
        if self._identity is not None and identity != self._identity:
            # Replaced, not appended to.
            self._reset_position()
        elif size < self._offset:
            # Truncated in place.
            self._reset_position()
        self._identity = identity

        start = self._offset
        skipped_head = False
        if start == 0 and size > self.max_bytes:
            start = size - self.max_bytes
            # A byte offset is not a character offset. Landing one byte out
            # of phase in a UTF-16 file shifts every character after it, and
            # the whole visible slice comes back as CJK -- on exactly the
            # files too big for anyone to sanity-check by eye.
            start -= start % self._char_width
            self.truncated = True
            skipped_head = True

        try:
            with open(self.path, "rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return self._strip_bom("".join(chunks))
        self._offset = size

        if skipped_head:
            # Seeking into the middle of a file lands mid-line, so the first
            # partial line goes. Only on the read that actually seeked:
            # `truncated` is sticky for the UI's benefit, and trimming on
            # every later read would eat each appended line as it arrived.
            #
            # Trimmed in BYTES rather than in decoded text, so that `_start`
            # can record where the kept text really begins. Trimming after
            # the decode leaves `_start` pointing into the middle of the
            # discarded line, and a backward read ending there would stop
            # mid-line too -- costing that line from BOTH halves, one line
            # per step, silently.
            cut = self._first_newline(data)
            if cut == -1:
                # The whole slice is one unterminated line. Nothing to show;
                # the window is empty and sits at the end of the file.
                self._start = size
                data = b""
            else:
                self._start = start + cut
                data = data[cut:]

        text = self._pending + self._decoder.decode(data)
        self._pending = ""

        # Hold back an unterminated final line. Split characters need no
        # handling here -- the incremental decoder keeps those bytes itself
        # and emits them once the rest of the character arrives.
        cut = text.rfind("\n")
        if cut == -1:
            self._pending = text
            text = ""
        else:
            self._pending = text[cut + 1:]
            text = text[:cut + 1]

        chunks.append(text)
        return self._strip_bom("".join(chunks))

    # ---- reading backwards ----------------------------------------------

    def has_earlier(self) -> bool:
        """Whether any of the file sits before the loaded slice."""
        return self._start > 0

    def read_earlier(self) -> str:
        """The chunk immediately BEFORE the loaded slice, oldest data last.

        The counterpart to `read_new`, and deliberately not built on it: this
        decodes one bounded chunk in a single call rather than feeding
        `_decoder`, which holds the forward stream's incremental state. A
        followed log and a "load earlier" click share one reader, so touching
        that decoder here would make the next `read_new` replay the file or
        return nothing -- a followed log going silent, which is exactly the
        defect shape the real-log pass found three of.

        The returned text always begins on a line boundary, and ends on the
        one `_start` already sits on, so a caller can concatenate the pieces
        and get the file back.
        """
        if not self.has_earlier():
            return ""

        end = self._start
        start = end
        data = b""
        cut = -1
        # Normally one pass. The loop is for the pathological case of a chunk
        # containing no newline at all: rather than discard those bytes (they
        # would be skipped by the next step and lost for good), reach further
        # back in the same call until a line boundary or the head turns up.
        while cut == -1 and start > 0:
            previous = max(0, start - self.max_bytes)
            previous -= previous % self._char_width
            try:
                with open(self.path, "rb") as handle:
                    handle.seek(previous)
                    chunk = handle.read(start - previous)
            except OSError:
                return ""
            data = chunk + data
            start = previous
            if start == 0:
                break
            cut = self._first_newline(data)

        if start == 0:
            self._start = 0
            # The head of the file carries the BOM, which decodes to an
            # invisible U+FEFF that `\s` does not match -- it would cost the
            # first record of the file its timestamp.
            return data.decode(self._encoding, errors="replace").lstrip(
                "﻿")

        self._start = start + cut
        return data[cut:].decode(self._encoding, errors="replace")

    def _strip_bom(self, text: str) -> str:
        r"""Drop a leading BOM, once, at the very start of the stream.

        Every log under C:\Windows\Logs on a real machine is UTF-8 WITH a
        BOM. Decoded, that is a leading U+FEFF -- invisible, and NOT matched
        by `\s`, so it costs the first line of every CBS, DISM and Setup log
        its timestamp. A BOM sequence later in the file is data, not a marker.
        """
        if self._at_start and text:
            self._at_start = False
            return text.lstrip("\ufeff")
        return text
