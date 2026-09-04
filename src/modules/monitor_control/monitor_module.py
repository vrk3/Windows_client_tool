r"""Monitor Control — one place for what your displays are doing.

Shows what the displays are doing, and changes them.

**Every change goes through `_apply_guard`** — snapshot, apply, then a
15-second countdown that puts it back unless someone confirms. Nothing here
calls a write function directly, because the failure being designed around
is a mode the monitor cannot show: the screen goes dark and the control
that would undo it is on that screen. Doing nothing has to be the safe
answer, so doing nothing reverts.

Wired: raise every display to its best refresh rate, the four Win+P
arrangements, and connect/disconnect per monitor. Not yet wired: audio
endpoint toggles and DDC brightness/input, which need their own supervised
first run.

`requires_admin` with `read_only_unelevated`: display and DDC work needs no
elevation at all, and only the audio endpoint writes do. Gating the whole
module on admin would disable a tab that is mostly usable without it — the
same reasoning as `debloat_module.py` and `store_apps_module.py`.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.widget_life import widget_is_valid
from core.worker import Worker
from modules.monitor_control import _apply_guard as guard
from modules.monitor_control import display_config as dc
from modules.monitor_control import display_writes as dw
from modules.monitor_control import view_model as vm
from modules.monitor_control._arrangement_canvas import ArrangementCanvas
from modules.monitor_control._screen_overlay import IdentifyOverlays

logger = logging.getLogger(__name__)


class _MonitorCard(QFrame):
    """One monitor: what it is, what it is doing, what it could do."""

    #: (target_id, activate)
    toggle_requested = pyqtSignal(int, bool)

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.setObjectName("monitorCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(3)

        title = QLabel(f"<b>{view.name}</b>")
        state = QLabel("● Active" if view.active else "○ Not in use")
        state.setObjectName("monitorActive" if view.active
                            else "monitorInactive")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch()
        header.addWidget(state)
        layout.addLayout(header)

        mode = QLabel(vm.describe(view))
        mode.setObjectName("muted" if not view.active else "")
        layout.addWidget(mode)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(2)
        rows = [("Connector", view.connector)]
        if view.native_resolution:
            native = view.native_resolution
            rows.append(("Native", f"{native[0]}x{native[1]}"))
        if view.rates_at_resolution:
            rows.append(("Rates here",
                         ", ".join(f"{r:g}" for r in view.rates_at_resolution)))
        if view.device_name:
            rows.append(("Device", view.device_name))
        for row, (name, value) in enumerate(rows):
            key = QLabel(name)
            key.setObjectName("muted")
            grid.addWidget(key, row, 0, Qt.AlignmentFlag.AlignRight)
            grid.addWidget(QLabel(str(value)), row, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)

        if vm.is_below_best(view):
            best = vm.best_available_rate(view)
            note = QLabel(f"Could run at {best:g} Hz here")
            note.setObjectName("statusWarning")
            layout.addWidget(note)

        actions = QHBoxLayout()
        actions.addStretch()
        toggle = QPushButton("Disconnect" if view.active else "Connect")
        toggle.setToolTip(
            "Remove this display from the desktop"
            if view.active else "Add this display to the desktop")
        toggle.clicked.connect(
            lambda _checked=False, t=view.target_id, a=not view.active:
                self.toggle_requested.emit(t, a))
        actions.addWidget(toggle)
        layout.addLayout(actions)


class MonitorControlModule(BaseModule):
    """The Monitor Control tab."""

    name = "Monitor Control"
    icon = "🖥️"
    description = "Displays, resolutions, refresh rates and monitor audio"
    requires_admin = True
    #: Reading and every display change needs no elevation; only the audio
    #: endpoint writes do, and those gate themselves through require_admin().
    read_only_unelevated = True
    group = ModuleGroup.SYSTEM

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._views: List = []
        self._workers: list = []
        self._identify = IdentifyOverlays()

    # ── UI ──

    def create_widget(self) -> QWidget:
        outer = QWidget()
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setObjectName("noticeBanner")
        self._banner.hide()
        layout.addWidget(self._banner)

        self._fix_btn = QPushButton("Use highest refresh rate")
        self._fix_btn.setToolTip(
            "Raise every display to the fastest rate it offers AT the "
            "resolution it is already using. Reverts itself in 15 seconds "
            "unless you confirm.")
        self._fix_btn.clicked.connect(self._do_raise_refresh)
        self._fix_btn.hide()
        layout.addWidget(self._fix_btn, 0, Qt.AlignmentFlag.AlignLeft)

        bar = QHBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._identify_btn = QPushButton("Identify")
        self._identify_btn.setToolTip(
            "Show a large number on each screen for a few seconds")
        self._status = QLabel("")
        self._status.setObjectName("muted")
        bar.addWidget(self._refresh_btn)
        bar.addWidget(self._identify_btn)

        # Win+P, as four buttons. What people actually want most of the time.
        bar.addSpacing(16)
        self._arrangement_buttons = {}
        for key, label in dw.ARRANGEMENT_LABELS:
            button = QPushButton(label)
            button.setToolTip(f"Switch the desktop to: {label}")
            button.clicked.connect(
                lambda _checked=False, k=key, t=label: self._do_arrangement(k, t))
            bar.addWidget(button)
            self._arrangement_buttons[key] = button

        bar.addStretch()
        bar.addWidget(self._status)
        layout.addLayout(bar)

        self._canvas = ArrangementCanvas()
        layout.addWidget(self._canvas)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()
        scroll.setWidget(self._cards_host)
        layout.addWidget(scroll, 1)

        self._refresh_btn.clicked.connect(self.refresh_data)
        self._identify_btn.clicked.connect(self._do_identify)

        # Qt already tracks this; a raw WM_DISPLAYCHANGE filter would be
        # reimplementing it. Stale state that looks authoritative is the
        # failure being avoided — this machine's configuration changed three
        # times while the module was being written.
        app = QGuiApplication.instance()
        if app is not None:
            app.screenAdded.connect(lambda _s: self.refresh_data())
            app.screenRemoved.connect(lambda _s: self.refresh_data())
            app.primaryScreenChanged.connect(lambda _s: self.refresh_data())

        self._widget = outer
        return outer

    # ── data ──

    def on_activate(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        """Re-read everything on a worker; the engines walk the driver."""
        if self._widget is None:
            return
        self._status.setText("Reading displays…")

        def _run(_worker):
            return vm.build_views()

        def _done(views):
            if not widget_is_valid(self._widget):
                return
            self._views = views
            self._render()

        def _error(message: str):
            if not widget_is_valid(self._widget):
                return
            self._status.setText(f"Could not read the display configuration: "
                                 f"{message}")
            logger.warning("Monitor Control refresh failed: %s", message)

        worker = Worker(_run)
        worker.signals.result.connect(_done)
        worker.signals.error.connect(_error)
        self._workers.append(worker)
        self._thread_pool().start(worker)

    def _thread_pool(self):
        from PyQt6.QtCore import QThreadPool
        app = getattr(self, "app", None)
        return getattr(app, "thread_pool", None) or QThreadPool.globalInstance()

    def _render(self) -> None:
        headline = vm.headline(self._views)
        self._banner.setText(headline)
        self._banner.setVisible(bool(headline))

        active = sum(1 for v in self._views if v.active)
        self._status.setText(f"{active} of {len(self._views)} monitors active")

        self._canvas.set_views(self._views)
        self._fix_btn.setVisible(bool(vm.raise_refresh_plan(self._views)))

        while self._cards_layout.count() > 1:
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, view in enumerate(self._views):
            card = _MonitorCard(view)
            card.toggle_requested.connect(self._do_toggle_monitor)
            self._cards_layout.insertWidget(index, card)

    # ── changing things ──
    #
    # Everything below goes through `_apply_guard`: snapshot, apply, then a
    # countdown that puts it back unless someone says otherwise. Nothing
    # here calls a write function directly.

    def _guarded(self, apply_fn, summary: str) -> None:
        """Apply a display change with the revert countdown around it."""
        def _snapshot():
            return dc.raw_topology_arrays()

        def _restore(arrays):
            paths, modes, npath, nmode = arrays
            ok, reason = dc.apply_raw_topology(paths, modes, npath, nmode)
            if not ok:
                raise OSError(reason)

        def _start(before):
            def _resolved(kept):
                outcome = guard.resolve(kept, before, _restore)
                self._status.setText(
                    "Change kept" if outcome is guard.Outcome.KEPT
                    else "Reverted" if outcome is guard.Outcome.REVERTED
                    else "COULD NOT REVERT — see the log")
                if outcome is guard.Outcome.REVERT_FAILED:
                    logger.error("Reverting a display change failed")
                self.refresh_data()

            self._countdown = guard.RevertCountdown(
                seconds=guard.COUNTDOWN_SECONDS, on_resolve=_resolved,
                summary=summary)
            self._countdown.start()

        result = guard.run_apply(snapshot=_snapshot, apply=apply_fn,
                                 start_countdown=_start)
        if not result.applied:
            self._status.setText(result.error or "the change was refused")
            logger.info("Display change refused: %s", result.error)

    def _do_raise_refresh(self) -> None:
        plan = vm.raise_refresh_plan(self._views)
        if not plan:
            return
        changes = [(fix.device_name, fix.resolution[0], fix.resolution[1],
                    fix.to_rate) for fix in plan if fix.device_name]
        summary = ", ".join(f"{f.name} to {f.to_rate:g} Hz" for f in plan)

        def _apply():
            ok, reason = dw.apply_modes(changes)
            if not ok:
                raise OSError(reason)

        self._guarded(_apply, summary)

    def _do_arrangement(self, key: str, label: str) -> None:
        def _apply():
            ok, reason = dw.set_arrangement(key)
            if not ok:
                raise OSError(reason)

        self._guarded(_apply, f"Display arrangement: {label}")

    def _do_toggle_monitor(self, target_id: int, activate: bool) -> None:
        view = next((v for v in self._views if v.target_id == target_id), None)
        name = view.name if view else f"target {target_id}"

        def _apply():
            ok, reason = dw.set_target_active(target_id, activate)
            if not ok:
                raise OSError(reason)

        self._guarded(
            _apply,
            f"{name}: {'connected' if activate else 'disconnected'}")

    # ── actions ──

    def _do_identify(self) -> None:
        labels = {}
        for screen, view in zip(QGuiApplication.screens(),
                                [v for v in self._views if v.active]):
            labels[screen.name()] = view.name
        self._identify.show(labels)

    # ── lifecycle ──

    def on_start(self, app) -> None:
        self.app = app

    def on_deactivate(self) -> None:
        self._identify.hide()
        self._cancel_all()

    def on_stop(self) -> None:
        self._identify.hide()
        self._cancel_all()

    def _cancel_all(self) -> None:
        for worker in self._workers:
            worker.cancel()
        self._workers.clear()

    def get_status_info(self) -> str:
        active = sum(1 for v in self._views if v.active)
        return f"Monitor Control — {active} active"
