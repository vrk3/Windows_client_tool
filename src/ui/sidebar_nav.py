# src/ui/sidebar_nav.py
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)


class SidebarNav(QWidget):
    """Vertical navigation sidebar.

    Emits module_selected(module_name: str) when a module button is clicked.
    Groups are displayed as bold QLabel headers; modules are QPushButton items.
    Collapsed mode shows icon-only (48 px wide).
    """

    module_selected = pyqtSignal(str)
    collapsed_changed = pyqtSignal(bool)  # True = collapsed, False = expanded

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._collapsed = False
        self._is_admin = False
        self._module_buttons: Dict[str, List[Tuple[str, QPushButton]]] = {}
        self._btn_map: Dict[str, QPushButton] = {}
        self._group_order: List[str] = []
        self._active_name: Optional[str] = None

        self._build_layout()
        self.setMinimumWidth(180)
        self.setMaximumWidth(240)

    def _build_layout(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setFixedHeight(28)
        self._toggle_btn.setToolTip("Collapse sidebar")
        self._toggle_btn.clicked.connect(self._toggle_collapse)
        outer.addWidget(self._toggle_btn)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        self._nav_widget = QWidget()
        self._nav_layout = QVBoxLayout(self._nav_widget)
        self._nav_layout.setContentsMargins(0, 4, 0, 4)
        self._nav_layout.setSpacing(0)
        self._nav_layout.addStretch()

        scroll.setWidget(self._nav_widget)
        outer.addWidget(scroll)

    def set_admin(self, is_admin: bool) -> None:
        self._is_admin = is_admin
        for name, btn in self._btn_map.items():
            if btn.property("requires_admin") and not is_admin:
                btn.setEnabled(False)
                btn.setToolTip("Requires administrator")
            elif btn.property("requires_admin") and is_admin:
                btn.setEnabled(True)
                btn.setToolTip(btn.property("display_name") or name)

    def add_module(self, group: str, name: str, icon: str,
                   display: str, requires_admin: bool) -> None:
        if group not in self._module_buttons:
            self._module_buttons[group] = []
            self._group_order.append(group)
            stretch_idx = self._nav_layout.count() - 1
            header = QLabel(group)
            header.setObjectName("sidebarGroupHeader")
            header.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self._nav_layout.insertWidget(stretch_idx, header)

        stretch_idx = self._nav_layout.count() - 1
        btn = QPushButton(f"{icon}  {display}" if not self._collapsed else icon)
        btn.setObjectName("sidebarModuleBtn")
        btn.setCheckable(True)
        btn.setProperty("module_name", name)
        btn.setProperty("requires_admin", requires_admin)
        btn.setProperty("display_name", display)
        btn.setProperty("icon_char", icon)
        btn.setToolTip(display)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setFixedHeight(32)

        if requires_admin and not self._is_admin:
            btn.setEnabled(False)
            btn.setToolTip("Requires administrator")

        btn.clicked.connect(lambda checked, n=name: self._on_btn_clicked(n))
        self._nav_layout.insertWidget(stretch_idx, btn)
        self._module_buttons[group].append((name, btn))
        self._btn_map[name] = btn

    def select(self, name: str) -> None:
        if self._active_name and self._active_name in self._btn_map:
            self._btn_map[self._active_name].setChecked(False)
        self._active_name = name
        if name in self._btn_map:
            self._btn_map[name].setChecked(True)

    def _on_btn_clicked(self, name: str) -> None:
        self.select(name)
        self.module_selected.emit(name)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.collapsed_changed.emit(self._collapsed)
        if self._collapsed:
            self.setMaximumWidth(48)
            self.setMinimumWidth(48)
            self._toggle_btn.setText("▶")
            for name, btn in self._btn_map.items():
                icon = btn.property("icon_char") or ""
                btn.setText(icon)
        else:
            self.setMaximumWidth(240)
            self.setMinimumWidth(180)
            self._toggle_btn.setText("◀")
            for name, btn in self._btn_map.items():
                icon = btn.property("icon_char") or ""
                display = btn.property("display_name") or name
                btn.setText(f"{icon}  {display}")
