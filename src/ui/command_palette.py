from typing import Callable, List

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)


class CommandPalette(QDialog):
    """Ctrl+P module switcher — type to filter, Up/Down/Enter to navigate."""

    def __init__(self, modules: List, on_select: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._modules = modules
        self._on_select = on_select
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setFixedWidth(480)
        self.setStyleSheet("""
            QDialog {
                background: #252526;
                border: 1px solid #555;
                border-radius: 6px;
            }
            QLineEdit {
                background: #3c3c3c;
                color: #d4d4d4;
                border: none;
                border-bottom: 1px solid #555;
                padding: 10px 14px;
                font-size: 14px;
            }
            QListWidget {
                background: #252526;
                color: #d4d4d4;
                border: none;
                font-size: 13px;
                outline: none;
            }
            QListWidget::item { padding: 7px 14px; }
            QListWidget::item:selected { background: #094771; color: #fff; }
            QListWidget::item:hover { background: #2a2d2e; }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Go to module\u2026")
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setMaximumHeight(340)
        layout.addWidget(self._list)

        hint = QLabel("  \u2191\u2193 navigate   \u23ce select   Esc dismiss")
        hint.setStyleSheet("color: #555; font-size: 11px; padding: 4px 8px 6px 8px;")
        layout.addWidget(hint)

        self._populate("")
        self._search.textChanged.connect(self._populate)
        self._list.itemActivated.connect(self._activate)
        self._search.installEventFilter(self)

    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if obj is self._search and isinstance(event, QKeyEvent):
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._list.setFocus()
                if self._list.count() > 0 and self._list.currentRow() < 0:
                    self._list.setCurrentRow(0)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate()
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------

    def _populate(self, text: str):
        self._list.clear()
        q = text.lower()
        for mod in self._modules:
            if not q or q in mod.name.lower():
                icon = getattr(mod, "icon", "")
                label = f"{icon}  {mod.name}" if icon else mod.name
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, mod.name)
                self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _activate(self, item=None):
        if item is None:
            item = self._list.currentItem()
        if item:
            self._on_select(item.data(Qt.ItemDataRole.UserRole))
            self.accept()

    def showEvent(self, event):
        super().showEvent(event)
        self._search.setFocus()
        self._search.clear()
        self._populate("")
