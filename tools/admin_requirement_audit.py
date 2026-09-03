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
import re
import sys
import time
import traceback
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox

#: Compare two runs instead of performing one:
#:     admin_requirement_audit.py --compare unelevated.json elevated.json
COMPARE = sys.argv[1:2] == ["--compare"]

OUT = sys.argv[1] if len(sys.argv) > 1 else "admin_audit.json"
#: Optional: only these modules, and wait much longer for each. Some panes load
#: on workers that take far longer than a default sample -- Security Dashboard
#: was still showing "Loading..." in BOTH runs, which makes "identical" a
#: meaningless verdict rather than a reassuring one.
ONLY = [n.strip() for n in sys.argv[2].split("|")] if len(sys.argv) > 2 else None
#: Upper bound, not a sleep. `settle_until_stable` returns as soon as the pane
#: stops changing; only a pane that never stops costs the whole budget.
SETTLE_MS = int(sys.argv[3]) if len(sys.argv) > 3 else 20000

#: Some panes load nothing until asked. Windows Features says "Click Refresh
#: to load features." and means it; System Restore shows two labels until its
#: Refresh is pressed. Pressing THOSE is still a read.
#:
#: An allowlist, never a denylist — the pane next door has twenty buttons that
#: all say "Run" and every one of them executes a fix. `_DESTRUCTIVE` is a
#: second guard, not the decision: a button must match SAFE_BUTTON *and* miss
#: every word here before it is touched.
SAFE_BUTTON = re.compile(r"\b(refresh|reload)\b", re.I)
_DESTRUCTIVE = ("create", "delete", "remove", "run", "apply", "fix", "enable",
                "disable", "start", "stop", "restart", "install", "repair",
                "clean", "scan", "restore", "properties", "reset", "kill",
                "export", "import", "save", "edit", "add", "set")


def safe_refresh_buttons(widget):
    """Enabled buttons that only ask the machine to say what it already knows."""
    from PyQt6.QtWidgets import QAbstractButton
    found = []
    for button in widget.findChildren(QAbstractButton):
        text = (button.text() or "").strip()
        if not text or not button.isEnabled():
            continue
        if not SAFE_BUTTON.search(text):
            continue
        if any(word in text.lower() for word in _DESTRUCTIVE):
            continue
        found.append((text, button))
    return found


#: A pane still showing one of these has not answered the question yet, and
#: any verdict drawn from comparing it against another run is meaningless.
LOADING = ("loading", "click refresh", "please wait", "scanning...",
           "refreshing", "working...")

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


def settle_until_stable(widget, baseline, cap_ms, quiet_ms=1200):
    """Wait for the pane to stop changing, not for the clock to run out.

    A fixed sleep cannot tell a pane that finished in 200ms from one that has
    not finished in thirty seconds. The Security Dashboard was photographed
    mid-load at 6000ms AND at 30000ms, and both runs were then called
    "identical" -- identical, and empty.

    "Held still for a moment" is not enough on its own, and getting that wrong
    reproduced the very bug this replaced: a pane whose worker has not
    delivered yet is PERFECTLY still, so the first version of this returned at
    1.5s with the same 82 unpopulated strings as before. Stillness only counts
    once something has actually landed -- hence `baseline`, the text the pane
    showed before anything was asked of it.
    """
    deadline = time.time() + cap_ms / 1000.0
    previous, unchanged_since = None, time.time()
    while time.time() < deadline:
        settle(150)
        current = harvest_text(widget)
        if current != previous:
            previous, unchanged_since = current, time.time()
            continue
        if (time.time() - unchanged_since) * 1000 < quiet_ms:
            continue
        if current == baseline:
            continue   # still as the grave, and still showing nothing
        if loading_markers(current):
            continue   # a pane can hold still BETWEEN stages: Services
                       # settled at 17 strings on its way to 297
        return current, True
    return harvest_text(widget), False


def loading_markers(texts):
    """Strings that say the pane is still working."""
    return sorted({t[:80] for t in texts
                   if any(m in t.lower() for m in LOADING)})


def normalize(texts):
    """Collapse digits, so a drifting byte count is not read as a finding.

    `317.2 MB` against `294.6 MB` and `306` against `310` are temp folders
    changing between two runs minutes apart. Diffed raw they looked like
    fourteen strings that elevation had bought.
    """
    return {re.sub(r"\d+", "#", t) for t in texts}


def harvest_text(widget):
    """Every string the pane is actually showing.

    Ink was the first metric here and it was useless: nine modules came back
    identical to four decimal places, because both runs photographed the pane
    before its background workers had returned anything. What matters is not
    how much the pane painted but WHAT IT SAYS -- "Requires administrator" and
    "TPM 2.0" are the whole question.
    """
    from PyQt6.QtWidgets import (QLabel, QTableWidget,
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


def compare(unelevated_path, elevated_path):
    """Say what elevation bought, and refuse to guess when it cannot be known.

    Two traps this exists to avoid, both of which the first pass fell into:

    - "identical unelevated" is only meaningful if BOTH runs actually
      rendered. A pane photographed twice on "Loading..." is identical and
      tells you nothing.
    - a raw text diff counts drifting byte counts as findings. Cleanup looked
      like it gained fourteen strings from elevation; it had gained
      `317.2 MB` where the other run said `294.6 MB`.
    """
    unelev = json.load(io.open(unelevated_path, encoding="utf-8"))
    elev = json.load(io.open(elevated_path, encoding="utf-8"))
    if unelev["elevated"] or not elev["elevated"]:
        sys.exit("expected an unelevated run first, then an elevated one")

    print(f"{'module':<24}{'unelev':>7}{'elev':>6}{'gained':>8}  verdict")
    print("-" * 96)
    detail = []
    for name, urow in unelev["modules"].items():
        erow = elev["modules"].get(name, {})
        utext, etext = set(urow.get("text", [])), set(erow.get("text", []))
        gained = sorted(normalize(etext) - normalize(utext))

        blocked, caveats = [], []
        for label, row in (("unelevated", urow), ("elevated", erow)):
            if not row.get("changed_from_baseline", True):
                blocked.append(f"{label} never populated")
            elif not row.get("stable", True):
                caveats.append(f"{label} never fully settled")
            elif row.get("loading"):
                caveats.append(f"{label} partly still loading")

        says_so = [t for t in utext
                   if any(w in t.lower() for w in DENIED)]

        if blocked:
            verdict = "INCONCLUSIVE — " + "; ".join(blocked)
        elif says_so:
            verdict = "NEEDS ADMIN — the pane says so itself"
        elif not gained:
            verdict = "IDENTICAL UNELEVATED — flag looks too strict"
        else:
            verdict = f"GAINS DATA (+{len(gained)})"
        if caveats and not blocked:
            verdict += "  [" + "; ".join(caveats) + "]"

        print(f"{name[:23]:<24}{len(utext):>7}{len(etext):>6}"
              f"{len(gained):>8}  {verdict}")
        if gained and not blocked:
            detail.append((name, gained, says_so))

    for name, gained, says_so in detail:
        print()
        print(f"{name} — what elevation actually adds:")
        for t in gained[:8]:
            print(f"    + {t[:92]}")
        if len(gained) > 8:
            print(f"    ... {len(gained) - 8} more")


def main():
    from app import App
    from core.admin_utils import is_admin
    from main import register_all_modules
    import tempfile

    qapp = QApplication(sys.argv)  # noqa: F841 -- bound: an unnamed one is collected
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
            widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            widget.resize(1100, 780)
            widget.show()
            settle(300)
            #: What the pane says before anything has been asked of it. If the
            #: final text still equals this, no refresh ever landed and the run
            #: says nothing about what elevation would have bought.
            row["baseline_text"] = harvest_text(widget)
            try:
                module.on_activate()
            except Exception as exc:
                row["on_activate_error"] = repr(exc)[:200]
            try:
                module.refresh_data()
            except Exception as exc:
                row["refresh_error"] = repr(exc)[:200]
            text, stable = settle_until_stable(
                widget, row["baseline_text"], SETTLE_MS)

            #: Only provoke a pane that produced nothing on its own, and only
            #: through a button that reads. Recorded either way, so a run that
            #: needed prodding is never mistaken for one that did not.
            row["clicked"] = []
            if text == row["baseline_text"]:
                candidates = safe_refresh_buttons(widget)
                row["refresh_control"] = [label for label, _ in candidates]
                for label, button in candidates:
                    button.click()
                    row["clicked"].append(label)
                if candidates:
                    text, stable = settle_until_stable(
                        widget, row["baseline_text"], SETTLE_MS)
            row["text"] = text
            row["stable"] = stable
            row["loading"] = loading_markers(text)
            row["changed_from_baseline"] = text != row["baseline_text"]
            row["ink"] = ink(widget)
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
        flags = []
        if not row.get("stable", True):
            flags.append("NEVER-SETTLED")
        if row.get("loading"):
            flags.append("STILL-LOADING")
        if not row.get("changed_from_baseline", True):
            if row.get("clicked"):
                flags.append("NEVER-POPULATED(refreshed anyway)")
            elif row.get("refresh_control") == [] or "refresh_control" in row:
                flags.append("NEVER-POPULATED(no refresh control)")
            else:
                flags.append("NEVER-POPULATED")
        if row.get("clicked"):
            flags.append("clicked=" + ",".join(row["clicked"]))
        print(f"  {name:<26} ink={row['ink']:<7} strings={len(row.get('text', [])):<4} "
              f"denied={','.join(row['denied_signals']) or '-':<20} "
              f"{' '.join(flags)}")
        try:
            module.on_stop()
        except Exception:
            pass

    payload = {"elevated": elevated, "modules": results}
    io.open(OUT, "w", encoding="utf-8").write(json.dumps(payload, indent=2))
    print(f"\n{len(results)} admin-gated modules audited -> {os.path.abspath(OUT)}")


if __name__ == "__main__":
    if COMPARE:
        compare(sys.argv[2], sys.argv[3])
    else:
        main()
