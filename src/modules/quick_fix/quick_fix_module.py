from collections import OrderedDict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QFrame, QScrollArea, QGridLayout,
)
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QFont

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from core.windows_utils import is_reboot_pending
from modules.quick_fix.fix_actions import ALL_ACTIONS, FixAction


class _FixCard(QFrame):
    def __init__(self, action: FixAction, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._action = action
        self._running = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Title row
        title_row = QHBoxLayout()
        title_lbl = QLabel(self._action.title)
        font = title_lbl.font()
        font.setBold(True)
        title_lbl.setFont(font)
        title_row.addWidget(title_lbl)
        if self._action.reboot_required:
            badge = QLabel("⚠ Reboot required")
            badge.setStyleSheet("color: orange;")
            title_row.addStretch()
            title_row.addWidget(badge)
        layout.addLayout(title_row)

        # Description
        desc = QLabel(self._action.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: gray;")
        layout.addWidget(desc)

        # Run button
        self._run_btn = QPushButton("Run")
        self._run_btn.setFixedWidth(80)
        layout.addWidget(self._run_btn)

        # Output
        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setMaximumHeight(150)
        mono_font = QFont("Consolas", 8)
        self._output.setFont(mono_font)
        self._output.hide()
        layout.addWidget(self._output)

        self._run_btn.clicked.connect(self._run)

    def _run(self):
        if self._running:
            return
        self._running = True
        self._run_btn.setEnabled(False)
        self._output.clear()
        self._output.show()

        action = self._action

        def append(line: str):
            self._output.appendPlainText(line)

        def do_work():
            action.fn(append)

        # Worker passes itself as first argument to fn, so wrap with ignored param
        worker = Worker(lambda _w: do_work())
        worker.signals.result.connect(lambda _result: self._on_done())
        worker.signals.error.connect(self._on_error)
        QThreadPool.globalInstance().start(worker)

    def _on_done(self):
        self._running = False
        self._run_btn.setEnabled(True)

    def _on_error(self, error_str: str):
        self._running = False
        self._run_btn.setEnabled(True)
        self._output.appendPlainText(f"ERROR: {error_str}")


class QuickFixModule(BaseModule):
    name = "Quick Fix"
    icon = "🔧"
    description = "One-click system repair and maintenance tools"
    requires_admin = True
    group = ModuleGroup.TOOLS

    def create_widget(self) -> QWidget:
        outer = QWidget()
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Reboot banner (hidden by default)
        self._reboot_banner = QLabel("⚠ A system reboot is pending.")
        self._reboot_banner.setStyleSheet(
            "background: #FF8800; color: white; padding: 4px; font-weight: bold;"
        )
        self._reboot_banner.hide()
        outer_layout.addWidget(self._reboot_banner)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(8, 8, 8, 8)

        # Group actions by category preserving order
        categories: OrderedDict = OrderedDict()
        for action in ALL_ACTIONS:
            categories.setdefault(action.category, []).append(action)

        for cat_name, actions in categories.items():
            hdr = QLabel(cat_name)
            hdr_font = hdr.font()
            hdr_font.setBold(True)
            hdr_font.setPointSize(hdr_font.pointSize() + 1)
            hdr.setFont(hdr_font)
            content_layout.addWidget(hdr)

            grid = QGridLayout()
            grid.setSpacing(8)
            for i, action in enumerate(actions):
                card = _FixCard(action)
                grid.addWidget(card, i // 2, i % 2)
            content_layout.addLayout(grid)

        content_layout.addStretch()
        scroll.setWidget(content)
        outer_layout.addWidget(scroll)

        # Check reboot status
        try:
            if is_reboot_pending():
                self._reboot_banner.show()
        except Exception:
            pass

        return outer

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        pass

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()
