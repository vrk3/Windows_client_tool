import csv
import datetime
import json
import os
import shutil
import string
import threading
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, QEvent, QObject, pyqtSignal
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMenu, QMessageBox, QProgressBar, QPushButton,
    QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
    QToolButton, QTreeView, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from modules.treesize.disk_scanner import DiskScanner
from modules.treesize.disk_tree_model import (
    COL_SIZE, COL_NAME, DiskTreeModel, SizeBarDelegate,
    format_size, PieChartWidget, _CHART_COLORS,
)


def _get_drives():
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


# ── PieChart widget ─────────────────────────────────────────────────────────

class _PieChart(QWidget):
    """Donut chart showing top-level folder proportions."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: List[tuple] = []  # (name, size, color)
        self.setMinimumHeight(90)
        self.setMaximumHeight(110)

    def set_data(self, roots):
        self._data = []
        if not roots:
            self.update()
            return
        total = sum(r.size for r in roots if r.is_dir and r.size > 0)
        if total == 0:
            self.update()
            return
        for i, r in enumerate(roots[:9]):
            if not r.is_dir or r.size <= 0:
                continue
            self._data.append((
                r.name[:14],
                r.size,
                _CHART_COLORS[i % len(_CHART_COLORS)],
                r.size / total,
            ))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if not self._data:
            painter.drawText(w // 2 - 40, h // 2, "Scan to see chart")
            return

        # Donut chart on the left
        chart_size = min(h - 8, w // 3)
        cx, cy = chart_size // 2 + 4, h // 2
        r = chart_size // 2 - 4

        total = sum(d[1] for d in self._data)
        angle = 0
        for name, size, color, frac in self._data:
            sweep = int(360 * 16 * frac)
            painter.setPen(color)
            painter.setBrush(color)
            painter.drawPie(cx - r, cy - r, r * 2, r * 2, int(angle * 16), sweep)
            angle += sweep / 16

        # White donut hole
        painter.setBrush(self.palette().window())
        inner = int(r * 0.5)
        painter.drawEllipse(cx - inner, cy - inner, inner * 2, inner * 2)

        # Legend on the right
        lx = chart_size + 10
        painter.setFont(self.font())
        for i, (name, size, color, frac) in enumerate(self._data):
            painter.setPen(color)
            painter.drawText(lx, 16 + i * 16, f"{name}  {frac * 100:.0f}%  {format_size(size)}")


# ── Top Files panel ─────────────────────────────────────────────────────────

class _TopFilesPanel(QWidget):
    """Collapsible panel showing the top N largest individual files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(160)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)

        header = QHBoxLayout()
        self._toggle_btn = QPushButton("▼ Top 10 Largest Files")
        self._toggle_btn.setStyleSheet("border: none; font-weight: bold; text-align: left; padding: 0;")
        self._toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self._toggle_btn)
        self._count_lbl = QLabel("")
        header.addWidget(self._count_lbl)
        lay.addLayout(header)

        self._table = QTableWidget(0, 2, self)
        self._table.setHorizontalHeaderLabels(["Name", "Size"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setMaximumHeight(120)
        lay.addWidget(self._table)

        self._expanded = True

    def _toggle(self):
        self._expanded = not self._expanded
        self._table.setVisible(self._expanded)
        arrow = "▼" if self._expanded else "▶"
        self._toggle_btn.setText(f"{arrow} Top 10 Largest Files")

    def populate(self, top_files):
        self._table.setRowCount(0)
        for node in top_files:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(node.name))
            self._table.setItem(row, 1, QTableWidgetItem(format_size(node.size)))
        self._count_lbl.setText(f"({len(top_files)} files)")


# ── Breadcrumb bar ──────────────────────────────────────────────────────────

class _BreadcrumbBar(QWidget):
    """Clickable path segments for quick navigation up the tree."""

    path_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.addWidget(QLabel("Path:"))
        self._content = QWidget()
        self._content_lay = QHBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(2)
        lay.addWidget(self._content, 1)

    def set_path(self, path: str):
        self._path = path
        # Clear existing
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        parts = []
        p = path.rstrip("\\")
        while p:
            parts.append(p)
            p = os.path.dirname(p)
        parts.reverse()

        for i, part in enumerate(parts):
            if i > 0:
                sep = QLabel("›")
                sep.setStyleSheet("color: gray;")
                self._content_lay.addWidget(sep)
            btn = QPushButton(os.path.basename(part) if i > 0 else part)
            btn.setStyleSheet("border: none; text-decoration: underline; color: #4488FF;")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, p=part: self.path_clicked.emit(p))
            self._content_lay.addWidget(btn)

        self._content_lay.addStretch()


# ── Main module ────────────────────────────────────────────────────────────

class TreeSizeModule(BaseModule):
    name = "Tree Size"
    icon = "📊"
    description = "Visualise disk usage by folder and file size"
    requires_admin = False
    group = ModuleGroup.TOOLS

    def __init__(self):
        super().__init__()
        self._widget: QWidget | None = None
        self._scanner: DiskScanner | None = None
        self._scan_thread: threading.Thread | None = None
        self._loaded = False
        self._auto_refresh_timer: QTimer | None = None
        self._auto_refresh_enabled: bool = True
        self._current_scan_path: str = ""
        self._is_paused: bool = False

        # ── feature: navigation history ─────────────────────────────────
        self._nav_history: List[str] = []
        self._nav_forward: List[str] = []

        # ── feature: scan history ────────────────────────────────────────
        self._scan_history: List[dict] = []  # {"path": str, "timestamp": float}
        self._history_limit = 20

    # ── widget creation ────────────────────────────────────────────────────

    def create_widget(self) -> QWidget:
        w = QWidget()
        self._event_filter = _TreeEventFilter(self)
        w.installEventFilter(self._event_filter)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Top toolbar ───────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self._drive_cb = QComboBox()
        self._drive_cb.setFixedWidth(80)
        for d in _get_drives():
            self._drive_cb.addItem(d)
        self._drive_cb.view().setMouseTracking(True)
        self._drive_cb.view().installEventFilter(
            _DoubleClickWatcher(self._drive_cb, self._on_drive_dblclick))

        self._path_edit = QLineEdit()
        self._path_edit.setPlaceholderText("Path to scan…")
        if self._drive_cb.count():
            self._path_edit.setText(self._drive_cb.currentText())

        self._scan_btn = QPushButton("Scan")
        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setEnabled(False)
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setEnabled(False)
        self._pause_btn.clicked.connect(self._toggle_pause)

        # ── feature: back / forward ──────────────────────────────────────
        self._back_btn = QPushButton("◀")
        self._back_btn.setToolTip("Back")
        self._back_btn.setEnabled(False)
        self._back_btn.setMaximumWidth(32)
        self._fwd_btn = QPushButton("▶")
        self._fwd_btn.setToolTip("Forward")
        self._fwd_btn.setEnabled(False)
        self._fwd_btn.setMaximumWidth(32)
        self._back_btn.clicked.connect(self._go_back)
        self._fwd_btn.clicked.connect(self._go_forward)

        # ── feature: expand / collapse all ─────────────────────────────────
        self._expand_btn = QPushButton("Expand All")
        self._expand_btn.setMaximumWidth(80)
        self._collapse_btn = QPushButton("Collapse All")
        self._collapse_btn.setMaximumWidth(80)

        toolbar.addWidget(QLabel("Drive:"))
        toolbar.addWidget(self._drive_cb)
        toolbar.addWidget(QLabel("Path:"))
        toolbar.addWidget(self._path_edit, 1)
        toolbar.addWidget(self._scan_btn)
        toolbar.addWidget(self._stop_btn)
        toolbar.addWidget(self._pause_btn)
        toolbar.addWidget(self._back_btn)
        toolbar.addWidget(self._fwd_btn)
        toolbar.addWidget(self._expand_btn)
        toolbar.addWidget(self._collapse_btn)
        layout.addLayout(toolbar)

        # ── Progress bar ─────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.hide()
        layout.addWidget(self._progress)

        # ── Filter / options bar ──────────────────────────────────────────
        fbar = QGridLayout()
        fbar.setColumnStretch(0, 0)
        fbar.setColumnStretch(1, 1)
        fbar.setColumnStretch(2, 0)
        fbar.setColumnStretch(3, 1)
        fbar.setColumnStretch(4, 0)
        fbar.setColumnStretch(5, 0)
        fbar.setColumnStretch(6, 0)
        fbar.setColumnStretch(7, 0)
        fbar.setColumnStretch(8, 0)

        # Exclude patterns
        self._exclude_edit = QLineEdit()
        self._exclude_edit.setPlaceholderText("e.g. node_modules, .git, WinSxS …")
        self._exclude_btn = QPushButton("Exclude")
        self._exclude_btn.setMaximumWidth(64)
        self._exclude_btn.clicked.connect(self._apply_exclude)

        # Min age
        self._min_age_spin = QSpinBox()
        self._min_age_spin.setRange(0, 9999)
        self._min_age_spin.setSuffix(" days")
        self._min_age_spin.setFixedWidth(100)
        self._min_age_spin.setToolTip("Skip files older than N days (0 = off)")

        # Auto-expand depth
        self._auto_expand_spin = QSpinBox()
        self._auto_expand_spin.setRange(0, 10)
        self._auto_expand_spin.setValue(2)
        self._auto_expand_spin.setSuffix(" levels")
        self._auto_expand_spin.setFixedWidth(90)
        self._auto_expand_spin.setToolTip("Auto-expand depth after scan (0 = collapsed)")

        # Select above threshold
        self._select_thresh_spin = QSpinBox()
        self._select_thresh_spin.setRange(0, 999999)
        self._select_thresh_spin.setSuffix(" MB")
        self._select_thresh_spin.setValue(100)
        self._select_thresh_spin.setFixedWidth(100)
        self._select_thresh_btn = QPushButton("Select ≥")
        self._select_thresh_btn.setMaximumWidth(70)
        self._select_thresh_btn.clicked.connect(self._select_above)

        # Live search
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("🔍 Filter by name…")
        self._search_edit.setMinimumWidth(160)
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._do_live_search)
        self._search_edit.textChanged.connect(
            lambda _: self._search_timer.start() if self._search_edit.text() else self._do_live_search()
        )
        self._search_edit.returnPressed.connect(self._search_edit.clear)

        # Scan history
        self._history_cb = QComboBox()
        self._history_cb.setMinimumWidth(120)
        self._history_cb.setToolTip("Previous scans")
        self._history_cb.activated.connect(self._on_history_selected)

        fbar.addWidget(QLabel("Exclude:"), 0, 0)
        fbar.addWidget(self._exclude_edit, 0, 1)
        fbar.addWidget(self._exclude_btn, 0, 2)
        fbar.addWidget(QLabel("Min age:"), 0, 3)
        fbar.addWidget(self._min_age_spin, 0, 4)
        fbar.addWidget(QLabel("Auto-expand:"), 0, 5)
        fbar.addWidget(self._auto_expand_spin, 0, 6)
        fbar.addWidget(self._select_thresh_btn, 0, 7)
        fbar.addWidget(self._select_thresh_spin, 0, 8)

        fbar2 = QHBoxLayout()
        fbar2.addWidget(QLabel("Search:"))
        fbar2.addWidget(self._search_edit, 1)
        fbar2.addWidget(QLabel("History:"))
        fbar2.addWidget(self._history_cb)
        fbar2.addStretch()
        layout.addLayout(fbar)
        layout.addLayout(fbar2)

        # ── Breadcrumb ───────────────────────────────────────────────────
        self._breadcrumb = _BreadcrumbBar()
        self._breadcrumb.path_clicked.connect(self._on_breadcrumb_clicked)
        layout.addWidget(self._breadcrumb)

        # ── Pie chart header ─────────────────────────────────────────────
        self._pie_chart = _PieChart()
        self._pie_chart.setMaximumHeight(100)
        layout.addWidget(self._pie_chart)

        # ── Top 10 files panel ───────────────────────────────────────────
        self._top_files_panel = _TopFilesPanel()
        layout.addWidget(self._top_files_panel)

        # ── Tree view ────────────────────────────────────────────────────
        self._model = DiskTreeModel()
        self._tree = QTreeView()
        self._tree.setModel(self._model)
        self._tree.setAlternatingRowColors(True)  # feature 12
        delegate = SizeBarDelegate()
        self._tree.setItemDelegateForColumn(COL_SIZE, delegate)
        self._tree.setItemDelegateForColumn(COL_NAME, delegate)
        hdr = self._tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.resizeSection(1, 160)
        hdr.setStretchLastSection(False)
        hdr.setSortIndicatorShown(True)
        self._tree.setSortingEnabled(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.setSelectionMode(QTreeView.SelectionMode.MultiSelection)
        layout.addWidget(self._tree, 1)

        # ── expand / collapse (moved here — _tree must exist first) ────
        self._expand_btn.clicked.connect(self._tree.expandAll)
        self._collapse_btn.clicked.connect(self._tree.collapseAll)

        # ── Status bar ───────────────────────────────────────────────────
        status_layout = QHBoxLayout()
        status_layout.setSpacing(8)
        self._status_lbl = QLabel("Ready")
        self._status_lbl.setStyleSheet("color: gray;")
        self._ad_badge = QLabel("🔒 0")
        self._ad_badge.setStyleSheet("color: #FF8800; font-weight: bold;")
        self._ad_badge.setVisible(False)
        self._scan_stats_lbl = QLabel("")
        self._scan_stats_lbl.setStyleSheet("color: gray;")
        status_layout.addWidget(self._status_lbl)
        status_layout.addStretch()
        status_layout.addWidget(self._ad_badge)
        status_layout.addWidget(self._scan_stats_lbl)

        status_widget = QWidget()
        status_widget.setLayout(status_layout)
        layout.addWidget(status_widget)

        # ── connections ─────────────────────────────────────────────────
        self._scan_btn.clicked.connect(self._do_scan)
        self._stop_btn.clicked.connect(self._do_stop)
        self._drive_cb.currentTextChanged.connect(self._on_drive_changed)
        self._tree.doubleClicked.connect(self._on_double_click)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        export_btn = QPushButton("Export…")
        export_btn.setMaximumWidth(80)
        export_btn.clicked.connect(self._do_export)
        status_layout.addWidget(export_btn)

        self._widget = w
        return w

    # ── scan ────────────────────────────────────────────────────────────────

    def _do_scan(self):
        if not self._scan_btn.isEnabled():
            return
        path = self._path_edit.text().strip()
        if not path or not os.path.isdir(path):
            self._status_lbl.setText("Invalid path.")
            return

        # Push to back history (feature 9)
        if self._current_scan_path and self._current_scan_path != path:
            if not self._nav_history or self._nav_history[-1] != self._current_scan_path:
                self._nav_history.append(self._current_scan_path)
                self._update_nav_buttons()

        self._current_scan_path = path
        self._breadcrumb.set_path(path)
        self._model.clear()
        self._scan_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._pause_btn.setEnabled(True)
        self._pause_btn.setText("Pause")
        self._is_paused = False
        self._progress.setRange(0, 0)
        self._progress.show()
        self._status_lbl.setText("Scanning…")
        self._ad_badge.setText("🔒 0")
        self._ad_badge.setVisible(False)
        self._scan_stats_lbl.setText("")
        self._top_files_panel.populate([])

        self._scanner = DiskScanner()

        # Apply exclude patterns
        excluded = [p.strip() for p in self._exclude_edit.text().split(",") if p.strip()]
        if excluded:
            self._scanner.set_excluded_patterns(excluded)

        # Apply min age
        self._scanner.set_min_age_days(self._min_age_spin.value())

        self._scanner.signals.batch_ready.connect(self._on_batch_ready)
        self._scanner.signals.node_replaced.connect(self._on_node_replaced)
        self._scanner.signals.progress.connect(self._on_progress)
        self._scanner.signals.access_denied.connect(self._on_access_denied)
        self._scanner.signals.finished.connect(self._on_scan_finished)
        self._scanner.signals.error.connect(self._on_scan_error)

        self._scan_thread = threading.Thread(
            target=self._scanner.scan, args=(path,), daemon=True,
        )
        self._scan_thread.start()

    def _on_batch_ready(self, nodes):
        self._model.add_batch(nodes)
        self._model.sort(COL_SIZE, Qt.SortOrder.DescendingOrder)
        self._tree.expandToDepth(self._auto_expand_spin.value())

    def _on_node_replaced(self, node):
        self._model.replace_node(node)

    def _on_progress(self, n):
        self._status_lbl.setText(f"Scanned {n:,} nodes…")

    def _on_access_denied(self, count):
        self._ad_badge.setText(f"🔒 {count}")
        self._ad_badge.setVisible(count > 0)

    def _on_scan_finished(self):
        # Store previous scan for delta
        self._model.store_last_scan()
        # Apply delta map to delegate
        delegate = self._tree.itemDelegateForColumn(COL_SIZE)
        if delegate:
            delegate.setDeltaMap(self._model.delta_map())

        import time
        stats = self._scanner.get_stats() if self._scanner else {}
        elapsed = time.time() - (self._scanner._start_time if self._scanner else 0)

        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._progress.hide()

        roots = self._model._roots
        total_size = sum(r.size for r in roots)
        total_files = sum(r.file_count for r in roots)
        now = datetime.datetime.now().strftime("%H:%M:%S")

        err_count = stats.get("errors", 0)
        skipped = stats.get("skipped", 0)
        ad_count = stats.get("access_denied", 0)

        stat_parts = [
            f"{len(roots)} items",
            format_size(total_size),
            f"{total_files:,} files",
            f"{int(elapsed)}s",
        ]
        if skipped:
            stat_parts.append(f"{skipped} skipped")
        if err_count:
            stat_parts.append(f"{err_count} errors")

        self._status_lbl.setText(
            f"{' · '.join(stat_parts)}  (scanned at {now})"
        )

        self._model.sort(COL_SIZE, Qt.SortOrder.DescendingOrder)
        self._tree.expandToDepth(self._auto_expand_spin.value())

        # Pie chart + top files (feature 21, 22)
        self._pie_chart.set_data(roots)
        top_files = self._model.get_top_files(10)
        self._top_files_panel.populate(top_files)

        # Add to scan history
        self._add_to_history(self._current_scan_path)

        # Start auto-refresh
        self._start_auto_refresh()

    def _on_scan_error(self, msg: str):
        self._scan_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._progress.hide()
        self._status_lbl.setText(f"Error: {msg}")

    def _do_stop(self):
        if self._scanner is not None:
            self._scanner.cancel()
        self._stop_btn.setEnabled(False)
        self._pause_btn.setEnabled(False)
        self._stop_auto_refresh()

    def _toggle_pause(self):
        if not self._scanner:
            return
        if self._is_paused:
            self._scanner.resume()
            self._pause_btn.setText("Pause")
            self._is_paused = False
        else:
            self._scanner.pause()
            self._pause_btn.setText("Resume")
            self._is_paused = True

    # ── auto-refresh ──────────────────────────────────────────────────────

    def _start_auto_refresh(self) -> None:
        self._stop_auto_refresh()
        if not self._auto_refresh_enabled:
            return
        self._auto_refresh_timer = QTimer()
        self._auto_refresh_timer.setInterval(30_000)
        self._auto_refresh_timer.timeout.connect(self._auto_rescan)
        self._auto_refresh_timer.start()

    def _stop_auto_refresh(self) -> None:
        if self._auto_refresh_timer is not None:
            self._auto_refresh_timer.stop()
            self._auto_refresh_timer.deleteLater()
            self._auto_refresh_timer = None

    def _auto_rescan(self) -> None:
        if not self._auto_refresh_enabled:
            return
        path = self._current_scan_path
        if path and os.path.isdir(path):
            self._path_edit.setText(path)
            self._do_scan()

    # ── live search ────────────────────────────────────────────────────────

    def _do_live_search(self) -> None:
        query = self._search_edit.text().strip()
        self._model.set_search_query(query)
        self._tree.expandToDepth(self._auto_expand_spin.value())

    # ── exclude patterns ───────────────────────────────────────────────────

    def _apply_exclude(self) -> None:
        patterns = [p.strip() for p in self._exclude_edit.text().split(",") if p.strip()]
        if self._scanner:
            self._scanner.set_excluded_patterns(patterns)

    # ── navigation: back / forward ─────────────────────────────────────────

    def _update_nav_buttons(self) -> None:
        self._back_btn.setEnabled(len(self._nav_history) > 0)
        self._fwd_btn.setEnabled(len(self._nav_forward) > 0)

    def _go_back(self) -> None:
        if not self._nav_history:
            return
        if self._current_scan_path:
            self._nav_forward.append(self._current_scan_path)
        prev = self._nav_history.pop()
        self._update_nav_buttons()
        self._path_edit.setText(prev)
        self._do_scan()

    def _go_forward(self) -> None:
        if not self._nav_forward:
            return
        if self._current_scan_path:
            self._nav_history.append(self._current_scan_path)
        nxt = self._nav_forward.pop()
        self._update_nav_buttons()
        self._path_edit.setText(nxt)
        self._do_scan()

    # ── breadcrumb navigation ───────────────────────────────────────────────

    def _on_breadcrumb_clicked(self, path: str) -> None:
        if path == self._current_scan_path:
            return
        if self._current_scan_path:
            self._nav_history.append(self._current_scan_path)
            self._nav_forward.clear()
        self._update_nav_buttons()
        self._path_edit.setText(path)
        self._do_scan()

    def _on_drive_changed(self, text: str):
        self._path_edit.setText(text)

    def _on_drive_dblclick(self) -> None:
        self._do_scan()

    # ── select above threshold ──────────────────────────────────────────────

    def _select_above(self) -> None:
        threshold_bytes = self._select_thresh_spin.value() * 1024 * 1024
        selection_model = self._tree.selectionModel()
        for row in range(self._model.rowCount()):
            idx = self._model.index(row, 0)
            node = idx.data(Qt.ItemDataRole.UserRole)
            if node and node.size >= threshold_bytes:
                selection_model.select(
                    idx,
                    QTreeView.selectionModel().Select | QTreeView.selectionModel().Rows,
                )

    # ── double-click drill-down ─────────────────────────────────────────────

    def _on_double_click(self, index):
        node = self._model.data(index, Qt.ItemDataRole.UserRole)
        if node and node.is_dir:
            if self._current_scan_path:
                self._nav_history.append(self._current_scan_path)
                self._nav_forward.clear()
                self._update_nav_buttons()
            self._path_edit.setText(node.path)
            self._do_scan()

    # ── context menu ───────────────────────────────────────────────────────

    def _on_context_menu(self, pos):
        index = self._tree.indexAt(pos)
        if not index.isValid():
            return
        node = self._model.data(index, Qt.ItemDataRole.UserRole)
        if not node:
            return

        # Build list of selected nodes
        selected_nodes = []
        for idx in self._tree.selectionModel().selectedRows():
            n = self._model.data(idx, Qt.ItemDataRole.UserRole)
            if n:
                selected_nodes.append(n)
        if node not in selected_nodes:
            selected_nodes = [node]

        menu = QMenu(self._tree)
        open_act = menu.addAction("Open in Explorer")
        copy_act = menu.addAction("Copy Path")
        menu.addSeparator()
        del_act = menu.addAction("Delete…")
        menu.addSeparator()
        prop_act = menu.addAction("Properties")

        chosen = menu.exec(self._tree.viewport().mapToGlobal(pos))

        if chosen == open_act:
            target = node.path if node.is_dir else os.path.dirname(node.path)
            os.startfile(target)

        elif chosen == copy_act:
            paths = "\n".join(n.path for n in selected_nodes)
            QApplication.clipboard().setText(paths)

        elif chosen == del_act:
            self._delete_selected(selected_nodes)

        elif chosen == prop_act:
            total = sum(n.size for n in selected_nodes)
            file_count = sum(n.file_count for n in selected_nodes)
            QMessageBox.information(
                self._widget, "Properties",
                f"Path: {node.path}\n"
                f"Size: {format_size(node.size)}\n"
                f"Files: {node.file_count:,}\n"
                f"Selected: {len(selected_nodes)} items · {format_size(total)}",
            )

    def _delete_selected(self, nodes: List) -> None:
        if not nodes:
            return
        total_size = sum(n.size for n in nodes)
        names = "\n".join(f"  • {n.path}" for n in nodes[:10])
        if len(nodes) > 10:
            names += f"\n  … and {len(nodes) - 10} more"

        reply = QMessageBox.question(
            self._widget, "Delete",
            f"Delete {len(nodes)} item(s) ({format_size(total_size)})?\n\n{names}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted = 0
        errors = 0
        for node in nodes:
            try:
                if node.is_dir:
                    shutil.rmtree(node.path, ignore_errors=True)
                else:
                    os.remove(node.path)
                deleted += 1
            except OSError:
                errors += 1

        self._do_scan()
        self._status_lbl.setText(
            f"Deleted {deleted} item(s)" + (f", {errors} errors" if errors else "")
        )

    # ── export (feature 24: JSON + CSV) ────────────────────────────────────

    def _do_export(self):
        if not self._widget:
            return
        path, _ = QFileDialog.getSaveFileName(
            self._widget, "Export", "",
            "All files (*.*)",
        )
        if not path:
            return

        # Auto-detect format
        is_json = path.lower().endswith(".json")

        def collect(node, rows):
            mod = ""
            if node.last_modified:
                mod = datetime.datetime.fromtimestamp(node.last_modified).strftime("%Y-%m-%d %H:%M")
            rows.append([node.path, format_size(node.size), node.file_count, mod])
            for child in node.children:
                collect(child, rows)

        if is_json:
            def to_dict(node):
                return {
                    "path": node.path,
                    "name": node.name,
                    "size": node.size,
                    "is_dir": node.is_dir,
                    "file_count": node.file_count,
                    "last_modified": node.last_modified,
                    "children": [to_dict(c) for c in node.children],
                }

            tree_data = {
                "scan_path": self._current_scan_path,
                "scanned_at": datetime.datetime.now().isoformat(),
                "roots": [to_dict(r) for r in self._model._roots],
            }
            with open(path, "w", encoding="utf-8") as f:
                json.dump(tree_data, f, indent=2)
            self._status_lbl.setText(f"Exported JSON to {os.path.basename(path)}")
        else:
            if not path.lower().endswith(".csv"):
                path += ".csv"
            rows = [["Path", "Size", "Files", "Last Modified"]]
            for root in self._model._roots:
                collect(root, rows)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            self._status_lbl.setText(f"Exported {len(rows) - 1} rows to {os.path.basename(path)}")

    # ── scan history (feature 25) ───────────────────────────────────────────

    def _add_to_history(self, path: str) -> None:
        now = datetime.datetime.now().timestamp()
        # Deduplicate
        self._scan_history = [h for h in self._scan_history if h["path"] != path]
        self._scan_history.insert(0, {"path": path, "timestamp": now})
        self._scan_history = self._scan_history[: self._history_limit]
        self._history_cb.blockSignals(True)
        self._history_cb.clear()
        for h in self._scan_history:
            label = os.path.basename(h["path"]) or h["path"]
            self._history_cb.addItem(label, h["path"])
        self._history_cb.blockSignals(False)

    def _on_history_selected(self, idx: int) -> None:
        path = self._history_cb.currentData()
        if path and path != self._current_scan_path:
            self._path_edit.setText(path)
            self._do_scan()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def on_activate(self) -> None:
        if not self._loaded:
            self._loaded = True
            self._path_edit.setText("C:\\")
            self._do_scan()

    def on_deactivate(self) -> None:
        self._stop_auto_refresh()

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self._do_stop()
        self._stop_auto_refresh()


# ── helper: double-click watcher for combo box ──────────────────────────────

class _DoubleClickWatcher(QObject):
    """Catch double-click events on a QComboBox's view (dropdown list)."""

    double_clicked = pyqtSignal()

    def __init__(self, combo: QComboBox, handler):
        super().__init__()
        self._handler = handler
        combo.view().viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonDblClick:
            self._handler()
            return True
        return False


# ── helper: keyboard event filter for the tree ─────────────────────────────

class _TreeEventFilter(QObject):
    """Catch keyboard shortcuts for the TreeSize module."""

    def __init__(self, module: "TreeSizeModule"):
        super().__init__()
        self._module = module

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress:
            return False
        key = event.key()
        mods = event.modifiers()

        if key == Qt.Key.Key_F and mods == Qt.KeyboardModifier.ControlModifier:
            # Ctrl+F → focus search
            self._module._search_edit.setFocus()
            self._module._search_edit.selectAll()
            return True

        if key == Qt.Key.Key_Backspace:
            # Backspace → go up one level
            path = self._module._current_scan_path
            if path:
                parent = os.path.dirname(path.rstrip("\\"))
                if parent and parent != path:
                    self._module._path_edit.setText(parent)
                    self._module._do_scan()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Enter → drill into selected node
            sel = self._module._tree.selectionModel().selectedRows(0)
            if sel:
                idx = sel[0]
                self._module._on_double_click(idx)
            return True

        return False
