"""QuickCleanupTab — dashboard-style cleanup with pie chart and category groups.

Provides:
- Summary pie chart showing reclaimable space by category
- Per-category expandable group cards with scan/clean
- Batch "Clean All" across all categories
- Background scanning via Worker threads
- Auto-refresh (external control via start/stop)
"""
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, QThreadPool, pyqtSignal
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QScrollArea, QFrame,
    QSizePolicy,
)

from core.worker import Worker
from modules.ui.components.category_group import CategoryGroup


# ── Pie Chart ────────────────────────────────────────────────────────────────

class _PieChart(QWidget):
    """Pure-Qt donut chart showing reclaimable space by category."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slices: List[tuple] = []   # (label, size_bytes, color)
        self.setMinimumSize(120, 120)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_slices(self, slices: List[tuple]) -> None:
        """Set slices: list of (label, size_bytes, css_color_string)."""
        self._slices = slices
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        size = min(w, h)

        # Donut: outer radius = half the widget, inner radius = 40%
        cx = w / 2
        cy = h / 2
        outer_r = size / 2 - 4
        inner_r = outer_r * 0.45

        total = sum(s[1] for s in self._slices)
        if total == 0:
            # Draw empty grey ring
            painter.setPen(QPen(QColor("#555"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(int(cx - outer_r), int(cy - outer_r),
                                int(outer_r * 2), int(outer_r * 2))
            painter.setPen(QPen(QColor("#888")))
            painter.drawText(int(cx), int(cy), "No data")
            return

        start_angle = 0
        for label, size_bytes, color in self._slices:
            span = int(size_bytes / total * 360 * 16)
            painter.setPen(QPen(QColor(color), 2))
            painter.setBrush(QBrush(QColor(color)))
            rect_x = int(cx - outer_r)
            rect_y = int(cy - outer_r)
            rect_w = int(outer_r * 2)
            rect_h = int(outer_r * 2)
            painter.drawPie(rect_x, rect_y, rect_w, rect_h,
                           int(start_angle), int(span))
            start_angle += span

        # Inner circle (donut hole)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#2d2d2d")))
        painter.drawEllipse(int(cx - inner_r), int(cy - inner_r),
                            int(inner_r * 2), int(inner_r * 2))

        # Centre text: total size
        from modules.cleanup.cleanup_scanner import format_size
        painter.setPen(QColor("#ffffff"))
        font = QFont("Segoe UI", 8, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(int(cx), int(cy - 6), format_size(total))
        font2 = QFont("Segoe UI", 7)
        painter.setFont(font2)
        painter.setPen(QColor("#aaaaaa"))
        painter.drawText(int(cx), int(cy + 8), "reclaimable")


# ── Category slice card ───────────────────────────────────────────────────────

class _SliceCard(QFrame):
    """Small legend card shown below the pie chart for each category."""

    def __init__(self, label: str, size_bytes: int, color: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._color = color
        self._update_style(size_bytes)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        self._dot = QLabel(f"<span style='color:{color};font-size:14px'>●</span>")
        self._lbl = QLabel(f"<span style='color:#e0e0e0'>{label}</span>")
        self._lbl.setStyleSheet("font-size:12px")
        self._sz = QLabel()
        self._sz.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        from modules.cleanup.cleanup_scanner import format_size
        self._sz.setText(f"<span style='color:#aaaaaa;font-size:11px'>{format_size(size_bytes)}</span>")
        lay.addWidget(self._dot)
        lay.addWidget(self._lbl, 1)
        lay.addWidget(self._sz)

    def _update_style(self, size_bytes: int):
        alpha = "33" if size_bytes == 0 else "ff"
        color_with_alpha = self._color + alpha
        self.setStyleSheet(f"""
            QFrame {{
                background: #3c3c3c;
                border-left: 3px solid {self._color};
                border-radius: 4px;
                padding: 4px 8px;
            }}
        """)

    def set_size(self, size_bytes: int) -> None:
        """Update the displayed size and opacity."""
        from modules.cleanup.cleanup_scanner import format_size
        self._sz.setText(f"<span style='color:#aaaaaa;font-size:11px'>{format_size(size_bytes)}</span>")
        self._update_style(size_bytes)
        self.setVisible(size_bytes > 0)


# ── QuickCleanupTab ──────────────────────────────────────────────────────────

# Category definitions: (id, display_name, color)
# scanner_fn is resolved in build() from the _id_map
CLEANUP_CATEGORIES = [
    ("temp",      "Temp Files",       "#4fc3f7"),
    ("prefetch",  "Prefetch",         "#ffb74d"),
    ("thumb",     "Thumbnail Cache",  "#81c784"),
    ("crash",     "Crash Dumps",     "#ce93d8"),
    ("browser",   "Browser Caches",   "#4dd0e1"),
    ("app",       "App Caches",       "#a5d6a7"),
    ("logs",      "Windows Logs",     "#fff59d"),
    ("wu",        "Windows Update",   "#ff8a65"),
    ("large",     "Large Items",      "#ef9a9a"),
    ("dev",       "Dev Tools",        "#b0bec5"),
]


class QuickCleanupTab(QWidget):
    """
    Dashboard-style cleanup view with a donut chart and per-category groups.

    Lifecycle:
        - Construct, then call build() to create category groups.
        - Auto-refresh: call start_auto_refresh() / stop_auto_refresh().
        - scan() triggers a background rescan of all categories.
        - cancel() cancels any in-flight workers.
    """

    # Emitted when all scans complete: (total_items, total_size)
    scan_done = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._categories: List[tuple] = []   # (id, label, color, scanner_fn)
        self._group_widgets: Dict[str, CategoryGroup] = {}
        self._results: Dict[str, object] = {}   # id -> ScanResult
        self._scanning = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_timer_refresh)
        self._refresh_interval_ms = 30_000
        self._workers: List[Worker] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self, categories: List[tuple] = None) -> None:
        """Build the UI. Call once after construction.

        categories: list of (id, display_name, color, scanner_fn).
                    Defaults to CLEANUP_CATEGORIES.
        """
        if categories is None:
            categories = CLEANUP_CATEGORIES
        self._categories = categories

        # Patch in real scanner functions if IDs match
        from modules.cleanup import cleanup_scanner as cs
        from modules.cleanup import browser_scanner as bs
        _id_map = {
            "temp":     (cs.scan_temp_files,       "safe"),
            "prefetch": (cs.scan_prefetch,         "caution"),
            "thumb":    (cs.scan_thumbnail_cache,  "safe"),
            "crash":    (cs.scan_user_crash_dumps, "caution"),
            "browser":   (None,                     "safe"),  # handled specially
            "app":      (cs.scan_app_caches,        "safe"),
            "logs":     (cs.scan_windows_logs,     "caution"),
            "wu":       (cs.scan_wu_cache,           "caution"),
            "large":    (cs.scan_windows_old,        "caution"),
            "dev":      (cs.scan_dev_tool_caches,    "safe"),
        }

        self._scanner_map = {}
        self._browser_scanner = bs.detect_browsers  # for browser category

        for cid, clabel, ccolor in categories:
            fn_safety = _id_map.get(cid, (None, "safe"))
            self._scanner_map[cid] = (fn_safety[0], clabel, ccolor)

        self._setup_ui()

    def start_auto_refresh(self, interval_ms: int = 30_000) -> None:
        self._refresh_interval_ms = interval_ms
        self._refresh_timer.start(interval_ms)

    def stop_auto_refresh(self) -> None:
        self._refresh_timer.stop()

    def scan(self) -> None:
        """Trigger background scan of all categories. Idempotent."""
        if self._scanning:
            return
        self._do_scan_all()

    def cancel(self) -> None:
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        self._scanning = False
        self._scan_all_btn.setEnabled(True)
        self._clean_all_btn.setEnabled(True)

    # ── Setup ────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Top toolbar ──
        toolbar = QHBoxLayout()
        self._scan_all_btn = QPushButton("🔍  Scan All")
        self._scan_all_btn.clicked.connect(self.scan)
        self._clean_all_btn = QPushButton("🗑️  Clean All Safe")
        self._clean_all_btn.setEnabled(False)
        self._clean_all_btn.clicked.connect(self._do_clean_all_safe)
        self._status_lbl = QLabel("Click Scan All to analyze your system")
        self._status_lbl.setStyleSheet("color: #aaaaaa;")
        toolbar.addWidget(self._scan_all_btn)
        toolbar.addWidget(self._clean_all_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._status_lbl)
        layout.addLayout(toolbar)

        # Progress bar
        self._progress = QLabel()
        self._progress.setStyleSheet("color: #ffb74d; font-size: 11px;")
        self._progress.hide()
        layout.addWidget(self._progress)

        # ── Dashboard row: pie chart + legend ──
        dash_frame = QFrame()
        dash_frame.setFrameShape(QFrame.Shape.StyledPanel)
        dash_frame.setStyleSheet("""
            QFrame { background: #2d2d2d; border-radius: 8px; padding: 4px; }
        """)
        dash_lay = QHBoxLayout(dash_frame)
        dash_lay.setContentsMargins(12, 12, 12, 12)

        self._pie_chart = _PieChart()
        self._pie_chart.setFixedSize(160, 160)
        dash_lay.addWidget(self._pie_chart)

        # Legend
        self._legend_layout = QVBoxLayout()
        self._legend_layout.setSpacing(4)
        self._legend_cards: List[_SliceCard] = []
        for cid, clabel, ccolor in self._categories:
            card = _SliceCard(clabel, 0, ccolor)
            self._legend_cards.append(card)
            self._legend_layout.addWidget(card)
        self._legend_layout.addStretch()
        dash_lay.addLayout(self._legend_layout, 1)

        # Summary stats on the right
        stats_lay = QVBoxLayout()
        stats_lay.setSpacing(6)
        self._total_lbl = QLabel("Total: —")
        self._total_lbl.setStyleSheet("color: #ffffff; font-size: 16px; font-weight: bold;")
        self._safe_lbl = QLabel("Safe to clean: —")
        self._safe_lbl.setStyleSheet("color: #81c784; font-size: 13px;")
        self._item_lbl = QLabel("Items found: —")
        self._item_lbl.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        self._cat_lbl = QLabel(f"Categories: {len(self._categories)}")
        self._cat_lbl.setStyleSheet("color: #aaaaaa; font-size: 12px;")
        stats_lay.addWidget(self._total_lbl)
        stats_lay.addWidget(self._safe_lbl)
        stats_lay.addWidget(self._item_lbl)
        stats_lay.addWidget(self._cat_lbl)
        stats_lay.addStretch()
        dash_lay.addLayout(stats_lay)
        dash_lay.addStretch()

        layout.addWidget(dash_frame)

        # ── Scrollable category groups ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 0, 0)
        content_lay.setSpacing(8)

        self._groups_container: List[CategoryGroup] = []
        for cid, clabel, ccolor in self._categories:
            fn_info = self._scanner_map.get(cid)
            if fn_info is None or fn_info[0] is None:
                continue
            scanner_fn, label, color = fn_info
            group = CategoryGroup(label, scanner_fn, auto_refresh=False)
            group.scan_done.connect(self._on_group_scan_done)
            self._groups_container.append(group)
            content_lay.addWidget(group)

        content_lay.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    # ── Auto-refresh ────────────────────────────────────────────────────────

    def _on_timer_refresh(self):
        if self._scanning:
            return
        self.scan()

    # ── Scan All ────────────────────────────────────────────────────────────

    def _do_scan_all(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_all_btn.setEnabled(False)
        self._clean_all_btn.setEnabled(False)
        self._progress.setText("🔍  Scanning all categories...")
        self._progress.show()
        self._results.clear()
        self._total_scanned = 0

        from modules.cleanup import cleanup_scanner as cs
        from modules.cleanup import browser_scanner as bs

        # Count how many scan targets (browser gets its own worker too)
        scan_targets = [cid for cid, _, _ in self._categories]

        for cid, clabel, ccolor in self._categories:
            fn_info = self._scanner_map.get(cid)
            if fn_info is None or fn_info[0] is None:
                if cid == "browser":
                    # Browser gets its own worker via detect_browsers
                    pass
                continue
            scanner_fn = fn_info[0]

            def _make_cb(c_id=cid):
                def _run(_worker):
                    r = scanner_fn(min_age_days=0)
                    return c_id, r

                def _done(data):
                    c_id, result = data
                    self._results[c_id] = result
                    self._total_scanned += 1
                    if self._total_scanned == len(scan_targets):
                        self._on_all_scanned()

                def _err(_e):
                    self._results[c_id] = cs.ScanResult()
                    self._total_scanned += 1
                    if self._total_scanned == len(scan_targets):
                        self._on_all_scanned()

                w = Worker(_run)
                w.signals.result.connect(_done)
                w.signals.error.connect(_err)
                self._workers.append(w)
                QThreadPool.globalInstance().start(w)

            _make_cb()

        # Browser detection as separate worker
        if "browser" in scan_targets:
            def _run_browser(_worker):
                return self._browser_scanner()

            def _done_browser(results):
                self._results["browser"] = results
                self._total_scanned += 1
                if self._total_scanned == len(scan_targets):
                    self._on_all_scanned()

            def _err_browser(_e):
                self._results["browser"] = []
                self._total_scanned += 1
                if self._total_scanned == len(scan_targets):
                    self._on_all_scanned()

            wb = Worker(_run_browser)
            wb.signals.result.connect(_done_browser)
            wb.signals.error.connect(_err_browser)
            self._workers.append(wb)
            QThreadPool.globalInstance().start(wb)

    def _on_all_scanned(self):
        self._scanning = False
        self._scan_all_btn.setEnabled(True)
        self._progress.hide()
        self._workers = [w for w in self._workers if not w.cancelled]

        from modules.cleanup import cleanup_scanner as cs
        from modules.cleanup import browser_scanner as bs

        # Build pie chart slices
        slices: List[tuple] = []
        total_size = 0
        total_safe = 0
        total_items = 0
        categories_with_data = 0

        for i, (cid, clabel, ccolor) in enumerate(self._categories):
            if cid == "browser":
                # detect_browsers() returns List[BrowserResult]; sum total_bytes
                browser_results: List[bs.BrowserResult] = self._results.get(cid, [])
                bsize = sum(r.total_bytes for r in browser_results)
                bitems = sum(len(r.profiles) for r in browser_results)
                if bsize > 0:
                    slices.append((clabel, bsize, ccolor))
                    total_size += bsize
                    total_items += bitems
                    categories_with_data += 1
                    if i < len(self._legend_cards):
                        self._legend_cards[i].set_size(bsize)
                else:
                    if i < len(self._legend_cards):
                        self._legend_cards[i].set_size(0)
            else:
                result: cs.ScanResult = self._results.get(cid, cs.ScanResult())
                if result.items:
                    slices.append((clabel, result.total_size, ccolor))
                    total_size += result.total_size
                    total_safe += sum(item.size for item in result.items if item.safety == "safe")
                    total_items += len(result.items)
                    categories_with_data += 1
                    if i < len(self._legend_cards):
                        self._legend_cards[i].set_size(result.total_size)
                else:
                    if i < len(self._legend_cards):
                        self._legend_cards[i].set_size(0)

        self._pie_chart.set_slices(slices)
        self._total_lbl.setText(f"Total: {cs.format_size(total_size)}")
        self._safe_lbl.setText(f"Safe to clean: {cs.format_size(total_safe)}")
        self._item_lbl.setText(f"Items found: {total_items}")
        self._clean_all_btn.setEnabled(total_safe > 0)
        self._status_lbl.setText(
            f"Found {total_items} item(s) across {categories_with_data} categories"
            if categories_with_data
            else "No reclaimable space found"
        )
        self.scan_done.emit(total_items, total_size)

    def _on_group_scan_done(self, item_count: int, total_size: int):
        """Forward from individual category groups."""
        pass  # Individual group scans don't update the dashboard summary

    # ── Clean All Safe ─────────────────────────────────────────────────────

    def _do_clean_all_safe(self):
        if self._scanning:
            return
        from modules.cleanup import cleanup_scanner as cs
        from modules.cleanup import browser_scanner as bs

        all_safe: List[cs.ScanItem] = []
        needs_wu = False
        total = 0
        browser_cats: List[bs.CacheCategory] = []

        for cid in self._results:
            if cid == "browser":
                browser_results: List[bs.BrowserResult] = self._results.get(cid, [])
                for r in browser_results:
                    for profile in r.profiles:
                        for cat in profile.categories:
                            if cat.size_bytes > 0:
                                browser_cats.append(cat)
                                total += cat.size_bytes
            else:
                result: cs.ScanResult = self._results.get(cid, cs.ScanResult())
                for item in result.items:
                    if item.safety == "safe":
                        item.selected = True
                        all_safe.append(item)
                        total += item.size
                if cid == "wu":
                    needs_wu = True

        if not all_safe and not browser_cats:
            return

        from PyQt6.QtWidgets import QMessageBox
        mb = QMessageBox(self)
        mb.setWindowTitle("Confirm Bulk Clean")
        mb.setIcon(QMessageBox.Icon.Warning)
        mb.setText(
            f"Clean <b>{cs.format_size(total)}</b> of safe items across "
            f"{len(all_safe) + len(browser_cats)} item(s)?<br>This cannot be undone."
        )
        mb.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        mb.setDefaultButton(QMessageBox.StandardButton.Cancel)
        if mb.exec() != QMessageBox.StandardButton.Ok:
            return

        self._scanning = True
        self._scan_all_btn.setEnabled(False)
        self._clean_all_btn.setEnabled(False)
        self._progress.setText("🗑️  Cleaning safe items...")
        self._progress.show()

        def _run(_worker):
            browser_freed = 0
            browser_errors = 0
            if browser_cats:
                browser_freed, browser_errors = bs.delete_selected(browser_cats)
            cs_freed = 0
            cs_errors = 0
            if all_safe:
                cs_freed, cs_errors = cs.delete_items(all_safe, stop_wuauserv=needs_wu)
            return (browser_freed + cs_freed), (browser_errors + cs_errors)

        def _done(result):
            deleted, errors = result
            self._scanning = False
            self._scan_all_btn.setEnabled(True)
            self._progress.hide()
            msg = f"Cleaned {deleted} item(s)"
            if errors:
                msg += f" — {errors} could not be deleted"
            self._status_lbl.setText(msg)
            # Rescan
            self.scan()

        def _err(e: str):
            self._scanning = False
            self._scan_all_btn.setEnabled(True)
            self._progress.hide()
            self._status_lbl.setText(f"Clean error: {e}")

        w = Worker(_run)
        w.signals.result.connect(_done)
        w.signals.error.connect(_err)
        self._workers.append(w)
        QThreadPool.globalInstance().start(w)
