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
import logging
import re
from html import escape

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QTextDocument, QPalette
from PyQt6.QtWidgets import QStyledItemDelegate, QStyle

from core.semantic_colors import semantic

from .error_codes import _is_failure, code_spans, corruption_spans

logger = logging.getLogger(__name__)


class LogMessageDelegate(QStyledItemDelegate):

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        #: Compiled patterns for whatever the Filter and Find boxes hold.
        #: Compiled HERE and never inside `paint`: `paint` is a reimplemented
        #: Qt virtual, so an exception raised inside it is routed to
        #: sys.excepthook and then qFatal() -- it cannot be caught, and the
        #: process dies. A half-typed regex is a keystroke, not a crash.
        self.needles: list = []
        #: The one row allowed to wrap to its full height, or -1.
        #:
        #: One, never a set: `sizeHint` is asked for every row the view lays
        #: out, and building a QTextDocument per row would lay out 200,000
        #: messages to show one.
        self.expanded_row = -1
        #: The user's chosen colours, by meaning. Empty means "follow the
        #: theme", which is not the same as storing the theme's current
        #: values -- see match_colours.
        self._colours: dict = {}

    def set_colours(self, colours) -> None:
        """Which colours to paint matches and failing codes in.

        Cleaned on the way in even though `load_colours` already cleaned what
        it read: this is public, and what it accepts is painted inside a Qt
        virtual, where a bad value is fatal rather than catchable.
        """
        from .match_colours import _clean

        self._colours = _clean(colours)

    def message_html(self, text: str, base_colour: str) -> str:
        """`text` marked up with this delegate's needles and colours.

        The seam `paint` and `sizeHint` both go through, so what is measured
        can never disagree with what is drawn.
        """
        return self.rich_text(text, base_colour, self.needles,
                              match_colour=self._colours.get("match"),
                              error_colour=self._colours.get("error"))

    @staticmethod
    def compiled(patterns, regex: bool = False) -> list:
        """`patterns` ready to paint with.

        An unfinished pattern colours nothing until it is finished, which is
        the same thing the Filter itself does with one.
        """
        out = []
        for pattern in patterns or ():
            if not pattern:
                # An empty box is not a match on every character.
                continue
            try:
                out.append(re.compile(
                    pattern if regex else re.escape(pattern), re.IGNORECASE))
            except re.error:
                logger.debug("compiled: skipping an item that could not be read", exc_info=True)
                continue
        return out

    def set_needles(self, patterns, regex: bool = False) -> None:
        """What the Filter and Find boxes are looking for, ready to paint."""
        self.needles = self.compiled(patterns, regex)

    @staticmethod
    def match_spans(text: str, needles) -> list:
        """`(start, end)` of every needle match, overlaps merged.

        Filter and Find can both match the same run of characters, and two
        spans over one stretch of text would nest their tags and paint it
        twice.
        """
        found = []
        for needle in needles or ():
            for match in needle.finditer(text):
                if match.end() > match.start():
                    found.append((match.start(), match.end()))
        if not found:
            return []
        found.sort()
        merged = [found[0]]
        for start, end in found[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    @staticmethod
    def _without(span, blockers) -> list:
        """`span` with every blocker cut out of it.

        A failing error code keeps its own colour even when the search term
        lands on top of it: searching for `0x800f0805` must not stop it
        reading as a failure.
        """
        start, end = span
        pieces = []
        for blocked_start, blocked_end in blockers:
            if blocked_end <= start or blocked_start >= end:
                continue
            if blocked_start > start:
                pieces.append((start, blocked_start))
            start = max(start, blocked_end)
            if start >= end:
                return pieces
        if start < end:
            pieces.append((start, end))
        return pieces

    @staticmethod
    def failure_spans(text: str) -> list:
        """Everything that means "this went wrong", merged.

        A failing error code and a damage marker are the same news to a
        reader and get the same colour, so they are combined here and any
        overlap between them collapsed -- two spans over one stretch of text
        would nest their tags and paint it twice.
        """
        found = [(start, end) for start, end, code in code_spans(text)
                 if _is_failure(code)]
        found.extend((start, end) for start, end, _label
                     in corruption_spans(text))
        if not found:
            return []
        found.sort()
        merged = [found[0]]
        for start, end in found[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    @classmethod
    def needs_rich_text(cls, text: str, needles=()) -> bool:
        if cls.failure_spans(text):
            return True
        return bool(cls.match_spans(text, needles))

    @classmethod
    def rich_text(cls, text: str, base_colour: str, needles=(),
                  match_colour=None, error_colour=None) -> str:
        """`text` with failing codes and search matches wrapped in spans.

        Built by walking the spans forwards with a cursor, escaping each
        plain-text segment as it goes -- a CBS message can contain < and &.
        Plain-text segments are wrapped with the base_colour to avoid
        relying on the ambient pen colour.

        Colour only, never a background: the row already carries a severity
        tint, and a highlight behind the match would fight it.

        `match_colour` and `error_colour` default to the themed values, so a
        caller that passes neither follows the theme -- which is what an
        unset override means.
        """
        error_colour = error_colour or semantic("error")
        match_colour = match_colour or semantic("match")

        errors = cls.failure_spans(text)
        spans = [(start, end, error_colour) for start, end in errors]
        for span in cls.match_spans(text, needles):
            spans.extend((start, end, match_colour)
                         for start, end in cls._without(span, errors))
        spans.sort()

        pieces = []
        cursor = 0
        for start, end, colour in spans:
            plain_segment = escape(text[cursor:start])
            if plain_segment:
                pieces.append(
                    f'<span style="color:{base_colour}">{plain_segment}</span>')
            pieces.append(
                f'<span style="color:{colour}">{escape(text[start:end])}</span>')
            cursor = end
        final_segment = escape(text[cursor:])
        if final_segment:
            pieces.append(
                f'<span style="color:{base_colour}">{final_segment}</span>')
        return "".join(pieces)

    def _document(self, text: str, base_colour: str, width: int):
        """A laid-out document for `text`, wrapped to `width`."""
        document = QTextDocument()
        document.setHtml(self.message_html(text, base_colour))
        if width > 0:
            document.setTextWidth(width)
        return document

    def sizeHint(self, option, index):
        """One line, except for the expanded row.

        Only that row is measured. Laying out every row to find its natural
        height is what makes a 200,000-record table unusable.
        """
        if index.row() != self.expanded_row:
            return super().sizeHint(option, index)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # `option.rect` is EMPTY when Qt asks during resizeRowToContents, and
        # a text width of zero disables wrapping -- so the row came back one
        # line tall and nothing appeared to happen. Fall back to the view's
        # actual column width, which is the number that matters anyway.
        width = option.rect.width()
        if width <= 0 and option.widget is not None:
            width = option.widget.columnWidth(index.column())
        document = self._document(str(text), "#000000", width)
        size = document.size()
        return QSize(int(size.width()), int(size.height()) + 4)

    def paint(self, painter, option, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        expanded = index.row() == self.expanded_row
        # The expanded row always takes the rich-text path: that is where the
        # wrapping lives, and the plain path elides instead.
        if not expanded and not self.needs_rich_text(text, self.needles):
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

        document = self._document(text, base_colour,
                                  option.rect.width() - 8 if expanded else 0)
        document.setDefaultFont(option.font)
        painter.save()
        painter.translate(option.rect.left() + 4, option.rect.top())
        document.drawContents(painter)
        painter.restore()
