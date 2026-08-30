"""Paints the Message column, picking out error codes where they sit.

A row can be Info-coloured and still be the failure someone is looking for:
`Info ... InternalOpenPackage failed [HRESULT = 0x800f0805]` is one of 1,156
such lines on this machine. Colouring the code in place makes it findable
without lying about the row's severity.

Only messages that carry a FAILING code take the rich-text path. On a real
CBS.log, 4,553 lines carry a hex code and 4,427 of them carry nothing but
0x00000000 -- painting those would be four thousand successes on screen to
surface nine failures.
"""
from html import escape

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextDocument, QPalette
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle

from core.semantic_colors import semantic

from .error_codes import _is_failure, code_spans


class LogMessageDelegate(QStyledItemDelegate):

    @staticmethod
    def needs_rich_text(text: str) -> bool:
        return any(_is_failure(code) for _s, _e, code in code_spans(text))

    @staticmethod
    def rich_text(text: str, base_colour: str) -> str:
        """`text` with every failing code wrapped in a coloured span.

        Built by walking the spans backwards so the earlier offsets stay
        valid, and escaped as it goes -- a CBS message can contain < and &.
        Plain-text segments are wrapped with the base_colour to avoid
        relying on the ambient pen colour.
        """
        error_colour = semantic("error")
        pieces = []
        cursor = 0
        for start, end, code in code_spans(text):
            if not _is_failure(code):
                continue
            plain_segment = escape(text[cursor:start])
            if plain_segment:
                pieces.append(
                    f'<span style="color:{base_colour}">{plain_segment}</span>')
            pieces.append(
                f'<span style="color:{error_colour}">{escape(text[start:end])}</span>')
            cursor = end
        final_segment = escape(text[cursor:])
        if final_segment:
            pieces.append(
                f'<span style="color:{base_colour}">{final_segment}</span>')
        return "".join(pieces)

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        if not self.needs_rich_text(text):
            super().paint(painter, option, index)
            return

        self.initStyleOption(option, index)
        style = option.widget.style() if option.widget else None
        option.text = ""
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, option,
                              painter, option.widget)

        # Derive the base colour from the palette, handling selected state
        is_selected = option.state & QStyle.StateFlag.State_Selected
        if is_selected:
            base_colour = option.palette.color(
                QPalette.ColorRole.HighlightedText).name()
        else:
            base_colour = option.palette.color(
                QPalette.ColorRole.Text).name()

        document = QTextDocument()
        document.setDefaultFont(option.font)
        document.setHtml(self.rich_text(text, base_colour))
        painter.save()
        painter.translate(option.rect.left() + 4, option.rect.top())
        document.drawContents(painter)
        painter.restore()
