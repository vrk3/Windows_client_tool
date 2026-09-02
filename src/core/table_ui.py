"""Shared table helpers: columns that adapt to the window, centred text.

Tables were hand-tuned one fixed column width at a time, which guaranteed a
horizontal scrollbar as soon as the window shrank and left long values cut
off. These helpers encode the choices a data table keeps repeating:

* header labels are centred,
* text-heavy columns share the free width (``Stretch``) or hug their content
  (``ResizeToContents``), so the table always fills the pane and follows the
  window as it is resized,
* cell text is centred unless the column holds prose.

The ``firewall`` pane keeps its own deliberate fit/zoom machinery and the log
viewer keeps its lines left-aligned; everything else can call these.
"""
from typing import Iterable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem


class _SortableItem(QTableWidgetItem):
    """QTableWidgetItem that compares case-insensitively for alpha sorting."""

    def __lt__(self, other) -> bool:
        return self.text().lower() < other.text().lower()


def centered_item(text: str = "", sortable: bool = False) -> QTableWidgetItem:
    """A table item whose text is centred (optionally sortable A-Z)."""
    item = _SortableItem(text) if sortable else QTableWidgetItem(text)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def center_header(table: QTableWidget) -> None:
    """Centre the header labels of an existing table.

    Does not touch column sizing, so panes with bespoke fit logic (firewall,
    logs) can adopt the look without losing their widths.
    """
    table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)


def fit_table(table: QTableWidget, stretch: Iterable[int] = (),
              content: Iterable[int] = ()) -> None:
    """Centre the header and let columns fill the pane.

    Columns in ``stretch`` share the free width; columns in ``content`` hug
    their widest cell (and header); anything else keeps Qt's Interactive mode
    so the user can still drag sections.
    """
    center_header(table)
    table.horizontalHeader().setStretchLastSection(False)
    header = table.horizontalHeader()
    for col in stretch:
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
    for col in content:
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)


def fit_last(table: QTableWidget) -> None:
    """Classic layout: content-sized columns with the last one stretching."""
    center_header(table)
    header = table.horizontalHeader()
    count = table.columnCount()
    for col in range(count - 1):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(count - 1, QHeaderView.ResizeMode.Stretch)
