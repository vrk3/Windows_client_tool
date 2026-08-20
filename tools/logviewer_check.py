"""Drive the log viewer against REAL logs, and a generated ConfigMgr one.

    .venv\\Scripts\\python.exe tools\\logviewer_check.py

Exits 1 if anything fails. Needs no display -- runs on the offscreen Qt
platform. Cleans up everything it creates.

This exists because generated test data is not the same shape as real data,
and the difference is where the bugs are. It found that every log under
C:\\Windows\\Logs is UTF-8 WITH a BOM, which decoded to a leading U+FEFF that
is invisible, is not matched by `\\s`, and so cost the first line of every
real Windows log its timestamp. No amount of synthetic input would have shown
that, because nothing generated writes a BOM.

The CMTrace path itself is still exercised only by the generated log below:
this machine has no ConfigMgr client, so `<![LOG[..]]>` records have never
been read from a real file. A run against a genuine CcmExec.log remains owed.
"""
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication          # noqa: E402

from modules.log_viewer.log_viewer_module import LogViewerWidget  # noqa: E402

#: Real logs almost every Windows box has. Absent ones are skipped, not failed.
REAL_LOGS = [
    r"C:\Windows\Logs\CBS\CBS.log",
    r"C:\Windows\Logs\DISM\dism.log",
    r"C:\Windows\Panther\setupact.log",
]

COMPONENTS = ["CcmExec", "UpdatesHandler", "ContentAccess", "PolicyAgent"]
MESSAGES = {
    1: ["Policy evaluation initiated", "Download started for content id {n}"],
    2: ["Content not found in cache, will download", "Retrying ({n})"],
    3: ["Failed to download content id {n} (0x80070005)",
        "GetDPLocations failed with 0x87d00231"],
}

failures = []


def check(label, ok, detail=""):
    print(f"    {'ok  ' if ok else 'FAIL'} {label}{'' if ok else '  -> ' + detail}")
    if not ok:
        failures.append(label)


def _generated(directory: str) -> str:
    """A realistic ConfigMgr log, with a BOM because real ones have one."""
    random.seed(11)
    path = os.path.join(directory, "CcmExec.log")
    lines = []
    for i in range(40_000):
        kind = random.choices([1, 2, 3], weights=[80, 14, 6])[0]
        message = random.choice(MESSAGES[kind]).format(n=i)
        if kind == 3 and i % 500 == 0:
            message += "\n  at CCMSetup::Install()\n  at CCMSetup::Run()"
        lines.append(
            f'<![LOG[{message}]LOG]!><time="{9 + i % 8:02d}:{i % 60:02d}:'
            f'{(i * 7) % 60:02d}.{i % 1000:03d}+000" date="08-20-2026" '
            f'component="{random.choice(COMPONENTS)}" context="" '
            f'type="{kind}" thread="{1000 + i % 40}" file="ccmexec.cpp:{i}">')
    with open(path, "w", encoding="utf-8-sig") as handle:
        handle.write("\n".join(lines) + "\n")
    return path


def _open(app, path, budget=20.0):
    widget = LogViewerWidget()
    started = time.monotonic()
    try:
        widget.open(path)
    except Exception as exc:                        # noqa: BLE001
        check(f"{os.path.basename(path)} opens", False,
              f"{type(exc).__name__}: {exc}")
        widget.stop()
        return None, 0.0
    took = time.monotonic() - started
    app.processEvents()
    return widget, took


def main() -> int:
    app = QApplication([])
    workspace = tempfile.mkdtemp(prefix="logcheck-")
    try:
        print("=== real logs on this machine ===")
        for path in REAL_LOGS:
            if not os.path.exists(path):
                print(f"  skip (absent) {path}")
                continue
            megabytes = os.path.getsize(path) / 1e6
            widget, took = _open(app, path)
            if widget is None:
                continue
            first = widget.model.entry(0)
            print(f"\n  {os.path.basename(path)} ({megabytes:.1f} MB) "
                  f"-> {widget.model.total:,} records in {took:.2f}s")
            check("records were parsed", widget.model.total > 0)
            check("no BOM leaked into the first message",
                  bool(first) and not first.message.startswith("\ufeff"))
            # The BOM bug showed up exactly here: an undated first line.
            check("the first line kept its timestamp",
                  bool(first) and first.timestamp.year > 1)
            check("opening is quick", took < 20.0, f"{took:.1f}s")
            widget.stop()

        print("\n=== a generated ConfigMgr log (the CMTrace path) ===")
        path = _generated(workspace)
        widget, took = _open(app, path)
        if widget is not None:
            print(f"  {os.path.getsize(path) / 1e6:.1f} MB "
                  f"-> {widget.model.total:,} records in {took:.2f}s")
            levels = {}
            for entry in widget.model._entries:
                levels[entry.level] = levels.get(entry.level, 0) + 1
            print(f"  severities: {levels}")
            check("all three severities parsed", len(levels) >= 3, str(levels))
            check("components were read",
                  len(widget.model.components()) > 1)
            check("the first record kept its timestamp",
                  widget.model.entry(0).timestamp.year == 2026)

            widget._level_boxes["Info"].setChecked(False)
            widget._level_boxes["Warning"].setChecked(False)
            only_errors = widget.model.rowCount()
            check("errors-only filters", 0 < only_errors < widget.model.total)
            for box in widget._level_boxes.values():
                box.setChecked(True)

            widget.find_box.setText("0x87d00231")
            widget.find_next()
            check("find located a match", widget.table.currentIndex().row() >= 0)

            before = widget.model.total
            widget.follow.setChecked(True)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write('<![LOG[appended]LOG]!><time="17:00:00.000+000" '
                             'date="08-20-2026" component="CcmExec" '
                             'context="" type="3" thread="1" file="x.cpp:1">\n')
            widget._poll()
            check("an appended line is picked up while following",
                  widget.model.total == before + 1,
                  f"{before} -> {widget.model.total}")

            # Rollover: the file is replaced under the reader.
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('<![LOG[after the roll]LOG]!>'
                             '<time="18:00:00.000+000" date="08-20-2026" '
                             'component="CcmExec" context="" type="1" '
                             'thread="1" file="x.cpp:2">\n')
            widget._poll()
            check("a rollover is noticed rather than going silent",
                  widget.model.total > before + 1,
                  "the reader kept its old offset")
            widget.stop()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
