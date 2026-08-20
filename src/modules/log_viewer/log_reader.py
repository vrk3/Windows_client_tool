"""Incremental reading of a log that is still being written.

Reads bytes, not lines, and keeps a byte offset so that following a file
costs only what was appended. Re-reading a 300 MB log every second is not
tailing.

Three things break naive tailers, and all three happen constantly with
ConfigMgr logs:

* **The file shrinks.** SCCM rolls the log and starts a new one under the
  same name. Keeping the old offset means reading from the middle of the new
  file forever: the view goes silent and looks like a quiet machine.
* **The last line is half-written.** A CMTrace record cut down the middle
  parses as nothing, so a partial tail is held back until its newline lands.
* **A multi-byte character is split across two reads.** Decoding the half
  gives a replacement character that never repairs itself, so undecodable
  trailing bytes are carried forward too.

No Qt here: everything below is testable against real temp files.
"""
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
        self._identity = None
        self._pending = b""
        self._rolled_done = False
        self._at_start = True

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

    # ---- reading --------------------------------------------------------

    def _rolled_path(self) -> str:
        base, _extension = os.path.splitext(self.path)
        return base + ROLLED_SUFFIX

    def _read_whole(self, path: str) -> bytes:
        try:
            with open(path, "rb") as handle:
                return handle.read()
        except OSError:
            return b""

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
            return self._strip_bom(self._decode(b"".join(chunks)))

        identity = self._identity_of(self.path)
        if self._identity is not None and identity != self._identity:
            # Replaced, not appended to.
            self._offset = 0
            self._pending = b""
        elif size < self._offset:
            # Truncated in place.
            self._offset = 0
            self._pending = b""
        self._identity = identity

        start = self._offset
        skipped_head = False
        if start == 0 and size > self.max_bytes:
            start = size - self.max_bytes
            self.truncated = True
            skipped_head = True

        try:
            with open(self.path, "rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return self._strip_bom(self._decode(b"".join(chunks)))
        self._offset = size

        data = self._pending + data
        self._pending = b""

        if skipped_head:
            # Seeking into the middle of a file lands mid-line, so the first
            # partial line goes. Only on the read that actually seeked:
            # `truncated` is sticky for the UI's benefit, and trimming on
            # every later read would eat each appended line as it arrived.
            newline = data.find(b"\n")
            data = data[newline + 1:] if newline != -1 else b""

        # Hold back an unterminated final line, and any trailing bytes that
        # cannot be decoded yet (a multi-byte character split across reads).
        cut = data.rfind(b"\n")
        if cut == -1:
            self._pending = data
            data = b""
        else:
            self._pending = data[cut + 1:]
            data = data[:cut + 1]

        chunks.append(data)
        return self._strip_bom(self._decode(b"".join(chunks)))

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

    @staticmethod
    def _decode(data: bytes) -> str:
        # Logs carry whatever the writing process emitted. One bad byte costs
        # one character, never the file.
        return data.decode("utf-8", errors="replace")
