r"""Render the Security Dashboard itself, in both themes, and look at it.

    .venv\Scripts\python.exe tools\security_pane_render.py [outdir]

Writes <outdir>/pane-<theme>-<tab>.png. Reads the machine for real -- the
whole point is what the pane looks like holding this machine's actual answers,
not a mock's.

Run it through the PowerShell tool: a QApplication launched from the Bash tool
exits 127 with no output at all.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from modules.security_dashboard.security_module import (  # noqa: E402
    SecurityDashboardModule)

OUT = sys.argv[1] if len(sys.argv) > 1 else "ui-pane"
TABS = ["Defender", "Exploit & CVE", "History"]


def settle(ms=800):
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


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    app = QApplication(sys.argv)

    from core import semantic_colors
    for theme in ("dark", "light"):
        app.setStyleSheet(theme_sheet(theme))
        semantic_colors.set_theme(theme)

        module = SecurityDashboardModule()
        module.on_start(None)
        widget = module.create_widget()
        widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        widget.resize(1100, 780)
        widget.show()
        settle()

        for name in TABS:
            if name == "History":
                for index in range(module._tabs.count()):
                    if module._tabs.tabText(index) == "History":
                        module._tabs.setCurrentIndex(index)
                        break
                settle()
                safe = "history"
                path = os.path.join(OUT, f"pane-{theme}-{safe}.png")
                widget.grab().save(path)
                print("wrote", path)
                continue
            module.show_category_tab(name)
            # the read is on a pool thread; give it time to come back
            for _ in range(60):
                settle(250)
                tab = module._category_tabs[name]
                if tab.loaded:
                    break
            safe = name.replace(" & ", "-").replace(" ", "-").lower()
            path = os.path.join(OUT, f"pane-{theme}-{safe}.png")
            widget.grab().save(path)
            print("wrote", path)

        # and one with a few changes staged, at a NARROW width
        staged = 0
        for control in module.catalog.values():
            if control.writable and control.desired is not None and staged < 3:
                module._on_card_staged(control.id, control.desired)
                staged += 1
        widget.resize(720, 560)
        settle()
        path = os.path.join(OUT, f"pane-{theme}-staged-narrow.png")
        widget.grab().save(path)
        print("wrote", path, f"({len(module.changeset)} staged)")

        module.on_stop()
        widget.deleteLater()
        settle(200)
    return 0


if __name__ == "__main__":
    sys.exit(main())
