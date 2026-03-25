from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from core.search_provider import SearchQuery


class FilterPanel(QWidget):
    """Expandable filter panel for refining search queries."""

    filters_changed = pyqtSignal(object)  # emits SearchQuery

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Date range
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Date:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        date_row.addWidget(self._date_from)
        date_row.addWidget(QLabel("to"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        date_row.addWidget(self._date_to)

        date_row.addWidget(QLabel("Time:"))
        self._time_from = QTimeEdit()
        date_row.addWidget(self._time_from)
        date_row.addWidget(QLabel("to"))
        self._time_to = QTimeEdit()
        date_row.addWidget(self._time_to)
        date_row.addStretch()
        layout.addLayout(date_row)

        # Type checkboxes
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._type_checks = {}
        for t in ["Error", "Warning", "Info", "Debug"]:
            cb = QCheckBox(t)
            cb.setChecked(t in ("Error", "Warning"))
            cb.stateChanged.connect(lambda _: self._emit_filters())
            self._type_checks[t] = cb
            type_row.addWidget(cb)
        type_row.addStretch()
        layout.addLayout(type_row)

        # Source checkboxes
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        self._source_checks = {}
        for s in ["EventViewer", "CBS", "DISM", "PerfMon", "AI"]:
            cb = QCheckBox(s)
            cb.setChecked(True)
            cb.stateChanged.connect(lambda _: self._emit_filters())
            self._source_checks[s] = cb
            source_row.addWidget(cb)
        source_row.addStretch()
        layout.addLayout(source_row)

        # Actions row
        action_row = QHBoxLayout()
        self._preset_combo = QComboBox()
        self._preset_combo.setPlaceholderText("Load Preset...")
        action_row.addWidget(self._preset_combo)
        save_btn = QPushButton("Save Preset")
        action_row.addWidget(save_btn)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        action_row.addWidget(clear_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

    def _emit_filters(self):
        query = self.build_query("")
        self.filters_changed.emit(query)

    def build_query(self, text: str, regex: bool = False) -> SearchQuery:
        types = [t for t, cb in self._type_checks.items() if cb.isChecked()]
        sources = [s for s, cb in self._source_checks.items() if cb.isChecked()]
        return SearchQuery(
            text=text,
            types=types,
            sources=sources,
            regex_enabled=regex,
        )

    def _clear_all(self):
        for cb in self._type_checks.values():
            cb.setChecked(False)
        for cb in self._source_checks.values():
            cb.setChecked(True)
        self._emit_filters()
