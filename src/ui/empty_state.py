"""A centred "there is nothing here yet, and here is why" panel.

Panes that need a scan before they can show anything were putting that fact in
a small grey label in the toolbar and leaving the pane itself blank. The
explanation has to live in the space it explains.

Carries no colours of its own: the muted role comes from the active theme's
sheet, which is the rule the rest of this codebase now follows.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class EmptyState(QWidget):
    """Glyph, title, hint, and optionally one button that starts the work."""

    action_triggered = pyqtSignal()

    def __init__(self, glyph: str, title: str, hint: str,
                 action_text: str = "", parent=None):
        super().__init__(parent)
        self.title = title
        self.hint = hint

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        glyph_label = QLabel(glyph)
        glyph_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Size goes in the stylesheet, not setFont(): both sheets declare
        # `QWidget { font-size: 13px }`, and a stylesheet beats a QFont set in
        # code -- which is why this glyph first rendered at body size. Sizes
        # are safe to set here; colours are what must come from the theme.
        glyph_label.setStyleSheet("font-size: 34px;")
        layout.addWidget(glyph_label)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(title_label)

        hint_label = QLabel(hint)
        hint_label.setObjectName("muted")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint_label.setWordWrap(True)
        # A wrapped label in a centred layout reports the height of ONE line,
        # so a two-line hint came out sliced in half. Bounding the width makes
        # the wrap predictable and lets the label ask for the height it needs.
        hint_label.setMaximumWidth(460)
        hint_label.setMinimumHeight(hint_label.fontMetrics().height() * 3)
        layout.addWidget(hint_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.action_button = None
        if action_text:
            self.action_button = QPushButton(action_text)
            self.action_button.setObjectName("accentButton")
            self.action_button.clicked.connect(self.action_triggered.emit)
            layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignCenter)
