"""file_ops end to end through the REAL IFileOperation primary path (spec 7.1).

    .venv\\Scripts\\python.exe tools\treesize_fileops_check.py

Exits 1 if any check fails. Permanent deletes and moves ONLY -- nothing here
goes near the Recycle Bin, because a check that leaves items in the machine's
bin every time it runs is a check nobody will run twice.

This exists because the unit tests fake the COM outcome, and a faked outcome
could not produce the combination that actually matters: some items succeeded,
one failed, AND the shell set its aborted flag. Reporting `aborted` before the
per-item failures turned "these 3 worked, this 1 is in use by another process"
into a bare "cancelled" -- the exact failure mode per-item reporting exists to
remove. Running it against a genuinely locked file found that in one go.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from modules.treesize.actions import file_ops, ifileop

failures = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        failures.append(label)


print("IFileOperation available:", ifileop.available())

tmp = tempfile.mkdtemp(prefix="fo-real-")
try:
    # --- a batch permanent delete, through file_ops.execute --------------
    print("\n-- permanent delete of 5 files via the primary path --")
    targets = []
    for i in range(5):
        p = os.path.join(tmp, f"del{i}.bin")
        with open(p, "wb") as h:
            h.write(b"x" * 1000)
        targets.append((p, 1000))

    seen = []
    pf = file_ops.plan("Delete", targets)
    ok, message = file_ops.execute(
        pf, recycle=False, on_progress=lambda d, t: seen.append((d, t)))
    print("   message:", message)
    check("execute reported success", ok, True)
    check("every file is gone", [os.path.exists(p) for p, _ in targets],
          [False] * 5)
    check("progress callbacks arrived", bool(seen), True)
    check("progress finished at 100%", seen[-1][0] == seen[-1][1], True)

    # --- a move ----------------------------------------------------------
    print("\n-- move via the primary path --")
    src = os.path.join(tmp, "movable.bin")
    with open(src, "wb") as h:
        h.write(b"m" * 500)
    dest = os.path.join(tmp, "dest")
    os.makedirs(dest)
    pf = file_ops.plan("Move", [(src, 500)])
    ok, message = file_ops.move(pf, dest)
    print("   message:", message)
    check("move reported success", ok, True)
    check("source is gone", os.path.exists(src), False)
    check("destination has it", os.path.exists(os.path.join(dest, "movable.bin")),
          True)

    # --- a partial failure: one file held open ---------------------------
    print("\n-- a locked file must be reported PER ITEM, not as total failure --")
    good = os.path.join(tmp, "good.bin")
    locked = os.path.join(tmp, "locked.bin")
    for p in (good, locked):
        with open(p, "wb") as h:
            h.write(b"y" * 100)

    handle = open(locked, "rb+")
    try:
        # Exclusive-ish: Windows will not delete a file with an open handle
        # that denies delete sharing. Python's open() does exactly that.
        pf = file_ops.plan("Delete", [(good, 100), (locked, 100)])
        ok, message = file_ops.execute(pf, recycle=False)
        print("   message:", message.replace("\n", "\n   "))
        check("the unlocked file was deleted", os.path.exists(good), False)
        check("the locked file survived", os.path.exists(locked), True)
        check("reported as NOT ok", ok, False)
        check("names the failing path", "locked.bin" in message, True)
        check("still counts the one that worked", "1 item(s)" in message, True)
    finally:
        handle.close()

    # --- the fallback still works ---------------------------------------
    print("\n-- the ctypes fallback still works when COM is skipped --")
    fb = os.path.join(tmp, "fallback.bin")
    with open(fb, "wb") as h:
        h.write(b"f" * 100)
    pf = file_ops.plan("Delete", [(fb, 100)])
    ok, message = file_ops.execute(pf, recycle=False, prefer_com=False)
    print("   message:", message)
    check("fallback reported success", ok, True)
    check("fallback really deleted", os.path.exists(fb), False)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
    raise SystemExit(1)
print("All checks passed.")
