r"""What the Security Dashboard costs before anyone has read anything.

    .venv\Scripts\python.exe tools\security_pane_timing.py

Two numbers, and they are different things:

* **build** -- creating the pane and its tabs. Pure widget construction, no
  machine access at all. All seven tabs built up front was 2.99s for 149
  cards: a three-second freeze the moment someone clicks the module in the
  sidebar, with nothing on screen to show for it.
* **read** -- one tab's controls, actually asked of Windows. This is the one
  the snapshot layer and the per-tab laziness exist to keep small.

Run it through the PowerShell tool: a QApplication launched from the Bash
tool exits 127 with no output.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from modules.security_dashboard.security_module import (  # noqa: E402
    SecurityDashboardModule)


def main() -> int:
    app = QApplication(sys.argv)  # bound: an unnamed one is collected
    module = SecurityDashboardModule()

    t0 = time.time()
    module.on_start(None)
    load = time.time() - t0

    t0 = time.time()
    widget = module.create_widget()
    build = time.time() - t0

    print(f"load_catalog   {load:6.2f}s   {len(module.catalog)} controls")
    print(f"create_widget  {build:6.2f}s   "
          f"{sum(len(t.cards) for t in module._category_tabs.values())} cards "
          f"built over {len(module._category_tabs)} tabs")

    print("\nper tab, first show (build + read):")
    total = 0.0
    for name, tab in module._category_tabs.items():
        t0 = time.time()
        tab.build_cards(module._on_card_staged)
        built = time.time() - t0
        t0 = time.time()
        readings = {c.id: c.read() for c in tab.controls}
        read = time.time() - t0
        total += built + read
        unread = sum(1 for v in readings.values() if v is None)
        flag = "   <- over 3s" if built + read > 3 else ""
        print(f"   {name:22} {len(tab.controls):3} controls  "
              f"build {built:5.2f}s  read {read:5.2f}s  "
              f"({unread} unreadable){flag}")
    print(f"\nevery tab, built and read once: {total:.1f}s")
    widget.deleteLater()
    module.on_stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
