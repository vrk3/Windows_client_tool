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
from ctypes import wintypes
from dataclasses import dataclass, field

from . import guardrails

logger = logging.getLogger(__name__)

FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_SILENT = 0x0004

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
            dry_run: bool = False) -> tuple[bool, str]:
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
