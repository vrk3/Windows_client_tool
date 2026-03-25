from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
)

from core.search_provider import SearchResult


class SearchResultDetail(QDialog):
    """Modal dialog showing full detail of a search result with copy support."""

    def __init__(self, result: SearchResult, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search Result Detail")
        self.resize(800, 600)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.WindowMaximizeButtonHint
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Header grid: Time / Source / Type
        header = QHBoxLayout()
        for label, value in [
            ("Time:", result.timestamp.strftime("%Y-%m-%d %H:%M:%S")),
            ("Source:", result.source),
            ("Type:", result.type),
        ]:
            lbl = QLabel(f"<b>{label}</b> {value}")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            header.addWidget(lbl)
        header.addStretch()
        layout.addLayout(header)

        # Summary line
        summary_lbl = QLabel(f"<b>Summary:</b> {result.summary}")
        summary_lbl.setWordWrap(True)
        summary_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(summary_lbl)

        # Full detail text area
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setFont(QFont("Consolas", 9))
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._text.setText(self._format_detail(result))
        layout.addWidget(self._text)

        # Buttons
        btn_row = QHBoxLayout()

        copy_all_btn = QPushButton("Copy All")
        copy_all_btn.setToolTip("Copy full content to clipboard (Ctrl+A, Ctrl+C)")
        copy_all_btn.clicked.connect(self._copy_all)
        btn_row.addWidget(copy_all_btn)

        copy_sel_btn = QPushButton("Copy Selection")
        copy_sel_btn.setToolTip("Copy selected text to clipboard")
        copy_sel_btn.clicked.connect(self._copy_selection)
        btn_row.addWidget(copy_sel_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

        # Keyboard shortcuts
        QShortcut(QKeySequence("Ctrl+W"), self).activated.connect(self.accept)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.accept)

    def _format_detail(self, result: SearchResult) -> str:
        lines = [
            f"Timestamp : {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Source    : {result.source}",
            f"Type      : {result.type}",
            f"Summary   : {result.summary}",
            "",
            "--- Detail ---",
        ]

        detail = result.detail
        if isinstance(detail, dict):
            for k, v in detail.items():
                lines.append(f"{k}: {v}")
        elif isinstance(detail, str):
            lines.append(detail)
        elif detail is not None:
            lines.append(str(detail))

        return "\n".join(lines)

    def _copy_all(self):
        QApplication.clipboard().setText(self._text.toPlainText())

    def _copy_selection(self):
        selected = self._text.textCursor().selectedText()
        if selected:
            QApplication.clipboard().setText(selected)
        else:
            self._copy_all()
