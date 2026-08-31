"""The right-click menu on a process row.

Task Manager's Details menu, over the verified actions in
`procengine/actions.py`.

Two things are deliberate:

- **Every destructive action confirms, and names what it will hit.** "End
  process tree" on a browser can take twenty processes with it; a dialog that
  says "End 20 processes?" is a different decision from "End task?".
- **The outcome is reported, always.** A kill that was refused says so. The
  engine already returns a reason rather than a boolean precisely so this
  layer has something true to show, and silently doing nothing is the failure
  mode that makes a process manager untrustworthy.
"""
import logging
import os
import subprocess
import webbrowser
from typing import List

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMenu,
                             QMessageBox)

from .procengine.actions import (PRIORITY_LABELS, create_dump, end_process,
                                 end_process_tree, resume_process,
                                 set_affinity, set_priority, suspend_process)
from .procengine.snapshot import descendants_of

logger = logging.getLogger(__name__)


class ProcessMenu(QObject):
    """Builds and runs the context menu for the selected processes."""

    #: Something changed, so whoever owns the table should read again.
    changed = pyqtSignal()

    def __init__(self, widget) -> None:
        super().__init__(widget)
        self._widget = widget

    def show(self, pids: List[int], info, position) -> None:
        if not pids:
            return
        menu = QMenu(self._widget)
        many = len(pids) > 1

        end = menu.addAction(f"End task ({len(pids)})" if many else "End task")
        end.triggered.connect(lambda: self._end(pids))

        tree = menu.addAction("End process tree")
        tree.setEnabled(not many)
        tree.triggered.connect(lambda: self._end_tree(pids[0]))

        menu.addSeparator()
        menu.addAction("Suspend").triggered.connect(
            lambda: self._simple(pids, suspend_process, "Suspend", True))
        menu.addAction("Resume").triggered.connect(
            lambda: self._simple(pids, resume_process, "Resume", False))

        priority = menu.addMenu("Set priority")
        for key, label in PRIORITY_LABELS:
            action = priority.addAction(label)
            action.triggered.connect(
                lambda _checked=False, k=key: self._priority(pids, k))

        affinity = menu.addAction("Set affinity…")
        affinity.setEnabled(not many)
        affinity.triggered.connect(lambda: self._affinity(pids[0]))

        menu.addSeparator()
        dump = menu.addAction("Create dump file…")
        dump.setEnabled(not many)
        dump.triggered.connect(lambda: self._dump(pids[0], info))

        location = menu.addAction("Open file location")
        location.setEnabled(not many and bool(_path_of(info)))
        location.triggered.connect(lambda: self._open_location(info))

        search = menu.addAction("Search online")
        search.setEnabled(not many)
        search.triggered.connect(lambda: self._search(info))

        copy = menu.addAction("Copy details")
        copy.triggered.connect(lambda: self._copy(info))

        menu.exec(position)

    # ---- the destructive ones -------------------------------------------

    def _end(self, pids: List[int]) -> None:
        if not self._confirm(
                "End task",
                f"End {len(pids)} processes?" if len(pids) > 1
                else f"End process {pids[0]}?",
                "Unsaved work in the process will be lost."):
            return
        self._report("End task",
                     [(pid, end_process(pid)) for pid in pids])

    def _end_tree(self, pid: int) -> None:
        """Counts the tree before asking. "End 23 processes?" is a different
        question from "End task?", and the person deserves the real one."""
        try:
            members = descendants_of(pid)
        except OSError:
            members = []
        total = len(members) + 1
        if not self._confirm(
                "End process tree",
                f"End this process and its {len(members)} "
                f"descendant{'s' if len(members) != 1 else ''} "
                f"({total} in total)?",
                "Unsaved work in any of them will be lost."):
            return
        self._report("End process tree", [(pid, end_process_tree(pid))])

    def _simple(self, pids, action, title: str, confirm: bool) -> None:
        if confirm and not self._confirm(
                title, f"{title} {len(pids)} process(es)?",
                "A suspended process stops responding until it is resumed."):
            return
        self._report(title, [(pid, action(pid)) for pid in pids])

    def _priority(self, pids, level: str) -> None:
        self._report("Set priority",
                     [(pid, set_priority(pid, level)) for pid in pids])

    def _affinity(self, pid: int) -> None:
        cores = os.cpu_count() or 1
        text, ok = QInputDialog.getText(
            self._widget, "Set affinity",
            f"Cores to allow (0-{cores - 1}, comma separated):",
            text=",".join(str(core) for core in range(cores)))
        if not ok:
            return
        try:
            chosen = [int(part) for part in text.split(",") if part.strip()]
        except ValueError:
            QMessageBox.warning(self._widget, "Set affinity",
                                "That is not a list of core numbers.")
            return
        self._report("Set affinity", [(pid, set_affinity(pid, chosen))])

    def _dump(self, pid: int, info) -> None:
        name = getattr(info, "name", None) or f"process-{pid}"
        target, _filter = QFileDialog.getSaveFileName(
            self._widget, "Save dump", f"{name}-{pid}.dmp",
            "Dump files (*.dmp)")
        if not target:
            return
        self._report("Create dump", [(pid, create_dump(pid, target))])

    # ---- the harmless ones ----------------------------------------------

    def _open_location(self, info) -> None:
        path = _path_of(info)
        if not path:
            return
        try:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        except OSError as error:
            logger.warning("Could not open %s: %s", path, error)

    def _search(self, info) -> None:
        name = getattr(info, "name", "")
        if name:
            webbrowser.open(
                f"https://www.bing.com/search?q={name}+process")

    def _copy(self, info) -> None:
        if info is None:
            return
        lines = [f"Name: {info.name}", f"PID: {info.pid}"]
        for label, value in (("Path", info.details.path),
                             ("Command line", info.details.cmdline),
                             ("User", info.details.user)):
            lines.append(f"{label}: {value if value else 'not available'}")
        QApplication.clipboard().setText("\n".join(lines))

    # ---- talking to the person ------------------------------------------

    def _confirm(self, title: str, question: str, detail: str) -> bool:
        box = QMessageBox(self._widget)
        box.setWindowTitle(title)
        box.setText(question)
        box.setInformativeText(detail)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setStandardButtons(QMessageBox.StandardButton.Yes
                               | QMessageBox.StandardButton.No)
        # Defaults to No: this is the same discipline core/confirm.py applies.
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _report(self, title: str, outcomes) -> None:
        """Say what happened. Failures are never swallowed.

        Successes are silent -- the row disappearing is the feedback -- but a
        refusal that says nothing is how someone concludes the button is
        broken.
        """
        failures = [(pid, result) for pid, result in outcomes if not result.ok]
        self.changed.emit()
        if not failures:
            return
        detail = "\n".join(f"PID {pid}: {result.message}"
                           for pid, result in failures)
        box = QMessageBox(self._widget)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning)
        if len(failures) == len(outcomes):
            box.setText(f"{title} failed.")
        else:
            box.setText(f"{title} failed for {len(failures)} "
                        f"of {len(outcomes)} processes.")
        box.setInformativeText(detail)
        box.exec()


def _path_of(info):
    return getattr(getattr(info, "details", None), "path", None)
