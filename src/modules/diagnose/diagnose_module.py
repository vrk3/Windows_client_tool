import logging
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSplitter, QStackedWidget,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QTabWidget,
)

from ui.error_banner import ErrorBanner
from core.admin_utils import is_admin
from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.search_provider import SearchProvider, SearchQuery, SearchResult
from core.worker import Worker
from ui.log_table_widget import LogTableWidget
from ui.detail_panel import DetailPanel

from modules.cbs_log.cbs_parser import CBSParser
from modules.cbs_log.cbs_search_provider import CBSSearchProvider
from modules.dism_log.dism_parser import DISMParser
from modules.dism_log.dism_search_provider import DISMSearchProvider
from modules.event_viewer.event_reader import read_all_logs
from modules.event_viewer.event_search_provider import EventViewerSearchProvider
from modules.reliability.reliability_reader import read_reliability_records
from modules.reliability.reliability_search_provider import ReliabilitySearchProvider
from modules.crash_dumps.crash_dump_reader import read_crash_dumps
from modules.crash_dumps.crash_dump_search_provider import CrashDumpSearchProvider
from modules.windows_update.wu_parser import WUParser
from modules.windows_update.wu_search_provider import WUSearchProvider

# Log file paths
CBS_LOG_PATH = r"C:\Windows\Logs\CBS\CBS.log"
DISM_LOG_PATH = r"C:\Windows\Logs\DISM\dism.log"
WU_LOG_PATH = r"C:\Windows\SoftwareDistribution\ReportingEvents.log"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tab definitions
# ---------------------------------------------------------------------------

TAB_DEFS = [
    {
        "name": "Event Viewer",
        "icon": "📋",
        "parser_fn": "_load_event_viewer",
        "progress_label": "Loading Event Viewer…",
        "requires_admin": False,
    },
    {
        "name": "CBS Log",
        "icon": "📝",
        "parser_fn": "_load_cbs",
        "progress_label": "Loading CBS Log…",
        "requires_admin": False,
    },
    {
        "name": "DISM Log",
        "icon": "🔧",
        "parser_fn": "_load_dism",
        "progress_label": "Loading DISM Log…",
        "requires_admin": False,
    },
    {
        "name": "Windows Update",
        "icon": "🪟",
        "parser_fn": "_load_wu",
        "progress_label": "Loading Windows Update…",
        "requires_admin": False,
    },
    {
        "name": "Reliability",
        "icon": "📊",
        "parser_fn": "_load_reliability",
        "progress_label": "Loading Reliability Records…",
        "requires_admin": False,
    },
    {
        "name": "Crash Dumps",
        "icon": "💥",
        "parser_fn": "_load_crash_dumps",
        "progress_label": "Loading Crash Dumps…",
        "requires_admin": True,
    },
]


# ---------------------------------------------------------------------------
# Per-tab widget builder
# ---------------------------------------------------------------------------

def _build_tab_widget(
    parent: QWidget,
    progress_label: str,
    extra_controls_fn=None,
) -> tuple[QWidget, LogTableWidget, DetailPanel, QProgressBar, ErrorBanner, QStackedWidget, dict]:
    """Build a self-contained log viewer tab widget.

    Returns (container, table, detail, progress, error_banner, stack, extra)
    where extra is a dict for tab-specific controls (e.g. hours_combo).
    """
    container = QWidget(parent)
    vlayout = QVBoxLayout(container)
    vlayout.setContentsMargins(4, 4, 4, 4)
    vlayout.setSpacing(4)

    # Toolbar row
    toolbar = QHBoxLayout()
    toolbar.setSpacing(6)

    extra = {}
    if extra_controls_fn:
        extra_controls_fn(toolbar, extra)

    toolbar.addStretch()

    progress = QProgressBar()
    progress.setMaximumWidth(200)
    progress.setVisible(False)
    toolbar.addWidget(progress)

    refresh_btn = QPushButton("Refresh")
    refresh_btn.setObjectName("refreshBtn")
    toolbar.addWidget(refresh_btn)
    vlayout.addLayout(toolbar)

    # Error banner
    error_banner = ErrorBanner(parent=container)
    vlayout.addWidget(error_banner)

    # Splitter + stack
    splitter = QSplitter()
    table = LogTableWidget()
    splitter.addWidget(table)

    detail = DetailPanel()
    splitter.addWidget(detail)
    splitter.setSizes([700, 300])

    stack = QStackedWidget()
    stack.addWidget(splitter)
    empty_page = QLabel("No data — click Refresh")
    empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
    empty_page.setStyleSheet("color: #888; font-size: 14px;")
    stack.addWidget(empty_page)

    vlayout.addWidget(stack, 1)

    return container, table, detail, progress, error_banner, stack, extra


# ---------------------------------------------------------------------------
# DiagnoseModule
# ---------------------------------------------------------------------------

class DiagnoseModule(BaseModule):
    """Unified diagnostic hub — embeds all 6 diagnostic log viewers as
    sub-tabs with a unified search bar that searches across all of them.
    """

    name = "Diagnose"
    icon = "🩺"
    description = "Unified diagnostic hub — search across all logs, events, and crash reports"
    group = ModuleGroup.DIAGNOSE
    requires_admin = False

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._search_input: Optional[QLineEdit] = None
        self._search_progress: Optional[QProgressBar] = None
        self._clear_btn: Optional[QPushButton] = None
        self._tab_widget: Optional[QTabWidget] = None
        self._results_tree: Optional[QTreeWidget] = None

        # Per-tab state dict keyed by tab name
        self._tab_state: Dict[str, dict] = {}

        self._search_timer: Optional[QTimer] = None
        self._active_search: Optional[Worker] = None

    # ------------------------------------------------------------------
    # BaseModule contract
    # ------------------------------------------------------------------

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        root = QVBoxLayout(self._widget)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Unified search bar ─────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search across all diagnostic logs…")
        self._search_input.setMinimumHeight(32)
        self._search_input.returnPressed.connect(self._do_search)
        search_row.addWidget(self._search_input, 1)

        self._search_progress = QProgressBar()
        self._search_progress.setMaximumWidth(120)
        self._search_progress.setMaximum(0)
        self._search_progress.setVisible(False)
        search_row.addWidget(self._search_progress)

        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setMaximumWidth(60)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._clear_search)
        search_row.addWidget(self._clear_btn)

        root.addLayout(search_row)

        # Debounce timer for live search
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)
        self._search_input.textChanged.connect(
            lambda text: self._search_timer.start(300) if text else self._clear_search()
        )

        # ── Results tree (unified search output) ───────────────────────
        self._results_tree = QTreeWidget()
        self._results_tree.setHeaderLabels(["Time", "Source", "Summary"])
        self._results_tree.setColumnWidth(0, 160)
        self._results_tree.setColumnWidth(1, 120)
        self._results_tree.setAlternatingRowColors(True)
        self._results_tree.setRootIsDecorated(True)
        self._results_tree.setStyleSheet("""
            QTreeWidget {
                background: #2d2d2d;
                color: #e0e0e0;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
            }
            QTreeWidget::item { padding: 4px 0; }
            QTreeWidget::item:selected { background: #3c3c3c; }
            QHeaderView::section {
                background: #3c3c3c;
                color: #b0b0b0;
                padding: 4px;
                border: none;
            }
        """)
        self._results_tree.setVisible(False)
        root.addWidget(self._results_tree, 1)

        # ── Tab widget ─────────────────────────────────────────────────
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        for tab_def in TAB_DEFS:
            tab_name = tab_def["name"]
            container, table, detail, progress, error_banner, stack, extra = \
                _build_tab_widget(
                    self._widget,
                    progress_label=tab_def["progress_label"],
                    extra_controls_fn=(
                        lambda tb, ex, _tab_name=tab_name: self._build_event_viewer_controls(tb, ex)
                        if _tab_name == "Event Viewer"
                        else None
                    ),
                )

            # Wire Refresh button
            refresh_btn = container.findChild(QPushButton, "refreshBtn")
            if refresh_btn:
                refresh_btn.clicked.connect(
                    lambda checked, tn=tab_name: self._load_tab(tn)
                )

            # Store state
            self._tab_state[tab_name] = {
                "loaded": False,
                "entries": [],
                "table": table,
                "detail": detail,
                "progress": progress,
                "error_banner": error_banner,
                "stack": stack,
                "refresh_btn": refresh_btn,
                "extra": extra,
                "requires_admin": tab_def["requires_admin"],
                "provider": None,
            }

            # Set up search providers
            provider = self._make_provider(tab_name)
            self._tab_state[tab_name]["provider"] = provider

            self._tab_widget.addTab(container, tab_def["icon"] + " " + tab_name)

        root.addWidget(self._tab_widget, 1)

        return self._widget

    def _make_provider(self, tab_name: str) -> Optional[SearchProvider]:
        """Create the appropriate search provider for a tab."""
        providers = {
            "Event Viewer": EventViewerSearchProvider,
            "CBS Log": CBSSearchProvider,
            "DISM Log": DISMSearchProvider,
            "Windows Update": WUSearchProvider,
            "Reliability": ReliabilitySearchProvider,
            "Crash Dumps": CrashDumpSearchProvider,
        }
        cls = providers.get(tab_name)
        if cls:
            return cls()
        return None

    def on_start(self, app) -> None:
        self.app = app

    def on_activate(self) -> None:
        # Lazy-load the currently visible tab on first activation
        if self._tab_widget:
            idx = self._tab_widget.currentIndex()
            if idx >= 0:
                tab_name = self._tab_widget.tabText(idx).split(" ", 1)[-1]
                self._load_tab(tab_name)

    def on_deactivate(self) -> None:
        pass

    def on_stop(self) -> None:
        self.cancel_all_workers()
        if self._search_timer:
            self._search_timer.stop()

    def get_toolbar_actions(self) -> list:
        from PyQt6.QtGui import QAction
        actions = []
        refresh_all = QAction("Refresh All", None)
        refresh_all.triggered.connect(self._refresh_all_tabs)
        actions.append(refresh_all)
        return actions

    def get_status_info(self) -> str:
        return "Diagnose — unified diagnostic hub"

    def get_search_provider(self) -> Optional[SearchProvider]:
        return None  # Unified search is local to the widget

    # ------------------------------------------------------------------
    # Tab lazy-loading
    # ------------------------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        """Trigger lazy loading when user switches to a tab."""
        if index < 0:
            return
        tab_name = self._tab_widget.tabText(index).split(" ", 1)[-1]
        self._load_tab(tab_name)

    def _load_tab(self, tab_name: str, force: bool = False) -> None:
        """Load the specified tab (once unless force=True)."""
        state = self._tab_state.get(tab_name)
        if not state:
            return

        if state.get("loaded") and not force:
            return

        # Check admin requirement for Crash Dumps
        if state.get("requires_admin") and not is_admin():
            state["error_banner"].set_error(
                "Administrator privileges are required to view Crash Dumps."
            )
            state["stack"].setCurrentIndex(1)
            state["loaded"] = True  # mark loaded so we don't retry repeatedly
            return

        # Call the right parser method
        fn_name = None
        for td in TAB_DEFS:
            if td["name"] == tab_name:
                fn_name = td["parser_fn"]
                break

        if fn_name and hasattr(self, fn_name):
            getattr(self, fn_name)(tab_name)

    def _refresh_all_tabs(self) -> None:
        for tab_name in self._tab_state:
            self._load_tab(tab_name, force=True)

    # ------------------------------------------------------------------
    # Individual tab loaders
    # ------------------------------------------------------------------

    def _do_tab_load(
        self,
        tab_name: str,
        do_work_fn,
        on_done_fn,
    ) -> None:
        """Generic worker runner for all tab loaders."""
        state = self._tab_state.get(tab_name)
        if not state:
            return

        progress = state["progress"]
        error_banner = state["error_banner"]
        progress.setValue(0)
        progress.setVisible(True)
        error_banner.clear()

        def work(worker):
            return do_work_fn(worker)

        worker = Worker(work)
        worker.signals.progress.connect(lambda v: progress.setValue(v))
        worker.signals.result.connect(
            lambda entries: self._on_tab_loaded(tab_name, entries, on_done_fn)
        )
        worker.signals.error.connect(
            lambda err: self._on_tab_error(tab_name, err)
        )
        self._workers.append(worker)
        self.app.thread_pool.start(worker)

    def _on_tab_loaded(self, tab_name: str, entries, on_done_fn) -> None:
        state = self._tab_state.get(tab_name)
        if not state:
            return
        state["progress"].setVisible(False)
        state["loaded"] = True
        state["entries"] = entries
        table = state["table"]
        if table:
            table.set_entries(entries)
        provider = state["provider"]
        if provider and hasattr(provider, "set_entries"):
            try:
                provider.set_entries(entries)
            except Exception:
                pass
        state["stack"].setCurrentIndex(0 if entries else 1)
        logger.info("Tab '%s' loaded: %d entries", tab_name, len(entries) if entries else 0)
        if on_done_fn:
            on_done_fn(entries)

    def _on_tab_error(self, tab_name: str, error_info) -> None:
        state = self._tab_state.get(tab_name)
        if not state:
            return
        state["progress"].setVisible(False)
        state["error_banner"].set_error(str(error_info))
        state["stack"].setCurrentIndex(1)
        logger.error("Failed to load %s: %s", tab_name, error_info)

    # -- Event Viewer --------------------------------------------------------

    def _build_event_viewer_controls(self, toolbar: QHBoxLayout, extra: dict) -> None:
        toolbar.addWidget(QLabel("Time Range:"))
        combo = QComboBox()
        combo.addItems(["1 hour", "6 hours", "12 hours", "24 hours", "48 hours", "7 days"])
        combo.setCurrentIndex(3)  # Default: 24 hours
        toolbar.addWidget(combo)
        extra["hours_combo"] = combo

    def _load_event_viewer(self, tab_name: str) -> None:
        state = self._tab_state.get(tab_name)
        if not state:
            return
        hours_combo = state["extra"].get("hours_combo")
        hours_map = {"1 hour": 1, "6 hours": 6, "12 hours": 12, "24 hours": 24,
                     "48 hours": 48, "7 days": 168}
        hours_back = 24
        if hours_combo:
            hours_back = hours_map.get(hours_combo.currentText(), 24)

        def do_work(worker):
            return read_all_logs(
                hours_back=hours_back,
                max_events_per_log=2000,
                progress_callback=lambda p: worker.signals.progress.emit(p),
            )

        self._do_tab_load(tab_name, do_work, None)

    # -- CBS Log -------------------------------------------------------------

    def _load_cbs(self, tab_name: str) -> None:
        def do_work(worker):
            import os, subprocess, tempfile

            # Windows 11 stores CBS in .cab files under C:\Windows\Logs\CBS\
            if not os.path.exists(CBS_LOG_PATH):
                logger.info("CBS.log not found — trying to extract from cab archive")
                # Find the most recent CBS cab file
                cab_dir = os.path.dirname(CBS_LOG_PATH)
                cab_files = []
                try:
                    for f in os.listdir(cab_dir):
                        if f.startswith("CbsPersist_") and f.endswith(".cab"):
                            cab_files.append(os.path.join(cab_dir, f))
                except OSError:
                    pass

                if not cab_files:
                    logger.warning("No CBS cab files found in %s", cab_dir)
                    return []

                cab_files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                latest_cab = cab_files[0]

                # Try 7z if available
                seven_zip = r"C:\Program Files\7-Zip\7z.exe"
                if not os.path.exists(seven_zip):
                    seven_zip = r"C:\Program Files (x86)\7-Zip\7z.exe"

                tmp_dir = tempfile.mkdtemp(prefix="cbs_")
                log_path = os.path.join(tmp_dir, "CBS_extracted.log")

                if os.path.exists(seven_zip):
                    try:
                        subprocess.run(
                            [seven_zip, "e", latest_cab, f"-o{tmp_dir}", "-y"],
                            capture_output=True, timeout=30,
                        )
                    except Exception as ex:
                        logger.warning("7z extraction failed: %s", ex)

                if os.path.exists(log_path):
                    parser = CBSParser(log_path)
                    worker.signals.progress.emit(50)
                    entries = parser.parse(
                        progress_callback=lambda p: worker.signals.progress.emit(50 + p // 2)
                    )
                    # Clean up temp file
                    try:
                        os.unlink(log_path)
                        os.rmdir(tmp_dir)
                    except Exception:
                        pass
                    return entries
                else:
                    logger.warning("Could not extract CBS log from cab: %s", latest_cab)
                    return []

            parser = CBSParser(CBS_LOG_PATH)
            return parser.parse(
                progress_callback=lambda p: worker.signals.progress.emit(p)
            )

        self._do_tab_load(tab_name, do_work, None)

    # -- DISM Log ------------------------------------------------------------

    def _load_dism(self, tab_name: str) -> None:
        def do_work(worker):
            import os, subprocess

            if not os.path.exists(DISM_LOG_PATH):
                # DISM text log not found — try DISM API via PowerShell (non-admin: get hotfixes)
                logger.info("DISM.log not found — using Get-HotFix as fallback")
                ps_script = (
                    "Get-HotFix | Sort-Object InstalledOn -Descending | "
                    "Select-Object HotFixID,Description,InstalledOn,Caption | "
                    "ConvertTo-Json -Compress -Depth 2"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                    capture_output=True, text=True, timeout=30,
                )
                raw = result.stdout.strip()
                if not raw:
                    return []
                import json
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        data = [data]
                    # Convert to LogEntry format
                    entries = []
                    from core.types import LogEntry
                    from datetime import datetime
                    for entry in data:
                        installed_on = entry.get("InstalledOn", {})
                        ts_str = ""
                        if isinstance(installed_on, dict):
                            ts_str = installed_on.get("DateTime", "")
                        elif isinstance(installed_on, str):
                            ts_str = installed_on
                        ts = datetime.now()
                        for fmt in ("%A, %B %d, %Y %H:%M:%S", "%m/%d/%Y", "%Y-%m-%d"):
                            try:
                                ts = datetime.strptime(ts_str.split()[0], fmt)
                                break
                            except Exception:
                                pass
                        desc = str(entry.get("Description", ""))
                        kb = str(entry.get("HotFixID", ""))
                        entries.append(LogEntry(
                            timestamp=ts,
                            source="DISM/HotFix",
                            level="Info",
                            message=f"{kb} — {desc}",
                            raw=entry,
                        ))
                    return entries
                except Exception as ex:
                    logger.warning("Failed to parse Get-HotFix output: %s", ex)
                    return []

            parser = DISMParser(DISM_LOG_PATH)
            return parser.parse(
                progress_callback=lambda p: worker.signals.progress.emit(p)
            )

        self._do_tab_load(tab_name, do_work, None)

    # -- Windows Update -------------------------------------------------------

    def _load_wu(self, tab_name: str) -> None:
        def do_work(worker):
            parser = WUParser(WU_LOG_PATH)
            return parser.parse(
                progress_callback=lambda p: worker.signals.progress.emit(p)
            )

        self._do_tab_load(tab_name, do_work, None)

    # -- Reliability ----------------------------------------------------------

    def _load_reliability(self, tab_name: str) -> None:
        def do_work(worker):
            return read_reliability_records(
                max_records=1000,
                progress_callback=lambda p: worker.signals.progress.emit(p),
            )

        self._do_tab_load(tab_name, do_work, None)

    # -- Crash Dumps ---------------------------------------------------------

    def _load_crash_dumps(self, tab_name: str) -> None:
        def do_work(worker):
            return read_crash_dumps(
                progress_callback=lambda p: worker.signals.progress.emit(p)
            )

        self._do_tab_load(tab_name, do_work, None)

    # ------------------------------------------------------------------
    # Unified search
    # ------------------------------------------------------------------

    def _clear_search(self) -> None:
        """Reset search UI and show the tab widget."""
        if self._search_timer:
            self._search_timer.stop()
        if self._active_search:
            self._active_search.cancel()
            self._active_search = None

        self._search_input.blockSignals(True)
        self._search_input.clear()
        self._search_input.blockSignals(False)

        if self._search_progress:
            self._search_progress.setVisible(False)
        if self._results_tree:
            self._results_tree.clear()
            self._results_tree.setVisible(False)
        if self._tab_widget:
            self._tab_widget.setVisible(True)

    def _do_search(self) -> None:
        """Run unified search across all 6 tab providers."""
        query_text = self._search_input.text().strip()
        if not query_text:
            self._clear_search()
            return

        if self._search_progress:
            self._search_progress.setVisible(True)
        if self._results_tree:
            self._results_tree.clear()
            self._results_tree.setVisible(True)
        if self._tab_widget:
            self._tab_widget.setVisible(False)

        query = SearchQuery(text=query_text)

        def work(worker):
            all_results: List[SearchResult] = []
            for tab_name, state in self._tab_state.items():
                provider = state.get("provider")
                if provider is None:
                    continue
                try:
                    results = provider.search(query)
                    for r in results:
                        # Prefix source with tab name
                        r.source = f"{tab_name} / {r.source}"
                    all_results.extend(results)
                except Exception as ex:
                    logger.warning("Search provider '%s' failed: %s", tab_name, ex)
            return all_results

        if self._active_search:
            self._active_search.cancel()

        self._active_search = Worker(work)
        self._active_search.signals.result.connect(self._on_search_done)
        self._active_search.signals.error.connect(self._on_search_error)

        if self.app:
            self.app.thread_pool.start(self._active_search)

    def _on_search_done(self, results: List[SearchResult]) -> None:
        if self._search_progress:
            self._search_progress.setVisible(False)

        if not self._results_tree:
            return

        # Group by tab name (source before "/")
        by_tab: Dict[str, List[SearchResult]] = {}
        for r in results:
            tab = r.source.split(" / ", 1)[0] if " / " in r.source else r.source
            by_tab.setdefault(tab, []).append(r)

        # Sort tabs by result count descending
        for tab_name, tab_results in sorted(by_tab.items(), key=lambda x: -len(x[1])):
            count = len(tab_results)
            parent = QTreeWidgetItem(self._results_tree)
            parent.setText(0, f"{tab_name}  [{count} result{'s' if count != 1 else ''}]")
            parent.setExpanded(False)
            for r in tab_results[:200]:  # Cap at 200 per tab
                child = QTreeWidgetItem(parent)
                ts = r.timestamp.strftime("%Y-%m-%d %H:%M") if r.timestamp else "—"
                child.setText(0, ts)
                child.setText(1, r.type or "—")
                child.setText(2, r.summary[:200] if r.summary else "—")

        if self._results_tree.topLevelItemCount() == 0:
            empty = QTreeWidgetItem(self._results_tree)
            empty.setText(0, "(no results)")

    def _on_search_error(self, error) -> None:
        if self._search_progress:
            self._search_progress.setVisible(False)
        logger.error("Unified search error: %s", error)
