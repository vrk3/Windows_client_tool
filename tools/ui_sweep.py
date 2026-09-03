r"""Render every registered module in BOTH themes and look at the result.

    .venv\Scripts\python.exe tools\ui_sweep.py [outdir]

Writes <outdir>/<theme>/<module>.png plus a summary table on stdout.
Renders through the real windows platform with WA_DontShowOnScreen,
so the text is real text — no window ever appears on the desktop.

Why pixels and not a stylesheet grep: a grep cannot tell which frames
actually carry text, and it cannot see a pane at all. Two checks here that a
grep cannot do:

  * THEME-BLIND: the dark and light renders are compared pixel for pixel. A
    pane that comes out identical in both is not participating in the theme —
    it has hardcoded its colours. That is the exact defect `db247db` fixed on
    the Sysinternals banner, and the one that hit the proportion bars before
    it, found both times by rendering and looking.
  * INK: the fraction of pixels differing from the pane's own dominant
    background. A pane at ~0 is blank — an empty state nobody sees content in.

Neither replaces looking at the PNGs. They rank which ones to look at first.
"""
import os
import sys
import time
import traceback
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
# NOT the offscreen platform: it reports ZERO font families on this box
# (QFontDatabase.families() == []), so every glyph renders as a .notdef box
# and a screenshot taken there has no readable text in it at all. The real
# windows platform has 288 families. WA_DontShowOnScreen below gives the full
# show/layout/paint cycle without ever mapping a window onto the desktop.
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt6.QtCore import Qt

OUT = sys.argv[1] if len(sys.argv) > 1 else "ui_sweep_out"
# ONE theme per process. Calling create_widget() twice on the same module
# instance is not what the app ever does, and a module that populates its
# layout once will hand back an EMPTY widget the second time — which reads as
# "the whole pane is invisible in light theme" when nothing of the sort is
# wrong. Run the themes as separate processes and compare the PNGs after.
THEMES = (sys.argv[2],) if len(sys.argv) > 2 else ("dark", "light")
PANE_W, PANE_H = 1150, 820

# A module that pops a modal on activate would block the sweep forever.
# Neutralise exec() and RECORD it — a modal on activate is itself a finding.
_modals = []
def _no_exec(self, *a, **k):
    _modals.append(type(self).__name__)
    return 0
QDialog.exec = _no_exec
QMessageBox.exec = _no_exec


def settle(ms=600):
    """Let queued work run without blocking forever on a module that never idles."""
    app = QApplication.instance()
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def render(widget, path):
    # The full show cycle (showEvent populates several panes) with no window.
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(PANE_W, PANE_H)
    widget.show()
    settle(500)
    pix = widget.grab()
    pix.save(path)
    return pix.toImage()


def ink_fraction(img):
    """Share of pixels that differ from the pane's dominant colour."""
    w, h = img.width(), img.height()
    step = max(1, min(w, h) // 220)
    counts = Counter()
    px = []
    for y in range(0, h, step):
        for x in range(0, w, step):
            v = img.pixel(x, y)
            counts[v] += 1
            px.append(v)
    if not px:
        return 0.0, 0
    bg, _ = counts.most_common(1)[0]
    return sum(1 for v in px if v != bg) / len(px), bg


def identical_fraction(a, b):
    """Share of sampled pixels that are the SAME in both theme renders."""
    if a.width() != b.width() or a.height() != b.height():
        return None
    w, h = a.width(), a.height()
    step = max(1, min(w, h) // 220)
    same = total = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            total += 1
            if a.pixel(x, y) == b.pixel(x, y):
                same += 1
    return same / total if total else None


def main():
    from app import App
    from main import register_all_modules

    qapp = QApplication(sys.argv)  # noqa: F841 -- bound: an unnamed one is collected
    app = App()
    register_all_modules(app)
    mods = list(app.module_registry.modules)
    print(f"{len(mods)} modules registered\n")

    for m in mods:
        try:
            m.on_start(app)
        except Exception as exc:
            print(f"  on_start FAILED {m.name}: {exc}")

    images, rows = {}, {}
    for theme in THEMES:
        app.theme.apply_theme(theme)
        os.makedirs(os.path.join(OUT, theme), exist_ok=True)
        settle(200)
        for m in mods:
            name = m.name
            safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
            path = os.path.join(OUT, theme, safe + ".png")
            t0 = time.time()
            try:
                w = m.create_widget()
                if w is None:
                    raise RuntimeError("create_widget() returned None")
                try:
                    m.on_activate()
                except Exception as exc:
                    rows.setdefault(name, {})[theme + "_activate_err"] = repr(exc)[:90]
                img = render(w, path)
                images.setdefault(name, {})[theme] = img
                ink, _ = ink_fraction(img)
                rows.setdefault(name, {})[theme + "_ink"] = ink
                rows[name][theme + "_ms"] = int((time.time() - t0) * 1000)
                w.hide()
                w.deleteLater()
            except Exception as exc:
                rows.setdefault(name, {})[theme + "_err"] = \
                    traceback.format_exception_only(type(exc), exc)[-1].strip()[:110]
            settle(60)

    print(f"{'module':<26}{'dark ink':>9}{'light ink':>10}{'same':>7}  {'ms':>6}  notes")
    print("-" * 96)
    flagged = []
    for m in mods:
        n = m.name
        r = rows.get(n, {})
        pair = images.get(n, {})
        same = identical_fraction(pair["dark"], pair["light"]) \
            if "dark" in pair and "light" in pair else None
        notes = []
        for k in ("dark_err", "light_err", "dark_activate_err", "light_activate_err"):
            if r.get(k):
                notes.append(f"{k}={r[k]}")
        if same is not None and same > 0.98:
            notes.append("THEME-BLIND")
        for t in ("dark", "light"):
            if r.get(t + "_ink") is not None and r[t + "_ink"] < 0.02:
                notes.append(f"{t} BLANK")
        d, l = r.get("dark_ink"), r.get("light_ink")
        ms = max(r.get("dark_ms", 0), r.get("light_ms", 0))
        print(f"{n[:25]:<26}{(f'{d:.3f}' if d is not None else '  -'):>9}"
              f"{(f'{l:.3f}' if l is not None else '  -'):>10}"
              f"{(f'{same:.3f}' if same is not None else '  -'):>7}  {ms:>6}  "
              f"{'; '.join(notes)}")
        if notes:
            flagged.append(n)

    print(f"\nmodals suppressed during sweep: {Counter(_modals) or 'none'}")
    print(f"flagged: {len(flagged)} of {len(mods)} -> {', '.join(flagged) if flagged else 'none'}")
    print(f"PNGs in {os.path.abspath(OUT)}")


if __name__ == "__main__":
    main()
