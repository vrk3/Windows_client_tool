r"""Measure which modules REALLY need elevation, instead of trusting the flag.

    .venv\Scripts\python.exe tools\admin_requirement_audit.py <out.json>

`start_all()` refuses to even call `on_start()` on a module whose class says
`requires_admin = True`, so unelevated users lose the whole pane -- including
everything it could have read perfectly well. That flag has already been shown
too pessimistic: Secure Boot state reads out of the registry unelevated, and
WMI returns 399 reliability records without a token.

This drives each module's READ path only -- on_start, create_widget, then
refresh_data()/on_activate() -- and records what happened. It never presses a
button and never calls an action: nothing here changes the machine.

Run it twice, once elevated, and diff. A module whose unelevated result matches
its elevated one does not need admin to show you something.
"""
import io
import json
import logging
import os
import sys
import time
import traceback
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

OUT = sys.argv[1] if len(sys.argv) > 1 else "admin_audit.json"
#: Optional: only these modules, and wait much longer for each. Some panes load
#: on workers that take far longer than a default sample -- Security Dashboard
#: was still showing "Loading..." in BOTH runs, which makes "identical" a
#: meaningless verdict rather than a reassuring one.
ONLY = [n.strip() for n in sys.argv[2].split("|")] if len(sys.argv) > 2 else None
SETTLE_MS = int(sys.argv[3]) if len(sys.argv) > 3 else 6000

# A modal would block the run forever; record that it wanted one.
_modals = []
QDialog.exec = lambda self, *a, **k: (_modals.append(type(self).__name__), 0)[1]
QMessageBox.exec = lambda self, *a, **k: (_modals.append(type(self).__name__), 0)[1]

#: Signals that mean "the OS said no", as opposed to any other failure.
DENIED = ("access is denied", "0x80041003", "winerror 5", "x_access_denied",
          "requires administrator", "requires admin", "not authorized",
          "privilege", "elevated", "administrator rights", "access denied")


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        try:
            self.records.append(f"{record.levelname} {record.name}: "
                                f"{record.getMessage()}"[:300])
        except Exception:
            pass


def settle(ms):
    app = QApplication.instance()
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def harvest_text(widget):
    """Every string the pane is actually showing.

    Ink was the first metric here and it was useless: nine modules came back
    identical to four decimal places, because both runs photographed the pane
    before its background workers had returned anything. What matters is not
    how much the pane painted but WHAT IT SAYS -- "Requires administrator" and
    "TPM 2.0" are the whole question.
    """
    from PyQt6.QtWidgets import (QAbstractItemView, QLabel, QTableWidget,
                                 QTreeWidget)
    seen = set()
    for label in widget.findChildren(QLabel):
        text = label.text().strip()
        if text and len(text) < 200:
            seen.add(text)
    for table in widget.findChildren(QTableWidget):
        for row in range(min(table.rowCount(), 40)):
            for col in range(min(table.columnCount(), 8)):
                item = table.item(row, col)
                if item and item.text().strip():
                    seen.add(item.text().strip()[:120])
    for tree in widget.findChildren(QTreeWidget):
        for i in range(min(tree.topLevelItemCount(), 40)):
            node = tree.topLevelItem(i)
            for col in range(min(tree.columnCount(), 8)):
                if node.text(col).strip():
                    seen.add(node.text(col).strip()[:120])
    return sorted(seen)


def ink(widget):
    """How much of the pane is not its own background."""
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(1100, 780)
    widget.show()
    settle(400)
    image = widget.grab().toImage()
    step = max(1, min(image.width(), image.height()) // 120)
    counts = Counter()
    for y in range(0, image.height(), step):
        for x in range(0, image.width(), step):
            counts[image.pixel(x, y)] += 1
    total = sum(counts.values())
    return round(1 - counts.most_common(1)[0][1] / total, 4) if total else 0.0


def main():
    from app import App
    from core.admin_utils import is_admin
    from main import register_all_modules
    import tempfile

    qapp = QApplication(sys.argv)
    App.instance = None
    app = App(app_data_dir=tempfile.mkdtemp())
    register_all_modules(app)

    elevated = is_admin()
    print(f"running {'ELEVATED' if elevated else 'UNELEVATED'}")

    capture = Capture()
    logging.getLogger().addHandler(capture)
    results = {}

    for module in app.module_registry.modules:
        name = module.name
        if not getattr(module, "requires_admin", False):
            continue
        if ONLY is not None and name not in ONLY:
            continue
        del capture.records[:]
        del _modals[:]
        row = {"declared_requires_admin": True}
        started = time.time()
        try:
            # Deliberately bypassing start_all()'s gate: the point is to find
            # out what the module could have done if it had been allowed to try.
            module.on_start(app)
            widget = module.create_widget()
            try:
                module.on_activate()
            except Exception as exc:
                row["on_activate_error"] = repr(exc)[:200]
            try:
                module.refresh_data()
            except Exception as exc:
                row["refresh_error"] = repr(exc)[:200]
            settle(SETTLE_MS)   # workers, not paint, are the slow part
            row["ink"] = ink(widget)
            settle(1500)
            row["text"] = harvest_text(widget)
            widget.hide()
        except Exception as exc:
            row["fatal"] = traceback.format_exception_only(
                type(exc), exc)[-1].strip()[:200]
            row["ink"] = 0.0
        row["ms"] = int((time.time() - started) * 1000)
        row["warnings"] = list(capture.records)
        row["denied_signals"] = sorted({
            token for token in DENIED
            for line in capture.records + [str(row.get("fatal", "")),
                                           str(row.get("refresh_error", "")),
                                           str(row.get("on_activate_error", ""))]
            if token in line.lower()})
        row["modals_wanted"] = list(_modals)
        results[name] = row
        print(f"  {name:<26} ink={row['ink']:<7} strings={len(row.get('text', [])):<4} "
              f"denied={','.join(row['denied_signals']) or '-'}")
        try:
            module.on_stop()
        except Exception:
            pass

    payload = {"elevated": elevated, "modules": results}
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(payload, indent=2))
    print(f"\n{len(results)} admin-gated modules audited -> {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
