r"""Render ControlCards from the REAL catalog, with REAL readings, and look.

    .venv\Scripts\python.exe tools\security_card_render.py [outdir]

Writes <outdir>/cards-<theme>.png for both themes, plus every result state.
A card that has only ever been asserted about has not been looked at: this
project's own record is that the defects live in what the pane actually
draws -- a green badge on a machine three NTLM levels below what it wants, a
column that clips 393 of 544 rows, a colour frozen to one theme.

Renders through the real windows platform with WA_DontShowOnScreen (the
offscreen platform reports zero font families on this box, so every glyph
comes out as a .notdef box). No window ever appears.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QVBoxLayout, QWidget)

from core import semantic_colors  # noqa: E402
from core.semantic_colors import PANE_BACKGROUND  # noqa: E402
from modules.security_dashboard.applier import ControlResult  # noqa: E402
from modules.security_dashboard.catalog import load_catalog  # noqa: E402
from modules.security_dashboard.catalog.model import ControlState  # noqa: E402
from modules.security_dashboard.security_module import ControlCard  # noqa: E402

OUT = sys.argv[1] if len(sys.argv) > 1 else "ui-cards"

#: One of each shape the catalog actually contains.
INTERESTING = [
    ("ntlm_level", "numeric, and this machine is BELOW what it wants"),
    ("defender_threat_severe", "numeric, four of these exist"),
    ("password_min_length", "numeric, written with `net accounts`"),
    ("defender_realtime", "boolean, at desired"),
    ("tpm_present", "read-only: hardware"),
    ("bitlocker_encryption_detail", "read-only, and slow to read"),
    ("llmnr", "boolean, plain"),
    ("credential_guard", "boolean, needs a reboot"),
]


def settle(ms=400):
    app = QApplication.instance()
    deadline = time.time() + ms / 1000.0
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def apply_theme(app, theme):
    """The app's OWN stylesheet, not a background colour of our own.

    A first pass here set only `background:` on the host widget, which
    overrides the subtree and left every title and button in the dark theme's
    near-white on a light pane -- a defect in the harness that looks exactly
    like a defect in the card. The pane must be dressed the way the app
    dresses it before anything drawn in it means anything.
    """
    path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "src", "ui", "styles", f"{theme}.qss")
    with open(path, encoding="utf-8") as handle:
        app.setStyleSheet(handle.read())
    semantic_colors.set_theme(theme)


def render(widget, path, background):
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    widget.resize(720, widget.sizeHint().height() + 40)
    widget.show()
    settle()
    widget.grab().save(path)


def build(catalog, readings) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    for control_id, note in INTERESTING:
        control = catalog.get(control_id)
        if control is None:
            print(f"   (no such control: {control_id})")
            continue
        caption = QLabel(f"{control_id} — {note}")
        caption.setStyleSheet("font-size: 10px;")
        layout.addWidget(caption)
        card = ControlCard(control)
        card.set_reading(readings.get(control_id))
        layout.addWidget(card)

    # every result state, on one control, so they can be compared side by side
    plain = catalog["llmnr"]
    for state in ControlState:
        caption = QLabel(f"result: {state.value}")
        caption.setStyleSheet("font-size: 10px;")
        layout.addWidget(caption)
        card = ControlCard(plain)
        card.set_reading(True)
        card.set_result(ControlResult(
            "llmnr", state, False, True,
            "Set-MpPreference : You don't have enough permissions to perform "
            "the requested operation.\nAt line:1 char:1\n+ Set-MpPreference "
            "-DisableArchiveScanning $true\n    + CategoryInfo : NotSpecified"))
        layout.addWidget(card)

    # a staged card
    caption = QLabel("staged")
    caption.setStyleSheet("font-size: 10px;")
    layout.addWidget(caption)
    staged = ControlCard(plain)
    staged.set_reading(True)
    staged.set_staged(False)
    layout.addWidget(staged)
    return host


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)  # bound: an unnamed QApplication is collected
    catalog = load_catalog()

    readings = {}
    for control_id, _ in INTERESTING:
        control = catalog.get(control_id)
        if control is not None:
            readings[control_id] = control.read()
    print("readings off this machine:")
    for control_id, value in readings.items():
        desired = catalog[control_id].desired
        flag = "" if desired is None or value == desired else "   <- not at desired"
        print(f"   {control_id}: {value!r} (wants {desired!r}){flag}")

    for theme in ("dark", "light"):
        apply_theme(app, theme)
        host = build(catalog, readings)
        path = os.path.join(OUT, f"cards-{theme}.png")
        render(host, path, PANE_BACKGROUND[theme])
        print("wrote", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
