"""File operations (spec 7.1) with the preflight and dry-run of spec 7.2.

`SHFileOperationW` through ctypes, with `FOF_ALLOWUNDO` for recycle. The spec
names `IFileOperation` (COM) as the primary implementation and this as the
fallback; the fallback is what exists today, and it is honest about that rather
than claiming per-item progress it does not deliver.

Everything destructive goes through `plan()` first, which produces a
`Preflight` the caller shows before anything executes. `execute()` refuses to
run on a plan that was refused, so a caller cannot skip the check by accident.

Dry-run runs the whole flow and writes the manifest without touching disk.
"""
import ctypes
import logging
import os
import stat
from ctypes import wintypes
from dataclasses import dataclass, field

from . import guardrails, ifileop

logger = logging.getLogger(__name__)

FO_MOVE = 0x0001
FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_SILENT = 0x0004

#: One pass of random bytes, which is spec 7.1's default. More passes are
#: offered because Pro offers them, not because the physics is different.
DEFAULT_ERASE_PASSES = 1

#: Written per chunk rather than materialising a whole file of random bytes:
#: a 4 GB video would otherwise want 4 GB of RAM per pass.
ERASE_CHUNK = 1 << 20

#: What the dialog has to say before a secure erase. Spec 7.1 is explicit that
#: the feature ships WITH the limitation stated, rather than implying a
#: guarantee it cannot make.
SSD_CAVEAT = (
    "Secure erase does not reliably destroy data on SSDs. Wear levelling "
    "means an overwrite can land on different physical cells than the "
    "original data, which stays readable until the drive reuses it.")

#: How many paths the preflight shows before summarising the rest. Spec 7.2
#: says ten; enough to recognise a mistake, short enough to actually read.
PREVIEW_LIMIT = 10


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


@dataclass
class Preflight:
    """What is about to happen, computed before anything executes."""
    operation: str
    paths: list[str]
    total_bytes: int
    refusals: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.paths)

    @property
    def allowed(self) -> bool:
        return bool(self.paths) and not self.refusals

    @property
    def preview(self) -> list[str]:
        return self.paths[:PREVIEW_LIMIT]

    def summary(self) -> str:
        from ..ui.formatting import format_bytes
        lines = [f"{self.operation}: {self.count:,} item(s), "
                 f"{format_bytes(self.total_bytes)}"]
        lines.extend("    " + p for p in self.preview)
        if self.count > PREVIEW_LIMIT:
            lines.append(f"    … and {self.count - PREVIEW_LIMIT:,} more")
        if self.refusals:
            lines.append("")
            lines.append("Refused:")
            lines.extend("    " + r for r in self.refusals)
        return "\n".join(lines)


def plan(operation: str, targets, *, override: bool = False) -> Preflight:
    """Check every target and total it up. Nothing touches disk here.

    `targets` is an iterable of (path, size). A refused path does not silently
    drop out: it lands in `refusals`, and its presence blocks the whole plan,
    so a batch cannot half-run because one entry was dangerous.
    """
    paths: list[str] = []
    refusals: list[str] = []
    total = 0
    for path, size in targets:
        try:
            guardrails.check(path, override=override)
        except guardrails.Refusal as refusal:
            refusals.append(str(refusal))
            continue
        paths.append(path)
        total += int(size or 0)
    return Preflight(operation=operation, paths=paths, total_bytes=total,
                     refusals=refusals)


def _double_null(paths) -> str:
    """SHFileOperationW wants a double-null-terminated list of paths."""
    return "\0".join(paths) + "\0\0"


def execute(preflight: Preflight, *, recycle: bool = True,
            dry_run: bool = False, prefer_com: bool = True,
            on_progress=None, show_progress: bool = False) -> tuple[bool, str]:
    """Carry out a planned operation. Returns (ok, message).

    The manifest is logged BEFORE execution, so a mistake is reconstructible
    from the log even if the process dies mid-operation.
    """
    if not preflight.allowed:
        return False, ("Refused:\n" + "\n".join(preflight.refusals)
                       if preflight.refusals else "Nothing to do.")

    logger.info("TreeSize %s manifest (%s, %d items, %d bytes):\n%s",
                preflight.operation, "DRY RUN" if dry_run else "EXECUTE",
                preflight.count, preflight.total_bytes,
                "\n".join(preflight.paths))

    if dry_run:
        return True, (f"Dry run: {preflight.count:,} item(s) would be "
                      f"{'recycled' if recycle else 'deleted permanently'}. "
                      f"Nothing was changed.")

    missing = [p for p in preflight.paths if not os.path.exists(p)]
    if missing:
        # The scan is a snapshot; the disk has moved on. Better to say so than
        # to hand the shell a path that no longer exists.
        return False, (f"{len(missing)} item(s) no longer exist. "
                       f"Rescan and try again.")

    # Spec 7.1: IFileOperation is the PRIMARY implementation and this is the
    # fallback. It is tried first and only its unavailability -- never a
    # refusal of the operation itself -- falls through to the ctypes path.
    if prefer_com and ifileop.available():
        outcome = ifileop.run(preflight.paths, recycle=recycle,
                              on_progress=on_progress,
                              silent=not show_progress)
        if outcome.items or outcome.ok:
            return _report(outcome, preflight,
                           "Recycled" if recycle else "Permanently deleted")
        logger.info("IFileOperation reported %s; using the ctypes fallback.",
                    outcome.error or "nothing")

    flags = FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    if recycle:
        flags |= FOF_ALLOWUNDO

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = _double_null(preflight.paths)
    op.pTo = None
    op.fFlags = flags

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0:
        logger.error("SHFileOperationW failed with 0x%X", result)
        return False, f"The operation failed (code 0x{result:X})."
    if op.fAnyOperationsAborted:
        return False, "The operation was cancelled part-way through."
    verb = "Recycled" if recycle else "Permanently deleted"
    return True, f"{verb} {preflight.count:,} item(s)."


def move(preflight: Preflight, destination: str, *,
         dry_run: bool = False, prefer_com: bool = True,
         on_progress=None, show_progress: bool = False) -> tuple[bool, str]:
    """Move planned items into `destination` (spec 7.1).

    The destination is guarded too. The guardrails exist because a
    path-assembly bug could aim an operation at something unrecoverable, and
    a move INTO %SystemRoot% is exactly as bad as a delete of it: it can
    shadow a system file with a user one.
    """
    if not preflight.allowed:
        return False, ("Refused:\n" + "\n".join(preflight.refusals)
                       if preflight.refusals else "Nothing to do.")
    if not destination or not os.path.isdir(destination):
        return False, "Choose an existing destination folder."
    try:
        guardrails.check(destination, override=False)
    except guardrails.Refusal as refusal:
        return False, f"Refused: {refusal}"
    inside = _first_containing(preflight.paths, destination)
    if inside:
        # The shell answers this with a bare error code. Naming it is the
        # difference between a fixable mistake and a mystery.
        return False, f"Cannot move {inside} into itself."

    logger.info("TreeSize Move manifest (%s, %d items, %d bytes) -> %s:\n%s",
                "DRY RUN" if dry_run else "EXECUTE", preflight.count,
                preflight.total_bytes, destination,
                "\n".join(preflight.paths))
    if dry_run:
        return True, (f"Dry run: {preflight.count:,} item(s) would move to "
                      f"{destination}. Nothing was changed.")

    missing = [p for p in preflight.paths if not os.path.exists(p)]
    if missing:
        return False, (f"{len(missing)} item(s) no longer exist. "
                       f"Rescan and try again.")

    if prefer_com and ifileop.available():
        outcome = ifileop.run(preflight.paths, operation="move",
                              destination=destination, on_progress=on_progress,
                              silent=not show_progress)
        if outcome.items or outcome.ok:
            return _report(outcome, preflight, "Moved")
        logger.info("IFileOperation reported %s; using the ctypes fallback.",
                    outcome.error or "nothing")

    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_MOVE
    op.pFrom = _double_null(preflight.paths)
    op.pTo = _double_null([destination])
    op.fFlags = FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if result != 0:
        logger.error("SHFileOperationW move failed with 0x%X", result)
        return False, f"The move failed (code 0x{result:X})."
    if op.fAnyOperationsAborted:
        return False, "The move was cancelled part-way through."
    return True, f"Moved {preflight.count:,} item(s) to {destination}."


def _report(outcome, preflight, verb: str) -> tuple[bool, str]:
    """Turn an IFileOperation outcome into (ok, message).

    Per-item reporting is the entire reason spec 7.1 prefers this interface.
    SHFileOperationW hands back ONE code for the whole batch, so a partial
    failure could only ever be reported as total failure -- which, for an
    operation that already deleted three thousand of four thousand files, is
    both wrong and unhelpful.
    """
    # Failures are reported BEFORE the aborted flag, not after it. The shell
    # sets GetAnyOperationsAborted whenever it stops early, and a locked file
    # is the commonest way that happens -- so checking aborted first replaced
    # "these 3 worked, this 1 is in use by another process" with a bare
    # "cancelled", which is the precise failure mode per-item reporting exists
    # to remove. Found by locking a file and running it, not by a unit test:
    # the faked outcomes could not produce this combination.
    failures = outcome.failures
    if not failures and outcome.aborted:
        return False, "The operation was cancelled part-way through."
    if failures:
        shown = "\n".join(f"  {f.path or '(unknown)'} (0x{int(f.hr) & 0xFFFFFFFF:08X})"
                           for f in failures[:PREVIEW_LIMIT])
        more = ("\n  ... and %d more" % (len(failures) - PREVIEW_LIMIT)
                if len(failures) > PREVIEW_LIMIT else "")
        done = len(outcome.items) - len(failures)
        logger.error("TreeSize %s: %d of %d item(s) failed",
                     preflight.operation, len(failures), len(outcome.items))
        return False, (f"{verb} {done:,} item(s); {len(failures):,} failed:\n"
                       f"{shown}{more}")
    return True, f"{verb} {preflight.count:,} item(s)."


def _first_containing(paths, destination: str):
    """The first planned path that `destination` sits inside, if any."""
    target = os.path.normcase(os.path.abspath(destination))
    for path in paths:
        source = os.path.normcase(os.path.abspath(path))
        if target == source or target.startswith(source + os.sep):
            return path
    return None


def overwrite_file(path: str, passes: int = DEFAULT_ERASE_PASSES) -> int:
    """Overwrite a file in place with random bytes. Returns bytes written.

    In place, and the length preserved exactly: truncating first would leave
    the original tail sitting in clusters the filesystem has released but not
    yet reused, which is precisely what this is meant to prevent.

    A read-only attribute is cleared first. It is not a security boundary, and
    skipping such files would leave behind the very contents this feature
    exists to destroy.
    """
    size = os.path.getsize(path)
    if size == 0:
        return 0
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWRITE)
    written = 0
    with open(path, "r+b", buffering=0) as handle:
        for _ in range(max(1, passes)):
            handle.seek(0)
            remaining = size
            while remaining > 0:
                chunk = min(ERASE_CHUNK, remaining)
                handle.write(os.urandom(chunk))
                remaining -= chunk
                written += chunk
            handle.flush()
            # Without fsync the last pass can still be sitting in the page
            # cache when the file is unlinked, and never reach the disk.
            os.fsync(handle.fileno())
    return written


def secure_erase(preflight: Preflight, *, passes: int = DEFAULT_ERASE_PASSES,
                 dry_run: bool = False, on_progress=None) -> tuple[bool, str]:
    """Overwrite then unlink every planned item (spec 7.1).

    A file that could not be overwritten is NOT deleted. Deleting it anyway
    would report success while leaving the contents recoverable, which is
    worse than refusing: the user would believe the data was gone.
    """
    if not preflight.allowed:
        return False, ("Refused:\n" + "\n".join(preflight.refusals)
                       if preflight.refusals else "Nothing to do.")

    logger.info("TreeSize Secure erase manifest (%s, %d items, %d bytes, "
                "%d pass(es)):\n%s",
                "DRY RUN" if dry_run else "EXECUTE", preflight.count,
                preflight.total_bytes, passes, "\n".join(preflight.paths))
    if dry_run:
        return True, (f"Dry run: {preflight.count:,} item(s) would be "
                      f"overwritten {passes} time(s) and removed. Nothing was "
                      f"changed.")

    failures: list[str] = []
    erased = 0
    for index, path in enumerate(preflight.paths):
        if on_progress:
            on_progress(index, preflight.count)
        if os.path.isdir(path):
            erased += _erase_tree(path, passes, failures)
        else:
            erased += _erase_one(path, passes, failures)
    if on_progress:
        on_progress(preflight.count, preflight.count)

    if failures:
        head = "; ".join(failures[:3])
        return False, (f"Erased {erased:,} item(s); {len(failures):,} could "
                       f"not be erased and were left alone: {head}")
    return True, f"Securely erased {erased:,} item(s)."


def _erase_one(path: str, passes: int, failures: list) -> int:
    try:
        overwrite_file(path, passes)
    except OSError as exc:
        failures.append(f"{path}: {exc}")
        return 0
    try:
        os.remove(path)
    except OSError as exc:
        failures.append(f"{path}: {exc}")
        return 0
    return 1


def _erase_tree(root: str, passes: int, failures: list) -> int:
    erased = 0
    # Bottom-up: a directory cannot be removed until what is inside it is gone.
    for folder, _dirs, files in os.walk(root, topdown=False):
        for name in files:
            erased += _erase_one(os.path.join(folder, name), passes, failures)
        try:
            os.rmdir(folder)
        except OSError as exc:
            failures.append(f"{folder}: {exc}")
    return erased
