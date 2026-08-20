"""`IFileOperation` — spec 7.1's PRIMARY file-operation implementation.

    "`IFileOperation` (COM, via pywin32) is the primary implementation:
    progress callbacks, correct Recycle Bin semantics through
    `FOF_ALLOWUNDO`, long-path handling, and per-item error reporting.
    `SHFileOperationW` through ctypes is the fallback."

Only the fallback was ever built, so the clone had no per-item progress and no
per-item errors: `SHFileOperationW` returns ONE code for a whole batch, so
"delete these 4,000 files" either worked or did not, with no way to say which
of them failed or how far it had got.

Everything here degrades rather than raises. If pywin32 is missing, if COM
cannot be initialised, or if the shell refuses the interface, `available()`
returns False and `file_ops` uses the ctypes fallback exactly as before --
this module is an upgrade to the primary path, never a new way to fail.

Two things that are easy to get wrong and are not obvious:

1. **A non-zero HRESULT is not a failure.** The copy engine reports success
   through codes like `COPYENGINE_S_DONT_PROCESS_CHILDREN` (0x00270008), which
   is what a perfectly ordinary delete returns. Only the sign bit means
   failure. Testing `hr != 0` marks every successful item as failed.
2. **`SHCreateItemFromParsingName` does not accept a `\\\\?\\` prefix.** The
   long-path handling the spec credits IFileOperation with is internal to it;
   handing it an already-prefixed path fails to parse.
"""
import logging
import os

logger = logging.getLogger(__name__)

#: Populated on first use. None means "not yet probed".
_COM = None


def _com():
    """The pywin32 pieces, or None. Probed once, never raises."""
    global _COM
    if _COM is None:
        try:
            import pythoncom
            import win32com.server.util
            from win32com.shell import shell, shellcon
            _COM = (pythoncom, win32com.server.util, shell, shellcon)
        except Exception as exc:                    # noqa: BLE001
            logger.info("IFileOperation unavailable, using the ctypes "
                        "fallback: %s", exc)
            _COM = ()
    return _COM or None


def available() -> bool:
    return _com() is not None


def _failed(hr) -> bool:
    """HRESULT failure is the SIGN BIT, not non-zero. See the module docstring."""
    if hr is None:
        return False
    return bool(int(hr) & 0xFFFFFFFF & 0x80000000)


class ItemResult:
    """What happened to one path. `SHFileOperationW` cannot produce these."""

    __slots__ = ("path", "hr", "ok")

    def __init__(self, path: str, hr, ok: bool) -> None:
        self.path, self.hr, self.ok = path, hr, ok

    def __repr__(self) -> str:                      # pragma: no cover - debug
        return f"ItemResult({self.path!r}, hr={self.hr}, ok={self.ok})"


class Outcome:
    """The result of one batch."""

    __slots__ = ("ok", "aborted", "items", "error")

    def __init__(self, ok: bool, aborted: bool = False, items=None,
                 error: str = "") -> None:
        self.ok = ok
        self.aborted = aborted
        self.items = list(items or ())
        self.error = error

    @property
    def failures(self) -> list:
        return [i for i in self.items if not i.ok]


def _make_sink_class():
    """Build the COM sink class lazily, since it needs the shell IID.

    Every method of IFileOperationProgressSink must exist and must be listed
    in `_public_methods_`: pywin32 builds its dispatch map by looking each one
    up, and a `__getattr__` shortcut breaks that with an unpacking error
    rather than a missing-method one.
    """
    pythoncom, _util, shell, shellcon = _com()

    class _Sink:
        _public_methods_ = [
            "StartOperations", "FinishOperations",
            "PreRenameItem", "PostRenameItem",
            "PreMoveItem", "PostMoveItem",
            "PreCopyItem", "PostCopyItem",
            "PreDeleteItem", "PostDeleteItem",
            "PreNewItem", "PostNewItem",
            "UpdateProgress", "ResetTimer", "PauseTimer", "ResumeTimer",
        ]
        _com_interfaces_ = [shell.IID_IFileOperationProgressSink]

        def __init__(self, on_progress=None) -> None:
            self.items: list[ItemResult] = []
            self.total = 0
            self.done = 0
            self._on_progress = on_progress

        # -- the two that carry the information we came for ---------------

        def _record(self, item, hr) -> None:
            try:
                path = item.GetDisplayName(shellcon.SHGDN_FORPARSING)
            except Exception:                       # noqa: BLE001
                path = ""
            self.items.append(ItemResult(path, hr, not _failed(hr)))

        def PostDeleteItem(self, flags, item, hr, created):
            self._record(item, hr)

        def PostMoveItem(self, flags, item, dest, new_name, hr, created):
            self._record(item, hr)

        def UpdateProgress(self, total, so_far):
            self.total, self.done = total, so_far
            if self._on_progress is not None:
                try:
                    self._on_progress(so_far, total)
                except Exception:                   # noqa: BLE001
                    # A broken consumer must not abort a delete half-way.
                    logger.warning("IFileOperation progress callback failed",
                                   exc_info=True)

        # -- required by the interface, nothing to do ---------------------

        def StartOperations(self):
            pass

        def FinishOperations(self, hr):
            pass

        def PreRenameItem(self, flags, item, new_name):
            pass

        def PostRenameItem(self, flags, item, new_name, hr, created):
            pass

        def PreMoveItem(self, flags, item, dest, new_name):
            pass

        def PreCopyItem(self, flags, item, dest, new_name):
            pass

        def PostCopyItem(self, flags, item, dest, new_name, hr, created):
            pass

        def PreDeleteItem(self, flags, item):
            pass

        def PreNewItem(self, flags, dest, new_name):
            pass

        def PostNewItem(self, flags, dest, new_name, template, attrs, hr, item):
            pass

        def ResetTimer(self):
            pass

        def PauseTimer(self):
            pass

        def ResumeTimer(self):
            pass

    return _Sink


class _Com:
    """CoInitialize for the duration, and only CoUninitialize if we did it.

    A thread already living in an apartment must be left in it -- the UI
    thread is one, and tearing its apartment down underneath Qt would be a
    far worse bug than the one this module fixes.
    """

    def __init__(self, pythoncom) -> None:
        self._pythoncom = pythoncom
        self._ours = False

    def __enter__(self):
        try:
            self._pythoncom.CoInitialize()
            self._ours = True
        except Exception:                           # noqa: BLE001
            # Already initialised, possibly in another model. Use it as is.
            self._ours = False
        return self

    def __exit__(self, *_exc):
        if self._ours:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:                       # noqa: BLE001
                pass
        return False


def _normalise(path: str) -> str:
    r"""Strip a \\?\ prefix: SHCreateItemFromParsingName cannot parse one."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[8:]
    if path.startswith("\\\\?\\"):
        return path[4:]
    return path


def run(paths, *, operation: str = "delete", destination: str = "",
        recycle: bool = False, on_progress=None,
        silent: bool = True) -> Outcome:
    """Perform one batch through IFileOperation.

    `operation` is "delete" or "move". Returns an Outcome carrying a per-item
    result for every path the shell reported on -- which is the entire reason
    the spec prefers this over SHFileOperationW.

    `silent=False` drops FOF_SILENT and lets the shell show its OWN progress
    dialog: the same one Explorer shows, with a working Cancel, for free.
    Deleting four thousand files with no indication of progress is the case
    that motivates spec 7.1's preference in the first place. It stays True by
    default so nothing pops a window in a test run.
    """
    parts = _com()
    if parts is None:
        return Outcome(False, error="IFileOperation is unavailable.")
    pythoncom, util, shell, shellcon = parts

    with _Com(pythoncom):
        try:
            op = pythoncom.CoCreateInstance(
                shell.CLSID_FileOperation, None, pythoncom.CLSCTX_ALL,
                shell.IID_IFileOperation)
        except Exception as exc:                    # noqa: BLE001
            logger.warning("CoCreateInstance(FileOperation) failed: %s", exc)
            return Outcome(False, error=str(exc))

        flags = shellcon.FOF_NOCONFIRMATION | shellcon.FOF_NOERRORUI
        if silent:
            flags |= shellcon.FOF_SILENT
        if recycle:
            flags |= shellcon.FOF_ALLOWUNDO
        op.SetOperationFlags(flags)

        sink = _make_sink_class()(on_progress)
        cookie = None
        try:
            cookie = op.Advise(util.wrap(sink))
        except Exception as exc:                    # noqa: BLE001
            # Progress is the bonus, not the operation. Losing the sink is
            # not a reason to refuse to delete anything.
            logger.warning("IFileOperation progress sink refused: %s", exc)

        try:
            target = None
            if operation == "move":
                if not destination:
                    return Outcome(False, error="No destination given.")
                target = shell.SHCreateItemFromParsingName(
                    _normalise(destination), None, shell.IID_IShellItem)
            for path in paths:
                item = shell.SHCreateItemFromParsingName(
                    _normalise(path), None, shell.IID_IShellItem)
                if operation == "move":
                    op.MoveItem(item, target, None, None)
                else:
                    op.DeleteItem(item, None)
            op.PerformOperations()
            aborted = bool(op.GetAnyOperationsAborted())
        except Exception as exc:                    # noqa: BLE001
            logger.warning("IFileOperation %s failed: %s", operation, exc)
            return Outcome(False, items=sink.items, error=str(exc))
        finally:
            if cookie is not None:
                try:
                    op.Unadvise(cookie)
                except Exception:                   # noqa: BLE001
                    pass

    failures = [i for i in sink.items if not i.ok]
    return Outcome(ok=not failures and not aborted, aborted=aborted,
                   items=sink.items)
