r"""Render the pending bar, the review dialog and the result report, and look.

    .venv\Scripts\python.exe tools\security_dialogs_render.py [outdir]

Uses REAL catalog entries and this machine's real readings, because what these
three have to survive is real content: a Set-MpPreference refusal is a dozen
lines of PowerShell error formatting, and a full baseline stages sixty changes
of which nineteen cannot be undone.

Run it through the PowerShell tool: a QApplication launched from the Bash tool
exits 127 with no output.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from core import semantic_colors  # noqa: E402
from modules.security_dashboard.applier import (  # noqa: E402
    BatchResult, ControlResult)
from modules.security_dashboard.catalog import load_catalog  # noqa: E402
from modules.security_dashboard.catalog.model import ControlState  # noqa: E402
from modules.security_dashboard.security_module import (  # noqa: E402
    PendingBar, ResultDialog, ReviewDialog)
from modules.security_dashboard.staging import ChangeSet, diff_against

OUT = sys.argv[1] if len(sys.argv) > 1 else "ui-dialogs"

REFUSAL = ("Set-MpPreference : You don't have enough permissions to perform "
           "the requested operation.\nAt line:1 char:1\n"
           "+ Set-MpPreference -DisableArchiveScanning $true\n"
           "+ ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n"
           "    + CategoryInfo          : NotSpecified: (MSFT_MpPreference:"
           "root\\Microsoft\\...FT_MpPreference) [Set-MpPreference],\n"
           "   CimException\n"
           "    + FullyQualifiedErrorId : HRESULT 0xc0000142,Set-MpPreference")


def settle(ms=400):
    app = QApplication.instance()
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def theme_sheet(theme):
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "src", "ui", "styles", f"{theme}.qss")
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def grab(widget, path, width, height):
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(width, height)
    widget.show()
    settle()
    widget.grab().save(path)
    print("wrote", path)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)
    catalog = load_catalog()

    print("staging a full baseline off this machine...")
    target = {cid: c.desired for cid, c in catalog.items()
              if c.desired is not None}
    baseline = diff_against(catalog, target)
    print(f"   {len(baseline)} staged, "
          f"{len(baseline.unread_before)} never readable, "
          f"{len(baseline.one_way_changes)} one-way, "
          f"reboot needed: {baseline.needs_reboot}")

    small = ChangeSet()
    for control in catalog.values():
        if control.writable and control.desired is not None and len(small) < 4:
            reading = control.read()
            if reading != control.desired:
                small.add(control, control.desired, from_value=reading)

    results = []
    for change, state in zip(
            list(baseline.changes)[:6],
            [ControlState.APPLIED_VERIFIED, ControlState.REFUSED,
             ControlState.APPLIED_UNVERIFIED,
             ControlState.APPLIED_PENDING_REBOOT,
             ControlState.APPLIED_VERIFIED, ControlState.REFUSED]):
        results.append(ControlResult(
            change.control_id, state, change.to_value,
            change.from_value if state is not ControlState.APPLIED_VERIFIED
            else change.to_value,
            REFUSAL if state is ControlState.REFUSED else
            ("takes effect after a restart"
             if state is ControlState.APPLIED_PENDING_REBOOT else "")))
    batch = BatchResult(rp_id="a1b2c3d4e5f6", results=results)

    for theme in ("dark", "light"):
        app.setStyleSheet(theme_sheet(theme))
        semantic_colors.set_theme(theme)

        bar = PendingBar()
        bar.set_changeset(baseline)
        grab(bar, os.path.join(OUT, f"pending-{theme}.png"), 1000, 60)

        review = ReviewDialog(baseline)
        grab(review, os.path.join(OUT, f"review-{theme}.png"), 820, 560)

        report = ResultDialog(batch)
        grab(report, os.path.join(OUT, f"report-{theme}.png"), 820, 560)

        small_bar = PendingBar()
        small_bar.set_changeset(small)
        grab(small_bar, os.path.join(OUT, f"pending-small-{theme}.png"),
             620, 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
