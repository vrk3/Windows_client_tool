from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                              QPushButton, QLabel, QFrame, QProgressBar, QSizePolicy)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor, QFont

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker, COMWorker
from modules.security_dashboard.security_reader import get_all_security_status

COLOR_MAP = {
    "green": "#27AE60",
    "amber": "#E67E22",
    "red": "#E74C3C",
}


class _StatusCard(QFrame):
    """A coloured status card with title, status badge, and detail rows."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)

        self._title_lbl = QLabel(title)
        font = self._title_lbl.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        self._title_lbl.setFont(font)
        layout.addWidget(self._title_lbl)

        self._status_lbl = QLabel("Loading...")
        self._status_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self._status_lbl)

        self._details_layout = QVBoxLayout()
        layout.addLayout(self._details_layout)
        layout.addStretch()

    def update_status(self, data: dict):
        color = COLOR_MAP.get(data.get("color", "amber"), "#888888")
        status = data.get("status", "Unknown")
        self._status_lbl.setText(status)
        self._status_lbl.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {color};")
        self.setStyleSheet(f"QFrame {{ border-left: 4px solid {color}; }}")

        # Clear detail rows
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


class SecurityDashboardModule(BaseModule):
    name = "security_dashboard"
    icon = "🔒"
    description = "Windows security status overview"
    requires_admin = True
    group = ModuleGroup.SYSTEM

    def create_widget(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Header
        header_row = QHBoxLayout()
        self._banner = QLabel("Security Status")
        font = self._banner.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 2)
        self._banner.setFont(font)
        refresh_btn = QPushButton("Refresh")
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        header_row.addWidget(self._banner, 1)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)
        layout.addWidget(self._progress)

        # 2x2 card grid
        grid = QGridLayout()
        grid.setSpacing(12)
        self._defender_card = _StatusCard("🛡 Windows Defender")
        self._firewall_card = _StatusCard("🔥 Firewall")
        self._bitlocker_card = _StatusCard("💾 BitLocker")
        self._boot_card = _StatusCard("🔐 Secure Boot & TPM")
        grid.addWidget(self._defender_card, 0, 0)
        grid.addWidget(self._firewall_card, 0, 1)
        grid.addWidget(self._bitlocker_card, 1, 0)
        grid.addWidget(self._boot_card, 1, 1)
        layout.addLayout(grid)
        layout.addStretch()

        def do_refresh():
            refresh_btn.setEnabled(False)
            self._progress.show()
            self._banner.setText("Security Status — Loading...")

            worker = COMWorker(lambda _w: get_all_security_status())

            def on_result(data: dict):
                refresh_btn.setEnabled(True)
                self._progress.hide()
                self._defender_card.update_status(data["defender"])
                self._firewall_card.update_status(data["firewall"])
                self._bitlocker_card.update_status(data["bitlocker"])
                self._boot_card.update_status(data["secure_boot_tpm"])
                # Overall banner
                colors = [d.get("color", "amber") for d in data.values()]
                if all(c == "green" for c in colors):
                    overall = "✅ Secure"
                    col = "#27AE60"
                elif any(c == "red" for c in colors):
                    overall = "❌ Issues Detected"
                    col = "#E74C3C"
                else:
                    overall = "⚠ Warnings"
                    col = "#E67E22"
                self._banner.setText(f"Security Status — {overall}")
                self._banner.setStyleSheet(f"color: {col};")

            def on_error(err):
                refresh_btn.setEnabled(True)
                self._progress.hide()
                self._banner.setText(f"Error: {err}")

            worker.signals.result.connect(on_result)
            worker.signals.error.connect(on_error)
            QThreadPool.globalInstance().start(worker)

        refresh_btn.clicked.connect(do_refresh)
        return w

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
