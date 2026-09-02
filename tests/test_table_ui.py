from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHeaderView, QTableWidget, QTableWidgetItem

from core.table_ui import center_header, centered_item, fit_last, fit_table


def test_centered_item_is_centered_and_compatible():
    item = centered_item("Hello")
    assert item.text() == "Hello"
    assert item.textAlignment() == Qt.AlignmentFlag.AlignCenter
    assert isinstance(item, QTableWidgetItem)


def test_centered_item_sortable_compares_case_insensitively():
    # 'apple' sorts before 'Zebra' only when comparison ignores case.
    a = centered_item("apple", sortable=True)
    b = centered_item("Zebra", sortable=True)
    assert a < b


def test_center_header_does_not_touch_resize_modes(qapp):
    table = QTableWidget(0, 2)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    center_header(table)
    assert table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.Interactive
    assert table.horizontalHeader().defaultAlignment() == Qt.AlignmentFlag.AlignCenter


def test_fit_table_sets_stretch_content_and_centred_header(qapp):
    table = QTableWidget(0, 4)
    fit_table(table, stretch=[0, 1], content=[2, 3])
    header = table.horizontalHeader()
    assert header.defaultAlignment() == Qt.AlignmentFlag.AlignCenter
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(3) == QHeaderView.ResizeMode.ResizeToContents
    assert header.stretchLastSection() is False


def test_fit_last_stretches_only_the_last_column(qapp):
    table = QTableWidget(0, 3)
    fit_last(table)
    header = table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(2) == QHeaderView.ResizeMode.Stretch
    assert header.defaultAlignment() == Qt.AlignmentFlag.AlignCenter
