from datetime import datetime, timedelta

from PyQt6.QtCore import QDate, QDateTime, QTime, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from core.search_provider import SearchQuery

# Must match SearchProvider.module_name values in each module
_ALL_SOURCES = ["EventViewer", "CBS", "DISM", "WindowsUpdate", "Reliability", "CrashDumps", "PerfMon"]


class FilterPanel(QWidget):
    """Expandable filter panel for refining search queries."""

    filters_changed = pyqtSignal(object)  # emits SearchQuery

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)

        # Date range — default to last 24 hours
        now = datetime.now()
        yesterday = now - timedelta(hours=24)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("Date:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        self._date_from.dateChanged.connect(lambda _: self._emit_filters())
        date_row.addWidget(self._date_from)
        date_row.addWidget(QLabel("to"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate(now.year, now.month, now.day))
        self._date_to.dateChanged.connect(lambda _: self._emit_filters())
        date_row.addWidget(self._date_to)

        date_row.addWidget(QLabel("Time:"))
        self._time_from = QTimeEdit()
        self._time_from.setTime(QTime(yesterday.hour, yesterday.minute))
        self._time_from.timeChanged.connect(lambda _: self._emit_filters())
        date_row.addWidget(self._time_from)
        date_row.addWidget(QLabel("to"))
        self._time_to = QTimeEdit()
        self._time_to.setTime(QTime(now.hour, now.minute))
        self._time_to.timeChanged.connect(lambda _: self._emit_filters())
        date_row.addWidget(self._time_to)
        date_row.addStretch()
        layout.addLayout(date_row)

        # Type checkboxes
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Type:"))
        self._type_checks = {}
        for t in ["Error", "Warning", "Info", "Debug"]:
            cb = QCheckBox(t)
            cb.setChecked(True)  # all on by default — user deselects to exclude
            cb.stateChanged.connect(lambda _: self._emit_filters())
            self._type_checks[t] = cb
            type_row.addWidget(cb)
        type_row.addStretch()
        layout.addLayout(type_row)

        # Source checkboxes — names match SearchProvider.module_name
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        self._source_checks = {}
        for s in _ALL_SOURCES:
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
        clear_btn = QPushButton("Reset")
        clear_btn.clicked.connect(self._reset)
        action_row.addWidget(clear_btn)
        action_row.addStretch()
        layout.addLayout(action_row)

    def _emit_filters(self):
        query = self.build_query("")
        self.filters_changed.emit(query)

    def build_query(self, text: str, regex: bool = False) -> SearchQuery:
        # Only pass types/sources as filter if something is unchecked
        # (empty list = no filter = all pass)
        all_types = list(self._type_checks.keys())
        checked_types = [t for t, cb in self._type_checks.items() if cb.isChecked()]
        types = checked_types if len(checked_types) < len(all_types) else []

        checked_sources = [s for s, cb in self._source_checks.items() if cb.isChecked()]
        sources = checked_sources if len(checked_sources) < len(_ALL_SOURCES) else []

        # Build datetime range from date+time widgets
        d_from = self._date_from.date()
        t_from = self._time_from.time()
        d_to = self._date_to.date()
        t_to = self._time_to.time()

        date_from = datetime(d_from.year(), d_from.month(), d_from.day(),
                             t_from.hour(), t_from.minute())
        date_to = datetime(d_to.year(), d_to.month(), d_to.day(),
                           t_to.hour(), t_to.minute(), 59)

        return SearchQuery(
            text=text,
            date_from=date_from,
            date_to=date_to,
            types=types,
            sources=sources,
            regex_enabled=regex,
        )

    def _reset(self):
        now = datetime.now()
        yesterday = now - timedelta(hours=24)
        self._date_from.setDate(QDate(yesterday.year, yesterday.month, yesterday.day))
        self._date_to.setDate(QDate(now.year, now.month, now.day))
        self._time_from.setTime(QTime(yesterday.hour, yesterday.minute))
        self._time_to.setTime(QTime(now.hour, now.minute))
        for cb in self._type_checks.values():
            cb.setChecked(True)
        for cb in self._source_checks.values():
            cb.setChecked(True)
        self._emit_filters()
