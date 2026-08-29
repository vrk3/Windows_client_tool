"""
Security Dashboard — interactive security posture monitoring and control.

Provides real-time status of Windows security features with the ability
to toggle Defender settings, firewall profiles, SmartScreen, and more.
Each toggle stores its previous state for per-setting revert.
"""

import re
from datetime import datetime
from functools import partial
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QFrame, QProgressBar, QCheckBox, QLineEdit,
    QTabWidget, QTableWidget, QTableWidgetItem,
    QGroupBox, QScrollArea, QSizePolicy, QStackedWidget,
)
from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor, QFont

try:
    import sip as _sip
    _widget_valid = lambda w: w is not None and not _sip.isdeleted(w)
except ImportError:
    _widget_valid = lambda w: w is not None

import logging
logger = logging.getLogger(__name__)

from core.base_module import BaseModule
from core.semantic_colors import semantic
from core.module_groups import ModuleGroup
from core.search_provider import FilterField, SearchProvider, SearchQuery, SearchResult
from core.worker import Worker, COMWorker
from ui.error_banner import ErrorBanner
from modules.security_dashboard import snapshots
from modules.security_dashboard.catalog import load_catalog
from modules.security_dashboard.catalog.model import Category, ControlState
from modules.security_dashboard.staging import ChangeSet
from modules.security_dashboard.security_reader import (
    get_all_security_status,
    get_overview_status,
    get_security_events,
    run_quick_scan,
    run_update_definitions,
    check_defender_signatures,
    set_defender_realtime,
    set_defender_cloud,
    set_defender_sample_submission,
    set_pua_protection,
    set_controlled_folder_access,
    set_tamper_protection,
    set_network_protection_defender,
    set_firewall_profile,
    set_smartscreen,
    set_lsass_protection,
    set_uac_level,
    set_defender_behavior_monitoring,
    set_defender_script_scanning,
    set_defender_archive_scanning,
    set_defender_ioav,
    set_defender_removable_drive_scanning,
    set_defender_catchup_scans,
    set_llmnr,
    set_wpad,
    set_wdigest_credential_caching,
    set_ntlm_level,
    set_pagefile_clear,
    set_ps_script_block_logging,
    # CVE checks (for CVEs tab)
    check_spectre_v2, check_meltdown, check_ssbd, check_l1tf, check_mds,
    check_printnightmare, check_zerologon, check_petitpotam, check_follina,
    check_blacklotus, check_kerberos_armoring, check_credential_guard_vbs,
    check_ntlm_relay_protection, check_smb_ghost,
)

COLOR_MAP = {
    "green": "#27AE60",
    "amber": "#E67E22",
    "red":   "#E74C3C",
}

# ── ControlCard: a catalog entry, rendered ─────────────────────────────────

class ControlCard(QFrame):
    """One `SecurityControl`, drawn. It stages; it never writes.

    `_ToggleCard` below is the thing this replaces, and the differences are
    the point:

    * **It renders by VALUE, not by truthiness.** 12 of the 149 controls are
      numeric -- NTLM level, cached logons, minimum password length, cloud
      block level, the four threat actions. This machine's `ntlm_level` reads
      3 and wants 5; drawn as a toggle that is a green "On".
    * **A numeric control's action is "set it to what the catalog
      recommends"**, never "the opposite of what it reads". `not 3` is False,
      False resolves to `off_steps`, and `ntlm_level`'s off_steps write the 3
      it already has -- while `defender_threat_severe`'s write
      `-SevereThreatDefaultAction None`, turning the severe-threat action off.
    * **Green means "at what the catalog wants"**, which is `desired`, not
      whatever colour the reader felt like. 14 controls have `desired=None`
      and are legitimately amber or red; those are not problems and are not
      coloured as though they were (Ruling 6).
    * **A reading of None is "Unknown"**, never "Off". A refused read is not
      an unset value.
    * **No hex literal anywhere.** Colours are resolved through
      `semantic()` at every render, so a theme change is followed rather than
      frozen at build time.
    """

    #: (control_id, target value). The pane stages it; nothing is written here.
    staged = pyqtSignal(str, object)

    _UNREAD = object()

    def __init__(self, control, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._control = control
        self._reading: Any = self._UNREAD
        self._staged_to: Any = self._UNREAD
        self._build_ui()

    # -- construction ------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(4)

        top = QHBoxLayout()
        self.title_label = QLabel(self._control.title)
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        top.addWidget(self.title_label, 1)

        self.status_badge = QLabel("—")
        self.status_badge.setObjectName("controlStatusBadge")
        top.addWidget(self.status_badge)
        root.addLayout(top)

        self.description_label = QLabel(self._control.description)
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName("controlDescription")
        root.addWidget(self.description_label)

        # Prefixed and italic, because a read-only card has no button either:
        # rendered as plain body text this sentence is indistinguishable from
        # the description above it, and the two say completely different
        # things -- what the setting is, versus why nobody can change it.
        reason = self._control.read_only_reason
        self.reason_label = QLabel(f"Read-only — {reason}" if reason else "")
        self.reason_label.setWordWrap(True)
        self.reason_label.setObjectName("controlReason")
        italic = self.reason_label.font()
        italic.setItalic(True)
        self.reason_label.setFont(italic)
        self.reason_label.setVisible(bool(reason))
        root.addWidget(self.reason_label)

        self.staged_label = QLabel("")
        self.staged_label.setWordWrap(True)
        root.addWidget(self.staged_label)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setVisible(False)
        root.addWidget(self.result_label)

        row = QHBoxLayout()
        row.addStretch(1)
        self.toggle_button = QPushButton(self._action_text())
        self.toggle_button.clicked.connect(self._on_action)
        self.toggle_button.setEnabled(self._control.writable)
        self.toggle_button.setVisible(self._control.writable)
        row.addWidget(self.toggle_button)
        root.addLayout(row)

        self._paint()

    # -- the value this control would be staged to -------------------------

    def _is_numeric(self) -> bool:
        """A control whose value is a number, not an on/off.

        Decided from the reading when there is one and from `desired`
        otherwise, so a control that has not been read yet still offers the
        right action.
        """
        for value in (self._reading, self._control.desired):
            if value is self._UNREAD or value is None:
                continue
            return not isinstance(value, bool)
        return False

    def _target(self) -> Any:
        """What a click would stage, or None if a click cannot mean anything.

        A numeric control has exactly one sensible target: what the catalog
        recommends. A boolean one flips -- and if it could not be read, it
        goes to `desired`, or to True when the catalog has no opinion either.
        """
        if not self._control.writable:
            return None
        if self._is_numeric():
            return self._control.desired
        if isinstance(self._reading, bool):
            return not self._reading
        if isinstance(self._control.desired, bool):
            return self._control.desired
        return True

    def _action_text(self) -> str:
        target = self._target()
        if target is None:
            return "Not changeable"
        if self._is_numeric():
            return f"Set to {target}"
        return "Turn off" if target is False else "Turn on"

    # -- rendering ---------------------------------------------------------

    def _reading_text(self) -> str:
        if self._reading is self._UNREAD:
            return "—"
        if self._reading is None:
            return "Unknown"
        if isinstance(self._reading, bool):
            return "On" if self._reading else "Off"
        return str(self._reading)

    def _reading_meaning(self) -> Optional[str]:
        """Which semantic colour the badge takes, or None for no opinion.

        Keyed off `desired`, never off the reader's own colour: a control the
        catalog has no opinion about is not a problem whatever it reads, and
        one that is away from what the catalog wants is not a success however
        truthy its value.
        """
        if self._reading is self._UNREAD:
            return None
        if self._reading is None:
            return "info"
        if self._control.desired is None:
            return None
        return "success" if self._reading == self._control.desired else "warning"

    def _paint(self) -> None:
        self.status_badge.setText(self._reading_text())
        meaning = self._reading_meaning()
        self.status_badge.setStyleSheet(
            f"font-weight: bold; padding: 2px 8px; color: {semantic(meaning)};"
            if meaning else "font-weight: bold; padding: 2px 8px;")
        if self._control.writable:
            self.toggle_button.setText(self._action_text())
            self.toggle_button.setEnabled(self._target() is not None)

    # -- the pane's side of it ---------------------------------------------

    def set_reading(self, value: Any) -> None:
        self._reading = value
        self._paint()

    def set_staged(self, to_value: Any) -> None:
        self._staged_to = to_value
        shown = ("Unknown" if to_value is None else
                 ("On" if to_value is True else
                  "Off" if to_value is False else str(to_value)))
        self.staged_label.setText(f"Staged: will be {shown}")
        self.staged_label.setStyleSheet(f"color: {semantic('info')};")

    def clear_staged(self) -> None:
        self._staged_to = self._UNREAD
        self.staged_label.setText("")
        self.staged_label.setStyleSheet("")

    def set_result(self, result) -> None:
        """Render what came back from `apply_batch` or `revert_batch`.

        The reason is a Windows command's own complaint and runs to a dozen
        lines of PowerShell error formatting -- measured, on a refused
        Set-MpPreference. The first line goes on the card; the whole thing is
        the tooltip, because it is the evidence.
        """
        state = result.state
        first_line = (result.reason or "").strip().splitlines()
        first_line = first_line[0] if first_line else ""

        if state is ControlState.APPLIED_VERIFIED:
            text, meaning = "Applied, and the machine confirms it", "success"
        elif state is ControlState.APPLIED_PENDING_REBOOT:
            text, meaning = ("Applied — takes effect after a restart, so it "
                             "cannot be checked yet"), "info"
        elif state is ControlState.APPLIED_UNVERIFIED:
            text = (f"Not confirmed: asked for {result.requested!r}, the "
                    f"machine still reads {result.observed!r}")
            meaning = "warning"
        else:
            text, meaning = f"Refused: {first_line}", "error"

        self.result_label.setText(text)
        self.result_label.setToolTip(result.reason or "")
        self.result_label.setStyleSheet(f"color: {semantic(meaning)};")
        self.result_label.setVisible(True)
        self.clear_staged()
        # `observed` is a reading taken after the write, so it is now the
        # freshest thing anyone has about this control -- fresher than the
        # badge, which still shows what the pane read before the batch ran.
        # Rendered without it, a card that applied False sits there saying
        # "On" beside "Applied, and the machine confirms it". Found by
        # rendering the card and looking at it; no assertion here caught it.
        self.set_reading(result.observed)

    def clear_result(self) -> None:
        self.result_label.setText("")
        self.result_label.setVisible(False)

    def _on_action(self) -> None:
        target = self._target()
        if target is None:
            return
        self.staged.emit(self._control.id, target)


# ── Reusable Toggle Card ───────────────────────────────────────────────────



# ── Read-Only Status Card ──────────────────────────────────────────────────

class _StatusCard(QFrame):
    """Read-only coloured status card with title, status badge, and detail rows."""

    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)

        self._title_lbl = QLabel(title)
        font = self._title_lbl.font()
        font.setBold(True)
        pt = font.pointSize()
        if pt > 0:
            font.setPointSize(pt + 1)
        self._title_lbl.setFont(font)
        layout.addWidget(self._title_lbl)

        self._status_lbl = QLabel("Loading...")
        self._status_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self._status_lbl)

        self._details_layout = QVBoxLayout()
        layout.addLayout(self._details_layout)
        layout.addStretch()

    def update_status(self, data: dict):
        color = COLOR_MAP.get(data.get("color", "amber"), "#888")
        status = data.get("status", "Unknown")
        self._status_lbl.setText(status)
        self._status_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {color};")
        self.setStyleSheet(f"QFrame {{ border-left: 4px solid {color}; }}")

        # Clear and rebuild detail rows
        while self._details_layout.count():
            item = self._details_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for k, v in data.get("details", []):
            row = QHBoxLayout()
            k_lbl = QLabel(f"{k}:")
            k_lbl.setStyleSheet("color: gray;")
            v_lbl = QLabel(str(v))
            row.addWidget(k_lbl)
            row.addStretch()
            row.addWidget(v_lbl)
            container = QWidget()
            container.setLayout(row)
            self._details_layout.addWidget(container)


# ── Main Module ────────────────────────────────────────────────────────────

class _CategoryTab(QWidget):
    """One `Category`, drawn as a scrolling column of `ControlCard`s.

    Holds no reading logic of its own -- the pane reads, and hands the values
    down. What it does own is the "as of" line, because a pane that shows a
    value without saying when it read it invites someone to trust a number
    from twenty minutes ago.
    """

    def __init__(self, category, controls, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.category = category
        self.controls = sorted(controls, key=lambda c: c.title.lower())
        self.cards: Dict[str, ControlCard] = {}
        self.built = False
        self.loaded = False
        self.reading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        self._status = QLabel("Not read yet")
        self._count = QLabel("")
        header.addWidget(self._status, 1)
        header.addWidget(self._count)
        root.addLayout(header)

        # The page is permanent and empty; the cards go into it on first show.
        # Never removeTab/insertTab to swap in a lazily built widget -- doing
        # that on the current index re-fires currentChanged and re-enters the
        # handler that asked for the build.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._inner = QWidget()
        self._column = QVBoxLayout(self._inner)
        self._column.setContentsMargins(0, 0, 0, 0)
        self._scroll.setWidget(self._inner)
        root.addWidget(self._scroll, 1)

    def build_cards(self, on_staged) -> None:
        """Create this tab's cards. Once, and only when it is shown.

        Building all seven tabs up front costs **2.99s** on this machine for
        149 cards -- a three-second freeze the moment someone clicks Security
        Dashboard in the sidebar, before a single value has been read. Measured
        with tools/security_pane_timing.py, not guessed.
        """
        if self.built:
            return
        self.built = True
        for control in self.controls:
            card = ControlCard(control)
            card.staged.connect(on_staged)
            self.cards[control.id] = card
            self._column.addWidget(card)
        # Without this the cards share the surplus height equally and every
        # one of them stretches -- the d57cdf2 layout trap. The stretch takes
        # the leftover space instead.
        self._column.addStretch(1)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_match_count(self, shown: int, total: int) -> None:
        self._count.setText("" if shown == total else f"{shown} of {total}")


class SecurityDashboardModule(BaseModule):
    name = "Security Dashboard"
    icon = "\U0001f6e1\ufe0f"
    description = "Windows security status overview with controls"
    requires_admin = True
    group = ModuleGroup.SYSTEM

    def __init__(self):
        super().__init__()
        self._workers: list = []
        self._overview_worker = None
        self._loaded_overview = False
        self._loaded_events = False
        #: The catalog, and the pane's own copy of what it last read. Both
        #: are what staging and the filters work off, so neither the machine
        #: nor a snapshot is consulted again to answer "is this a problem".
        self.catalog: Dict[str, Any] = {}
        self._readings: Dict[str, Any] = {}
        self._changeset = ChangeSet()
        self._category_tabs: Dict[str, Any] = {}
        self._tab_names: Dict[int, str] = {}
        self._events_progress: Optional[QProgressBar] = None
        self._events_table: Optional[QTableWidget] = None

    def get_refresh_interval(self) -> Optional[int]:
        """No timer. Refresh is a button.

        The Overview sweep took 37.3s against a 30s timer, so the timer
        relaunched an unfinished sweep for as long as the tab stayed
        open. Seven category tabs over 149 controls is that shape again,
        with more ways to lose. Nothing here refreshes unless someone
        asks it to.
        """
        return None

    def get_search_provider(self) -> Optional[SearchProvider]:
        return SecuritySearchProvider()

    def refresh_data(self) -> None:
        self._refresh_overview()

    def on_start(self, app) -> None:
        self.app = app
        self.catalog = load_catalog()

    # ── Widget Creation ───────────────────────────────────────────────────

    def create_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Error banner
        self._error_banner = ErrorBanner()
        self._error_banner.hide()
        layout.addWidget(self._error_banner)

        # Header
        header_row = QHBoxLayout()
        self._banner = QLabel("Security Status")
        font = self._banner.font()
        font.setBold(True)
        pt = font.pointSize()
        if pt > 0:
            font.setPointSize(pt + 2)
        self._banner.setFont(font)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._manual_refresh)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        header_row.addWidget(self._banner, 1)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)
        layout.addWidget(self._progress)

        layout.addWidget(self._build_filter_bar())

        # One tab per catalog category, plus Overview and the event log.
        # "Controls" and "Advanced" are gone: they were a grab bag of twenty
        # hand-wired cards, and which of the two a setting landed in was a
        # matter of when it was added.
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_overview_tab(), "Overview")
        for category in Category:
            # "&" is a keyboard mnemonic to Qt, so "Device & Boot" renders as
            # "Device  Boot" with the B underlined -- four of the seven tab
            # names carry one. Escaped for display; the index-to-name map
            # below is what the code looks names up by, because tabText()
            # hands back the escaped string.
            index = self._tabs.addTab(self._build_category_tab(category),
                                      category.value.replace("&", "&&"))
            self._tab_names[index] = category.value
        self._tabs.addTab(self._build_events_tab(), "Security Events")
        # Connected AFTER the addTab loop: addTab fires currentChanged
        # synchronously for the first tab added, which would kick off a read
        # during create_widget.
        self._tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tabs, 1)

        return w

    # ── Tab 1: Overview ───────────────────────────────────────────────────

    def _build_overview_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        # Core security grid (2x2)
        core_label = QLabel("Core Security")
        core_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0b0;")
        layout.addWidget(core_label)

        grid = QGridLayout()
        grid.setSpacing(12)
        self._defender_card = _StatusCard("\U0001f6e1 Windows Defender")
        self._firewall_card = _StatusCard("\U0001f525 Firewall")
        self._bitlocker_card = _StatusCard("\U0001f4be BitLocker")
        self._boot_card = _StatusCard("\U0001f510 Secure Boot & TPM")
        grid.addWidget(self._defender_card, 0, 0)
        grid.addWidget(self._firewall_card, 0, 1)
        grid.addWidget(self._bitlocker_card, 1, 0)
        grid.addWidget(self._boot_card, 1, 1)
        layout.addLayout(grid)

        # Additional checks grid
        adv_label = QLabel("Additional Protections")
        adv_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #b0b0b0;")
        layout.addWidget(adv_label)

        grid2 = QGridLayout()
        grid2.setSpacing(12)
        self._uac_card = _StatusCard("\U0001f6e1 UAC")
        self._smartscreen_card = _StatusCard("\U0001f4e7 SmartScreen")
        self._hvci_card = _StatusCard("\U0001f512 HVCI / Memory Integrity")
        self._credguard_card = _StatusCard("\U0001f6f0 Credential Guard")
        self._lsass_card = _StatusCard("\U0001f512 LSASS Protection")
        self._rdp_card = _StatusCard("\U0001f310 Remote Desktop")
        self._smbv1_card = _StatusCard("\U0001f5c4 SMBv1")
        self._tamper_card = _StatusCard("\U0001f512 Tamper Protection")
        self._applocker_card = _StatusCard("\U0001f4dc AppLocker / WDAC")
        self._winhello_card = _StatusCard("\U0001f440 Windows Hello")
        grid2.addWidget(self._uac_card, 0, 0)
        grid2.addWidget(self._smartscreen_card, 0, 1)
        grid2.addWidget(self._hvci_card, 1, 0)
        grid2.addWidget(self._credguard_card, 1, 1)
        grid2.addWidget(self._lsass_card, 2, 0)
        grid2.addWidget(self._rdp_card, 2, 1)
        grid2.addWidget(self._applocker_card, 3, 0)
        grid2.addWidget(self._winhello_card, 3, 1)
        grid2.addWidget(self._smbv1_card, 4, 0)
        grid2.addWidget(self._tamper_card, 4, 1)
        layout.addLayout(grid2)

        layout.addStretch()
        scroll.setWidget(tab)
        return scroll

    def _refresh_overview(self):
        """Load overview data in background.

        One sweep at a time. The auto-refresh timer fires every 30s and the
        sweep is not guaranteed to be quicker than that on every machine;
        without this guard each tick stacked another COMWorker on the global
        QThreadPool and another entry on `self._workers`, neither of which was
        ever removed.
        """
        if self._overview_worker is not None:
            logger.debug("overview sweep already in flight — skipping refresh")
            return

        self._progress.show()

        worker = COMWorker(lambda _w: get_overview_status())
        self._overview_worker = worker
        self._workers.append(worker)

        def on_finished():
            self._overview_worker = None
            try:
                self._workers.remove(worker)
            except ValueError:
                pass   # cancel_all_workers() cleared the list first

        worker.signals.finished.connect(on_finished)

        def on_result(data: dict):
            if not _widget_valid(self._banner):
                return
            self._progress.hide()

            # Core cards
            self._defender_card.update_status(data["defender"])
            self._firewall_card.update_status(data["firewall"])
            self._bitlocker_card.update_status(data["bitlocker"])
            self._boot_card.update_status(data["secure_boot_tpm"])

            # Additional cards
            self._uac_card.update_status(data["uac"])
            self._smartscreen_card.update_status(data["smartscreen"])
            self._hvci_card.update_status(data["hvci"])
            self._credguard_card.update_status(data["credential_guard"])
            self._lsass_card.update_status(data["lsass_protection"])
            self._tamper_card.update_status(data["tamper_protection"])
            self._rdp_card.update_status(data["rdp"])
            self._smbv1_card.update_status(data["smbv1"])
            self._applocker_card.update_status(data.get("applocker", {}))
            self._winhello_card.update_status(data.get("windows_hello", {}))

            # Overall banner
            all_data = [data["defender"], data["firewall"],
                        data["bitlocker"], data["secure_boot_tpm"]]
            colors = [d.get("color", "amber") for d in all_data]
            if all(c == "green" for c in colors):
                overall, col = "Secure", "#27AE60"
            elif any(c == "red" for c in colors):
                overall, col = "Issues Detected", "#E74C3C"
            else:
                overall, col = "Warnings", "#E67E22"
            self._banner.setText(f"Security Status — {overall}")
            self._banner.setStyleSheet(f"font-weight: bold; color: {col};")

        def on_error(err):
            if not _widget_valid(self._banner):
                return
            self._progress.hide()
            emsg = str(err[1]) if isinstance(err, tuple) else str(err)
            self._error_banner.set_error(f"Failed to load security status: {emsg}")
            self._error_banner.show()
            self._banner.setText("Security Status — Error")

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

        QThreadPool.globalInstance().start(worker)

    # ── Tab 2: Controls ───────────────────────────────────────────────────




    # ── Tab 3: Advanced ────────────────────────────────────────────────────



    # ── Tab 4: CVEs ───────────────────────────────────────────────────────



    # ── Tab 5: Security Events ────────────────────────────────────────────

    def _build_events_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)

        events_group = QGroupBox("Recent Security Events")
        events_layout = QVBoxLayout(events_group)
        self._events_progress = QProgressBar()
        self._events_progress.setFixedHeight(3)
        self._events_progress.setRange(0, 0)
        self._events_progress.hide()
        events_layout.addWidget(self._events_progress)

        self._events_table = QTableWidget()
        self._events_table.setColumnCount(4)
        self._events_table.setHorizontalHeaderLabels(
            ["Time", "Event ID", "Description", "Logon Info"])
        self._events_table.setColumnWidth(0, 160)
        self._events_table.setColumnWidth(1, 80)
        self._events_table.setColumnWidth(2, 320)
        self._events_table.setColumnWidth(3, 180)
        self._events_table.setAlternatingRowColors(True)
        self._events_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._events_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._events_table.horizontalHeader().setStretchLastSection(True)
        self._events_table.setStyleSheet("""
            QTableWidget { background: #2d2d2d; color: #e0e0e0;
                           border: 1px solid #3c3c3c; border-radius: 4px; }
            QTableWidget::item { padding: 4px; }
            QTableWidget::item:selected { background: #094771; }
            QHeaderView::section { background: #3c3c3c; color: #b0b0b0;
                                   padding: 4px; border: none; }
        """)
        events_layout.addWidget(self._events_table)

        # Empty state
        self._events_empty = QLabel("No recent security events found.\n"
                                    "Click Refresh to load events from the Security log.")
        self._events_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._events_empty.setStyleSheet("color: #888; padding: 40px;")
        events_layout.addWidget(self._events_empty)
        self._events_empty.hide()

        layout.addWidget(events_group, 1)
        return tab

    def _load_events(self):
        """Load security events in background."""
        if not _widget_valid(self._events_progress):
            return
        self._events_progress.show()

        worker = Worker(lambda _w: get_security_events(30))
        self._workers.append(worker)

        def on_result(events: list):
            if not _widget_valid(self._events_table):
                return
            self._events_progress.hide()
            self._update_events_table(events)

        def on_error(err):
            if not _widget_valid(self._events_table):
                return
            self._events_progress.hide()
            emsg = str(err[1]) if isinstance(err, tuple) else str(err)
            self._error_banner.set_error(f"Failed to load events: {emsg}")
            self._error_banner.show()

        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error)

        QThreadPool.globalInstance().start(worker)

    def _update_events_table(self, events: list):
        if not _widget_valid(self._events_table):
            return
        self._events_table.setRowCount(0)
        if not events:
            self._events_table.hide()
            self._events_empty.show()
            return
        self._events_table.show()
        self._events_empty.hide()

        for ev in events:
            row = self._events_table.rowCount()
            self._events_table.insertRow(row)
            self._events_table.setItem(row, 0, QTableWidgetItem(ev.get("time", "")))

            eid = ev.get("event_id", "")
            eid_item = QTableWidgetItem(eid)
            eid_color = "#E74C3C" if eid == "1102" else "#e0e0e0"
            eid_item.setForeground(QColor(eid_color))
            self._events_table.setItem(row, 1, eid_item)

            self._events_table.setItem(row, 2, QTableWidgetItem(
                ev.get("description", "")))

            # Logon type
            msg = ev.get("message", "")
            logon_info = ""
            m = re.search(r"LogonType:\s*(\d+)", msg)
            if m:
                logon_type = int(m.group(1))
                lt_map = {2: "Interactive", 3: "Network", 4: "Batch",
                          5: "Service", 7: "Unlock", 8: "Network Cleartext",
                          9: "New Credentials", 10: "Remote Interactive",
                          11: "Cached Interactive"}
                logon_info = f"LogonType {m.group(1)} ({lt_map.get(logon_type, '')})"
            self._events_table.setItem(row, 3, QTableWidgetItem(logon_info))

    # ── Quick Actions ─────────────────────────────────────────────────────

    def _do_quick_scan(self):
        self._action_status_lbl.setText("Quick scan running...")
        self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        def do_scan(worker):
            return run_quick_scan()

        def on_result(res):
            if not _widget_valid(self._action_status_lbl):
                return
            success = res.get("success", False)
            msg = res.get("message", "")
            if success:
                self._action_status_lbl.setText(f"Scan completed: {msg}")
                self._action_status_lbl.setStyleSheet("color: #27AE60; font-size: 12px;")
            else:
                self._action_status_lbl.setText(f"Scan finished: {msg[:150]}")
                self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        w = Worker(do_scan)
        w.signals.result.connect(on_result)
        w.signals.error.connect(
            lambda _: _on_label_error(self._action_status_lbl, "Error running scan."))
        self._workers.append(w)

        QThreadPool.globalInstance().start(w)

    def _do_update_defs(self):
        self._action_status_lbl.setText("Updating definitions...")
        self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        def do_update(worker):
            return run_update_definitions()

        def on_result(res):
            if not _widget_valid(self._action_status_lbl):
                return
            success = res.get("success", False)
            msg = res.get("message", "")
            if success:
                self._action_status_lbl.setText(f"Definitions updated: {msg}")
                self._action_status_lbl.setStyleSheet("color: #27AE60; font-size: 12px;")
                # Refresh signature state
                if self._loaded_controls:
                    self._refresh_controls()
            else:
                self._action_status_lbl.setText(f"Update: {msg[:150]}")
                self._action_status_lbl.setStyleSheet("color: #E67E22; font-size: 12px;")

        w = Worker(do_update)
        w.signals.result.connect(on_result)
        w.signals.error.connect(
            lambda _: _on_label_error(self._action_status_lbl, "Error updating definitions."))
        self._workers.append(w)

        QThreadPool.globalInstance().start(w)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        if not self._loaded_overview:
            self._loaded_overview = True
            self._refresh_overview()
        if not self._loaded_events:
            self._loaded_events = True
            self._load_events()

    def _on_tab_changed(self, index: int):
        """Read a category tab the first time it is actually shown.

        Not on build: seven tabs read at construction is the whole
        catalog, 15.8s of it, to draw one visible pane.
        """
        tab = self._category_tabs.get(self._tab_names.get(index))
        if tab is not None:
            self._read_category(tab)

    def _manual_refresh(self):
        """Refresh: drop the caches, then re-read what is on screen.

        `snapshots.invalidate()` FIRST -- 135 of the 149 readers answer
        out of that cache and it has no expiry, so a Refresh that
        skipped this would redraw exactly the same numbers and look
        broken. Only the visible tab is re-read; the others reread when
        they are next shown.
        """
        self._error_banner.clear()
        self._error_banner.hide()
        snapshots.invalidate()
        self._refresh_overview()
        for tab in self._category_tabs.values():
            tab.loaded = False
        current = self._category_tabs.get(
            self._tab_names.get(self._tabs.currentIndex()))
        if current is not None:
            self._read_category(current, force=True)
        if self._loaded_events:
            self._load_events()

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def on_stop(self) -> None:
        self.cancel_all_workers()



    # ── Catalog-driven category tabs ──────────────────────────────────────

    def _build_filter_bar(self) -> QWidget:
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)

        self._filter_box = QLineEdit()
        self._filter_box.setPlaceholderText(
            "Filter controls — matches the name, the description and why it "
            "matters")
        self._filter_box.setClearButtonEnabled(True)
        self._filter_box.textChanged.connect(self._apply_filter)
        row.addWidget(self._filter_box, 1)

        self._only_problems = QCheckBox("Only problems")
        self._only_problems.setToolTip(
            "Controls whose reading differs from what the catalog recommends. "
            "A control the catalog has no opinion about is never a problem, "
            "and neither is one that could not be read.")
        self._only_changed = QCheckBox("Only staged")
        self._only_actionable = QCheckBox("Only changeable")
        for box in (self._only_problems, self._only_changed,
                    self._only_actionable):
            box.stateChanged.connect(self._apply_filter)
            row.addWidget(box)
        return bar

    def _build_category_tab(self, category) -> QWidget:
        tab = _CategoryTab(category, [c for c in self.catalog.values()
                                      if c.category is category])
        self._category_tabs[category.value] = tab
        return tab

    def show_category_tab(self, name: str) -> None:
        """Select a category tab and make sure it has been read."""
        for index, tab_name in self._tab_names.items():
            if tab_name == name:
                self._tabs.setCurrentIndex(index)
                break
        tab = self._category_tabs.get(name)
        if tab is not None:
            self._read_category(tab)

    def _dispatch(self, worker) -> None:
        """Where a Worker goes. Overridden in tests, which have no pool."""
        QThreadPool.globalInstance().start(worker)

    def _read_category(self, tab, force: bool = False) -> None:
        """Read this tab's controls, once, off the UI thread.

        A tab reads only its OWN controls: the whole catalog is 15.8s warm
        (31.4s elevated), and 135 of the 149 controls are free -- the cost is
        twelve readers that each launch their own process. Reading everything
        because one tab was opened is the Overview 37.3s defect at scale.

        `tab.reading` is the same guard `test_security_overview_inflight.py`
        pins for Overview: a click on a tab whose read is still in flight must
        not start a second one.
        """
        tab.build_cards(self._on_card_staged)
        if tab.reading or (tab.loaded and not force):
            return
        tab.reading = True
        tab.set_status("Reading…")
        controls = list(tab.controls)

        def job(worker):
            readings = {}
            for control in controls:
                if worker.is_cancelled:
                    return readings
                readings[control.id] = control.read()
            return readings

        # COMWorker, not Worker: these readers reach WMI (BitLocker, TPM,
        # encryptable volumes) and COMWorker is what calls CoInitialize on the
        # pool thread. Unelevated the two are indistinguishable -- every WMI
        # call here is refused, so nothing exercises COM at all, which is
        # exactly why the wrong one would survive testing on this machine.
        worker = COMWorker(job)
        worker.signals.result.connect(
            lambda readings, t=tab: self._on_category_read(t, readings))
        worker.signals.error.connect(
            lambda err, t=tab: self._on_category_error(t, err))
        worker.signals.finished.connect(
            lambda t=tab: self._on_category_finished(t))
        self._workers.append(worker)
        self._dispatch(worker)

    def _on_category_read(self, tab, readings: Dict[str, Any]) -> None:
        if not _widget_valid(tab):
            return
        self._readings.update(readings)
        for control_id, value in readings.items():
            card = tab.cards.get(control_id)
            if card is not None:
                card.set_reading(value)
        tab.loaded = True
        unread = sum(1 for v in readings.values() if v is None)
        stamp = datetime.now().strftime("%H:%M:%S")
        tab.set_status(
            f"Read at {stamp}"
            + (f" — {unread} could not be read" if unread else ""))
        self._apply_filter()

    def _on_category_error(self, err, tab) -> None:
        logger.error("category read failed: %s", err)
        if _widget_valid(tab):
            tab.set_status("The read failed — see the log")

    def _on_category_finished(self, tab) -> None:
        tab.reading = False
        self._workers = [w for w in self._workers if not w.is_finished()] \
            if hasattr(Worker, "is_finished") else self._workers[-1:]

    # ── Filtering ─────────────────────────────────────────────────────────

    def filter_controls(self, text: str = "", only_problems: bool = False,
                        only_changed: bool = False,
                        only_actionable: bool = False) -> List[Any]:
        """The catalog entries a filter would leave visible.

        `only_problems` keys off `desired`, NEVER off the reader's own colour
        (Ruling 6): 14 controls have no `desired` and their readers
        legitimately paint them amber or red, and a control that could not be
        READ is not a control that is wrong.
        """
        needle = (text or "").strip().lower()
        hits = []
        for control in self.catalog.values():
            if needle:
                haystack = (f"{control.title} {control.description} "
                            f"{control.why_it_matters} {control.id}").lower()
                if needle not in haystack:
                    continue
            if only_actionable and not control.writable:
                continue
            if only_changed and control.id not in self._changeset:
                continue
            if only_problems:
                reading = self._readings.get(control.id)
                if (control.desired is None or reading is None
                        or reading == control.desired):
                    continue
            hits.append(control)
        return hits

    def _apply_filter(self) -> None:
        if not self._category_tabs:
            return
        visible = {c.id for c in self.filter_controls(
            self._filter_box.text(),
            only_problems=self._only_problems.isChecked(),
            only_changed=self._only_changed.isChecked(),
            only_actionable=self._only_actionable.isChecked())}
        for tab in self._category_tabs.values():
            shown = 0
            for control_id, card in tab.cards.items():
                on = control_id in visible
                card.setVisible(on)
                shown += 1 if on else 0
            tab.set_match_count(shown, len(tab.cards))

    # ── Staging ───────────────────────────────────────────────────────────

    @property
    def changeset(self):
        return self._changeset

    def _on_card_staged(self, control_id: str, to_value: Any) -> None:
        """A card was clicked. Nothing is written; the change is staged.

        The reading the pane already holds is passed as `from_value`, so
        staging does not read the machine again -- a full baseline diff is
        12.68s without it and 0.001s with it.
        """
        control = self.catalog.get(control_id)
        if control is None:
            return
        try:
            if control_id in self._readings:
                self._changeset.add(control, to_value,
                                    from_value=self._readings[control_id])
            else:
                # Never `add(control, to_value)` here: with no from_value
                # ChangeSet reads the machine, and this runs on the UI
                # thread -- bitlocker_encryption_detail alone is 5.4s of
                # frozen window. A control the pane has not read is
                # honestly staged as unread, which is what
                # ChangeSet.unread_before exists to report.
                logger.warning("staging %s with no reading of its own",
                               control_id)
                self._changeset.add(control, to_value, from_value=None)
        except ValueError as exc:      # read-only, or staged to no value
            logger.warning("cannot stage %s: %s", control_id, exc)
            return
        card = self._card_for(control_id)
        if card is not None:
            if control_id in self._changeset:
                card.set_staged(to_value)
            else:
                card.clear_staged()     # staged back to what it already is
        self._on_changeset_changed()

    def _card_for(self, control_id: str):
        for tab in self._category_tabs.values():
            card = tab.cards.get(control_id)
            if card is not None:
                return card
        return None

    def _on_changeset_changed(self) -> None:
        """Task 16 renders the pending bar here."""
        if self._only_changed.isChecked():
            self._apply_filter()


def _on_label_error(label, message: str):
    """Helper: show error on a QLabel if it still exists."""
    if _widget_valid(label):
        label.setText(message)
        label.setStyleSheet("color: #E74C3C; font-size: 12px;")


# ── Search Provider ────────────────────────────────────────────────────────

class SecuritySearchProvider(SearchProvider):
    """Search across security dashboard checks.

    Returns the current security posture so users can search for
    terms like "defender", "firewall", "bitlocker", etc.
    """

    module_name = "Security Dashboard"

    def search(self, query: SearchQuery) -> list:
        if not query.text:
            return []
        q = query.text.lower()
        results = []

        try:
            from modules.security_dashboard.security_reader import (
                check_defender, check_firewall, check_bitlocker,
                check_secure_boot_tpm, check_uac, check_smartscreen,
                check_hvci, check_credential_guard, check_lsass_protection,
                check_tamper_protection, check_pua_protection,
                check_controlled_folder_access, check_cloud_protection,
                check_network_protection_defender, check_rdp, check_smbv1,
            )
            checks = {
                "defender": ("Windows Defender", check_defender),
                "firewall": ("Windows Firewall", check_firewall),
                "bitlocker": ("BitLocker Drive Encryption", check_bitlocker),
                "secure boot": ("Secure Boot & TPM", check_secure_boot_tpm),
                "tpm": ("TPM Module", check_secure_boot_tpm),
                "uac": ("User Account Control", check_uac),
                "smartscreen": ("SmartScreen Filter", check_smartscreen),
                "hvci": ("HVCI / Memory Integrity", check_hvci),
                "memory integrity": ("Memory Integrity", check_hvci),
                "credential guard": ("Credential Guard", check_credential_guard),
                "lsass": ("LSASS Protection", check_lsass_protection),
                "tamper": ("Tamper Protection", check_tamper_protection),
                "pua": ("PUA Protection", check_pua_protection),
                "controlled folder": ("Controlled Folder Access",
                                       check_controlled_folder_access),
                "ransomware": ("Controlled Folder Access",
                               check_controlled_folder_access),
                "cloud": ("Cloud-Delivered Protection", check_cloud_protection),
                "network protection": ("Network Protection",
                                       check_network_protection_defender),
                "rdp": ("Remote Desktop", check_rdp),
                "remote desktop": ("Remote Desktop", check_rdp),
                "smbv1": ("SMBv1 Protocol", check_smbv1),
                "smb": ("SMBv1 Protocol", check_smbv1),
            }
            from datetime import datetime
            for term, (label, fn) in checks.items():
                if term in q or any(w in q for w in label.lower().split()):
                    try:
                        data = fn()
                        status = data.get("status", "Unknown")
                        color = data.get("color", "amber")
                        results.append(SearchResult(
                            timestamp=datetime.now(),
                            source="Security Dashboard",
                            type=f"Security Check ({color})",
                            summary=f"{label}: {status}",
                            detail=data.get("details", []),
                            relevance=0.9,
                        ))
                    except Exception:
                        logger.warning("Security search failed for '%s'", label, exc_info=True)
        except Exception:
            logger.warning("Security search provider failed", exc_info=True)
        return results[:20]

    def get_filterable_fields(self) -> list:
        return [
            FilterField("severity", "Status", ["green", "amber", "red"]),
        ]
