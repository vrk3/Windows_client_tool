# src/modules/tweaks/tweaks_module.py
import logging
import os
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QTabWidget,
    QTextEdit, QToolBar, QVBoxLayout, QWidget,
)

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker
from modules.tweaks.tweak_engine import TweakEngine
from modules.tweaks.app_catalog import AppCatalog, PROTECTED_APPS_DEFAULT
from modules.tweaks.preset_manager import PresetManager

logger = logging.getLogger(__name__)

_DEFS_DIR = os.path.join(os.path.dirname(__file__), "definitions")
_CATEGORY_FILES = {
    "Privacy":     "privacy.json",
    "Performance": "performance.json",
    "Telemetry":   "telemetry.json",
    "UI Tweaks":   "ui_tweaks.json",
    "Services":    "services.json",
    "Gaming":      "gaming.json",
    "Security":    "security.json",
    "Network":     "network.json",
}


# ---------------------------------------------------------------------------
# Signals helper (must be QObject for pyqtSignal)
# ---------------------------------------------------------------------------

class _Signals(QObject):
    status_detected = pyqtSignal(str, str)   # tweak_id, status
    apply_done      = pyqtSignal(bool, list) # success, errors
    apps_detected   = pyqtSignal(set, set)   # installed_winget_ids, installed_appx


# ---------------------------------------------------------------------------
# DetailsPanel — shows tweak info when a row is clicked
# ---------------------------------------------------------------------------

class _DetailsPanel(QFrame):
    """Side panel showing full details of a selected tweak."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(280)
        self.setMaximumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self._title = QLabel()
        self._title.setWordWrap(True)
        self._title.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(self._title)

        self._risk = QLabel()
        layout.addWidget(self._risk)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("color: #aaaaaa;")
        layout.addWidget(self._desc)

        layout.addWidget(QLabel("Steps:"))
        self._steps = QTextEdit()
        self._steps.setReadOnly(True)
        self._steps.setMaximumHeight(200)
        layout.addWidget(self._steps)

        self._presets = QLabel()
        self._presets.setWordWrap(True)
        self._presets.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self._presets)

        layout.addStretch()

        self._apply_btn = QPushButton("Apply This Tweak")
        self._apply_btn.setEnabled(False)
        layout.addWidget(self._apply_btn)

        self._tweak = None
        self._apply_btn.clicked.connect(self._on_apply_clicked)

    def set_tweak(self, tweak: Optional[Dict]) -> None:
        self._tweak = tweak
        if tweak is None:
            self._title.setText("Select a tweak")
            self._risk.setText("")
            self._desc.setText("Click a tweak to see its details.")
            self._steps.setText("")
            self._presets.setText("")
            self._apply_btn.setEnabled(False)
            return

        self._title.setText(tweak["name"])

        risk = tweak.get("risk", "low")
        risk_color = "#f44747" if risk == "high" else "#e89000" if risk == "medium" else "#4ec9b0"
        self._risk.setText(f"<span style='color:{risk_color}'>RISK: {risk.upper()}</span>")

        self._desc.setText(tweak.get("description", "No description."))

        steps_text = ""
        for i, step in enumerate(tweak.get("steps", [])):
            step_type = step.get("type", "unknown")
            if step_type == "registry":
                steps_text += f"  [{i+1}] Registry: {step.get('key', '')}\\{step.get('value', '')} = {step.get('data', '')} ({step.get('kind', 'DWORD')})\n"
            elif step_type == "service":
                steps_text += f"  [{i+1}] Service: {step.get('name', '')} → start_type={step.get('start_type', '')}\n"
            elif step_type == "command":
                steps_text += f"  [{i+1}] Command: {step.get('cmd', '')[:80]}...\n"
            elif step_type == "script":
                steps_text += f"  [{i+1}] Script: {step.get('command', step.get('cmd', ''))[:80]}...\n"
            elif step_type == "appx":
                steps_text += f"  [{i+1}] AppX Remove: {step.get('package', '')}\n"
            elif step_type == "scheduled_task":
                steps_text += f"  [{i+1}] Scheduled Task: {step.get('task_name', '')} → Disable\n"
        self._steps.setText(steps_text.strip() or "No steps defined.")

        self._presets.setText(f"ID: {tweak.get('id', '')}\nCategory: {tweak.get('category', '')}")

        self._apply_btn.setEnabled(True)

    def _on_apply_clicked(self) -> None:
        if self._tweak is not None:
            self.apply_requested.emit(self._tweak)

    apply_requested = pyqtSignal(dict)


# ---------------------------------------------------------------------------
# TweakRow — one row in a tweak tab
# ---------------------------------------------------------------------------

class TweakRow(QWidget):
    def __init__(self, tweak: Dict, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tweak = tweak
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)

        self.checkbox = QCheckBox()
        self.checkbox.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        layout.addWidget(self.checkbox)

        name_label = QLabel(tweak["name"])
        name_label.setToolTip(tweak.get("description", ""))
        name_label.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        layout.addWidget(name_label, stretch=1)

        risk = tweak.get("risk", "low")
        risk_label = QLabel(risk.upper())
        risk_label.setStyleSheet(
            "color: #f44747;" if risk == "high" else
            "color: #e89000;" if risk == "medium" else
            "color: #4ec9b0;"
        )
        risk_label.setFixedWidth(70)
        risk_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        risk_label.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        layout.addWidget(risk_label)

        self.status_label = QLabel("?")
        self.status_label.setFixedWidth(100)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        layout.addWidget(self.status_label)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setFixedWidth(70)
        self.apply_btn.setAttribute(Qt.WidgetAttribute.WA_LayoutUsesWidgetRect, True)
        layout.addWidget(self.apply_btn)

        # Row highlight on hover
        self.setStyleSheet(
            "TweakRow:hover { background-color: #2a2d2e; }"
        )

    def set_status(self, status: str) -> None:
        text_map = {
            "applied": "✅ Applied",
            "not_applied": "— Not Applied",
            "unknown": "? Unknown",
        }
        self.status_label.setText(text_map.get(status, status))

    @property
    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.setChecked(checked)


# ---------------------------------------------------------------------------
# TweakTab — one category tab (Privacy, Performance, etc.)
# ---------------------------------------------------------------------------

class TweakTab(QWidget):
    def __init__(self, tweaks: List[Dict], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._tweaks = tweaks
        self._rows: Dict[str, TweakRow] = {}
        self._filter_text = ""
        self._filter_risk = "all"
        self._filter_status = "all"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Control bar
        bar = QHBoxLayout()
        bar.setContentsMargins(4, 4, 4, 4)
        bar.setSpacing(4)

        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setFixedWidth(80)
        bar.addWidget(self._select_all_btn)

        self._deselect_all_btn = QPushButton("Deselect All")
        self._deselect_all_btn.setFixedWidth(90)
        bar.addWidget(self._deselect_all_btn)

        self._select_applied_btn = QPushButton("Select Applied")
        self._select_applied_btn.setFixedWidth(100)
        bar.addWidget(self._select_applied_btn)

        self._select_not_btn = QPushButton("Select Not Applied")
        self._select_not_btn.setFixedWidth(110)
        bar.addWidget(self._select_not_btn)

        bar.addStretch()

        self._count_label = QLabel("0 selected")
        bar.addWidget(self._count_label)

        layout.addLayout(bar)

        # Scroll area with rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)

        container = QWidget()
        self._container_layout = QVBoxLayout(container)
        self._container_layout.setSpacing(1)
        self._container_layout.setContentsMargins(0, 0, 0, 0)

        for tweak in tweaks:
            row = TweakRow(tweak)
            self._rows[tweak["id"]] = row
            self._container_layout.addWidget(row)

        self._container_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # Wire selection count update
        for row in self._rows.values():
            row.checkbox.stateChanged.connect(self._on_selection_changed)

    def apply_row_clicked(self, row: TweakRow) -> None:
        self.row_apply_requested.emit(row.tweak)

    def set_row_apply_handler(self, handler) -> None:
        for row in self._rows.values():
            row.apply_btn.clicked.connect(lambda _, r=row: handler(r))

    def _on_selection_changed(self) -> None:
        count = sum(1 for r in self._rows.values() if r.is_checked)
        self._count_label.setText(f"{count} selected")

    def set_status(self, tweak_id: str, status: str) -> None:
        if tweak_id in self._rows:
            self._rows[tweak_id].set_status(status)

    def selected_tweaks(self) -> List[Dict]:
        return [t for t in self._tweaks
                if self._rows[t["id"]].is_checked]

    def apply_preset(self, tweak_ids: List[str]) -> None:
        for tweak_id, row in self._rows.items():
            row.set_checked(tweak_id in tweak_ids)

    def current_state(self) -> List[str]:
        return [t["id"] for t in self._tweaks
                if self._rows[t["id"]].is_checked]

    def select_all(self) -> None:
        for row in self._rows.values():
            row.set_checked(True)

    def deselect_all(self) -> None:
        for row in self._rows.values():
            row.set_checked(False)

    def select_by_status(self, status: str) -> None:
        """status: 'applied', 'not_applied', or 'all'"""
        for row in self._rows.values():
            if status == "all":
                row.set_checked(True)
            else:
                label_text = row.status_label.text()
                if status == "applied" and "Applied" in label_text:
                    row.set_checked(True)
                elif status == "not_applied" and "Not Applied" in label_text:
                    row.set_checked(True)

    # Signal emitted when row selection should show details
    row_selected = pyqtSignal(dict)
    row_apply_requested = pyqtSignal(dict)

    def mousePressEvent(self, event) -> None:
        # Find which row was clicked
        child = self.childAt(event.pos())
        if child:
            for row in self._rows.values():
                if row.isAncestorOf(child):
                    self.row_selected.emit(row.tweak)
                    break
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# AppManagerTab
# ---------------------------------------------------------------------------

class AppManagerTab(QWidget):
    def __init__(self, catalog: AppCatalog, config,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._catalog = catalog
        self._config = config
        self._protected = set(
            config.get("tweaks.protected_apps", list(PROTECTED_APPS_DEFAULT))
            if config is not None else list(PROTECTED_APPS_DEFAULT)
        )
        self._remove_queue: set = set()
        self._install_queue: set = set()

        layout = QVBoxLayout(self)

        # Filter bar
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Category:"))
        self._cat_combo = QComboBox()
        self._cat_combo.addItem("All")
        self._cat_combo.addItems(catalog.categories())
        self._cat_combo.currentTextChanged.connect(self._refresh_catalog_list)
        filter_bar.addWidget(self._cat_combo)
        filter_bar.addStretch()
        layout.addLayout(filter_bar)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # Installed section
        installed_group = QGroupBox("Installed AppX Packages (check to remove)")
        ig_layout = QVBoxLayout(installed_group)
        self._installed_list = QListWidget()
        ig_layout.addWidget(self._installed_list)
        splitter.addWidget(installed_group)

        # Catalog section
        catalog_group = QGroupBox("Available to Install (via winget)")
        cg_layout = QVBoxLayout(catalog_group)
        self._catalog_list = QListWidget()
        self._catalog_list.itemChanged.connect(self._on_catalog_item_changed)
        cg_layout.addWidget(self._catalog_list)
        splitter.addWidget(catalog_group)

        layout.addWidget(splitter)

        # Apply bar
        apply_bar = QHBoxLayout()
        self._apply_label = QLabel("No changes queued")
        apply_bar.addWidget(self._apply_label)
        apply_bar.addStretch()
        self._apply_btn = QPushButton("Apply Changes")
        self._apply_btn.setEnabled(False)
        apply_bar.addWidget(self._apply_btn)
        layout.addLayout(apply_bar)

        self._refresh_catalog_list()

    def populate_installed(self, installed_appx: set) -> None:
        self._installed_list.clear()
        for pkg in sorted(installed_appx):
            item = QListWidgetItem(pkg)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if pkg in self._protected:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setText(f"{pkg}  🔒")
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, pkg)
            self._installed_list.addItem(item)

    def populate_installed_winget(self, installed_ids: set) -> None:
        self._installed_winget = installed_ids
        self._refresh_catalog_list()

    def _refresh_catalog_list(self) -> None:
        cat = self._cat_combo.currentText()
        entries = self._catalog.filter_by_category(cat)
        installed = getattr(self, "_installed_winget", set())
        self._catalog_list.clear()
        for entry in entries:
            item = QListWidgetItem(
                f"{entry['name']}  ({entry['publisher']})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            already = entry["winget_id"] in installed
            item.setCheckState(
                Qt.CheckState.Checked if entry["winget_id"] in self._install_queue
                else Qt.CheckState.Unchecked
            )
            if already:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setText(item.text() + "  ✅ Installed")
            item.setData(Qt.ItemDataRole.UserRole, entry["winget_id"])
            item.setToolTip(entry.get("description", ""))
            self._catalog_list.addItem(item)

    def _on_catalog_item_changed(self, item: QListWidgetItem) -> None:
        wid = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._install_queue.add(wid)
        else:
            self._install_queue.discard(wid)
        self._update_apply_label()

    def _update_apply_label(self) -> None:
        n_remove = len(self._remove_queue)
        n_install = len(self._install_queue)
        if n_remove + n_install == 0:
            self._apply_label.setText("No changes queued")
            self._apply_btn.setEnabled(False)
        else:
            self._apply_label.setText(
                f"Remove {n_remove}, Install {n_install}")
            self._apply_btn.setEnabled(True)


# ---------------------------------------------------------------------------
# TweaksModule
# ---------------------------------------------------------------------------

class TweaksModule(BaseModule):
    name         = "Tweaks"
    icon         = "🧹"
    description  = "Debloater, privacy, performance, telemetry and UI tweaks."
    requires_admin = True
    group        = ModuleGroup.OPTIMIZE

    def __init__(self):
        super().__init__()
        self._widget: Optional[QWidget] = None
        self._tab_widgets: Dict[str, TweakTab] = {}
        self._app_tab: Optional[AppManagerTab] = None
        self._engine: Optional[TweakEngine] = None
        self._preset_mgr: Optional[PresetManager] = None
        self._catalog: Optional[AppCatalog] = None
        self._progress: Optional[QProgressBar] = None
        self._log_output: Optional[QTextEdit] = None
        self._tabs: Optional[QTabWidget] = None
        self._signals = _Signals()
        self._tweaks_loaded = False
        self._details_panel: Optional[_DetailsPanel] = None

    # ------------------------------------------------------------------
    # BaseModule lifecycle
    # ------------------------------------------------------------------

    def on_start(self, app) -> None:
        self.app = app
        self._engine = TweakEngine(backup_service=app.backup)
        self._preset_mgr = PresetManager()
        self._catalog = AppCatalog()

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def on_activate(self) -> None:
        if not self._tweaks_loaded:
            self._tweaks_loaded = True
            self._detect_statuses()
            self._detect_apps()

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def get_status_info(self) -> str:
        return "Tweaks & Debloater"

    # ------------------------------------------------------------------
    # Widget
    # ------------------------------------------------------------------

    def create_widget(self) -> QWidget:
        self._widget = QWidget()
        layout = QVBoxLayout(self._widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Top: preset toolbar + search bar
        top_layout = QVBoxLayout()
        top_layout.setSpacing(4)
        top_layout.addWidget(self._build_preset_toolbar())
        top_layout.addWidget(self._build_search_bar())
        layout.addLayout(top_layout)

        # Main: tabs with details panel side-by-side
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._tabs = QTabWidget()
        for category, filename in _CATEGORY_FILES.items():
            path = os.path.join(_DEFS_DIR, filename)
            tweaks = TweakEngine.load_definitions(path)
            tab = TweakTab(tweaks)
            self._tab_widgets[category] = tab
            self._tabs.addTab(tab, category)
            tab.row_selected.connect(self._on_row_selected)
            tab.set_row_apply_handler(self._on_row_apply)

        config = self.app.config if self.app else None
        self._app_tab = AppManagerTab(self._catalog, config)
        self._tabs.addTab(self._app_tab, "Apps")

        main_splitter.addWidget(self._tabs)

        self._details_panel = _DetailsPanel()
        self._details_panel.apply_requested.connect(self._on_apply_single_tweak)
        main_splitter.addWidget(self._details_panel)
        main_splitter.setSizes([700, 300])

        layout.addWidget(main_splitter, stretch=1)

        layout.addWidget(self._build_bottom_bar())
        self._signals.status_detected.connect(self._on_status_detected)
        self._signals.apps_detected.connect(self._on_apps_detected)
        return self._widget

    def _build_search_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(QLabel("Search:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Filter tweaks by name or description...")
        self._search_input.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_input, stretch=1)

        # Risk filter
        layout.addWidget(QLabel("Risk:"))
        self._risk_filter = QComboBox()
        self._risk_filter.addItems(["All", "Low", "Medium", "High"])
        self._risk_filter.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self._risk_filter)

        # Status filter
        layout.addWidget(QLabel("Status:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems(["All", "Applied", "Not Applied", "Unknown"])
        self._status_filter.currentTextChanged.connect(self._on_filter_changed)
        layout.addWidget(self._status_filter)

        return bar

    def _build_preset_toolbar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Preset:"))
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(180)
        self._refresh_preset_combo()
        layout.addWidget(self._preset_combo)

        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._on_load_preset)
        layout.addWidget(load_btn)

        save_btn = QPushButton("Save As…")
        save_btn.clicked.connect(self._on_save_preset)
        layout.addWidget(save_btn)

        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._on_export_preset)
        layout.addWidget(export_btn)

        import_btn = QPushButton("Import…")
        import_btn.clicked.connect(self._on_import_preset)
        layout.addWidget(import_btn)

        layout.addStretch()

        self._select_all_global_btn = QPushButton("Select All in Tab")
        self._select_all_global_btn.clicked.connect(self._on_select_all_tab)
        layout.addWidget(self._select_all_global_btn)

        self._deselect_all_global_btn = QPushButton("Deselect All in Tab")
        self._deselect_all_global_btn.clicked.connect(self._on_deselect_all_tab)
        layout.addWidget(self._deselect_all_global_btn)

        return bar

    def _build_bottom_bar(self) -> QWidget:
        bar = QWidget()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(0, 0, 0, 0)

        self._apply_btn = QPushButton("Apply Selected")
        self._apply_btn.clicked.connect(self._on_apply)
        layout.addWidget(self._apply_btn)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setMaximumWidth(200)
        layout.addWidget(self._progress)

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setMaximumHeight(80)
        self._log_output.setVisible(False)
        layout.addWidget(self._log_output, stretch=1)

        return bar

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        self._filter_tweaks()

    def _on_filter_changed(self) -> None:
        self._filter_tweaks()

    def _filter_tweaks(self) -> None:
        search_text = self._search_input.text().lower()
        risk_filter = self._risk_filter.currentText().lower()
        status_filter = self._status_filter.currentText()

        for tab in self._tab_widgets.values():
            for tweak in tab._tweaks:
                row = tab._rows.get(tweak["id"])
                if row is None:
                    continue

                # Text match
                name_match = not search_text or (
                    search_text in tweak["name"].lower() or
                    search_text in tweak.get("description", "").lower()
                )

                # Risk match
                risk_match = risk_filter == "all" or tweak.get("risk", "low") == risk_filter

                # Status match
                status_text = row.status_label.text()
                if status_filter == "All":
                    status_match = True
                elif status_filter == "Applied":
                    status_match = "Applied" in status_text
                elif status_filter == "Not Applied":
                    status_match = "Not Applied" in status_text
                else:
                    status_match = "?" in status_text

                visible = name_match and risk_match and status_match
                row.setVisible(visible)

    # ------------------------------------------------------------------
    # Row interaction
    # ------------------------------------------------------------------

    def _on_row_selected(self, tweak: Dict) -> None:
        self._details_panel.set_tweak(tweak)

    def _on_row_apply(self, row: TweakRow) -> None:
        self._on_apply_single_tweak(row.tweak)

    def _on_apply_single_tweak(self, tweak: Dict) -> None:
        if not self.app:
            return

        risk = tweak.get("risk", "low")
        if risk == "high":
            reply = QMessageBox.question(
                self._widget, "Confirm High-Risk Tweak",
                f"You're about to apply a HIGH RISK tweak:\n\n{tweak['name']}\n\n"
                "Are you sure you want to continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        rp_id = self.app.backup.create_restore_point(
            f"Single tweak: {tweak['name']}", "Tweaks")

        errors = []

        def _worker_fn(worker):
            self._engine.apply_tweak(
                tweak, rp_id,
                on_error=lambda e: errors.append(e))
            return errors

        w = Worker(_worker_fn)
        w.signals.result.connect(self._on_single_apply_result)
        w.signals.error.connect(lambda e: self._log_output.append(f"Error: {e}"))
        self._workers.append(w)
        self.app.thread_pool.start(w)

    def _on_single_apply_result(self, errors: list) -> None:
        if self._log_output:
            if errors:
                for e in errors:
                    self._log_output.append(f"⚠ {e}")
            else:
                self._log_output.append("✅ Tweak applied successfully.")
        self._detect_statuses()

    # ------------------------------------------------------------------
    # Preset actions
    # ------------------------------------------------------------------

    def _refresh_preset_combo(self) -> None:
        if not self._preset_mgr:
            return
        self._preset_combo.clear()
        for p in self._preset_mgr.list_presets():
            self._preset_combo.addItem(p["name"])

    def _on_load_preset(self) -> None:
        name = self._preset_combo.currentText()
        if not name or not self._preset_mgr:
            return
        try:
            preset = self._preset_mgr.load_preset(name)
        except KeyError as e:
            QMessageBox.warning(self._widget, "Preset", str(e))
            return
        tweaks = preset.get("tweaks", {})
        for category, tab in self._tab_widgets.items():
            ids = tweaks.get(category.lower().replace(" ", "_"), [])
            if not ids:
                ids = tweaks.get(category, [])
            tab.apply_preset(ids)

    def _on_save_preset(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self._widget, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        data = {
            "name": name.strip(), "version": 1,
            "tweaks": {cat: tab.current_state()
                       for cat, tab in self._tab_widgets.items()},
            "apps": {"remove": [], "install": [], "protected": []}
        }
        self._preset_mgr.save_preset(name.strip(), data)
        self._refresh_preset_combo()

    def _on_export_preset(self) -> None:
        name = self._preset_combo.currentText()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self._widget, "Export Preset", f"{name}.json",
            "JSON (*.json);;ZIP (*.zip)")
        if path:
            self._preset_mgr.export_preset(name, path)

    def _on_import_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self._widget, "Import Preset", "",
            "Preset files (*.json *.zip)")
        if path:
            try:
                name = self._preset_mgr.import_preset(path)
                self._refresh_preset_combo()
                QMessageBox.information(
                    self._widget, "Import", f"Preset '{name}' imported.")
            except Exception as e:
                QMessageBox.critical(self._widget, "Import failed", str(e))

    def _on_select_all_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < len(self._tab_widgets):
            tab = list(self._tab_widgets.values())[idx]
            tab.select_all()

    def _on_deselect_all_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx < len(self._tab_widgets):
            tab = list(self._tab_widgets.values())[idx]
            tab.deselect_all()

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        tweaks_to_apply = []
        for tab in self._tab_widgets.values():
            tweaks_to_apply.extend(tab.selected_tweaks())

        if not tweaks_to_apply:
            QMessageBox.information(
                self._widget, "Nothing selected",
                "Check at least one tweak to apply.")
            return

        if not self.app:
            return

        rp_id = self.app.backup.create_restore_point(
            "Tweaks session", "Tweaks")

        self._apply_btn.setEnabled(False)
        self._progress.setMaximum(len(tweaks_to_apply))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._log_output.clear()
        self._log_output.setVisible(True)
        errors = []

        def _worker_fn(worker):
            for i, tweak in enumerate(tweaks_to_apply):
                if worker.is_cancelled:
                    break
                self._engine.apply_tweak(
                    tweak, rp_id,
                    on_error=lambda e: errors.append(e))
                worker.signals.progress.emit(i + 1)
            return errors

        w = Worker(_worker_fn)
        w.signals.progress.connect(self._progress.setValue)
        w.signals.result.connect(self._on_apply_result)
        w.signals.error.connect(
            lambda e: self._log_output.append(f"Error: {e}"))
        self._workers.append(w)
        self.app.thread_pool.start(w)

    def _on_apply_result(self, errors: list) -> None:
        self._apply_btn.setEnabled(True)
        self._progress.setVisible(False)
        for e in errors:
            self._log_output.append(f"⚠ {e}")
        if not errors:
            self._log_output.append("✅ All tweaks applied successfully.")
        self._detect_statuses()

    # ------------------------------------------------------------------
    # Status detection
    # ------------------------------------------------------------------

    def _detect_statuses(self) -> None:
        if not self._engine:
            return
        all_tweaks = []
        for tab in self._tab_widgets.values():
            all_tweaks.extend(tab._tweaks)

        def _worker_fn(worker):
            for tweak in all_tweaks:
                if worker.is_cancelled:
                    break
                status = self._engine.detect_status(tweak)
                self._signals.status_detected.emit(tweak["id"], status)
            return None

        w = Worker(_worker_fn)
        self._workers.append(w)
        if self.app:
            self.app.thread_pool.start(w)

    def _on_status_detected(self, tweak_id: str, status: str) -> None:
        for tab in self._tab_widgets.values():
            tab.set_status(tweak_id, status)
        self._filter_tweaks()  # Re-apply status filter if needed

    # ------------------------------------------------------------------
    # App detection
    # ------------------------------------------------------------------

    def _detect_apps(self) -> None:
        if not self._catalog or not self._app_tab:
            return

        def _worker_fn(worker):
            installed_ids = self._catalog.detect_installed_winget()
            installed_appx = self._catalog.detect_installed_appx()
            return installed_ids, installed_appx

        def _on_result(result):
            installed_ids, installed_appx = result
            self._signals.apps_detected.emit(installed_ids, installed_appx)

        w = Worker(_worker_fn)
        w.signals.result.connect(_on_result)
        self._workers.append(w)
        if self.app:
            self.app.thread_pool.start(w)

    def _on_apps_detected(self, installed_ids: set, installed_appx: set) -> None:
        if self._app_tab:
            self._app_tab.populate_installed(installed_appx)
            self._app_tab.populate_installed_winget(installed_ids)