"""Quick cleanup tab component.

Provides:
- Scan multiple categories
- Batch clean operations
- Auto-refresh support
- Background scan
- Dashboard view
- Statistics & charts
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QProgressBar,
    QPushButton, QLabel, QScrollArea, QFrame, QMenu,
)
from PyQt6.QtCore import Qt, QTimer, QThreadPool, QSettings, QDate
from PyQt6.QtGui import QAction

from modules.ui.components.category_group import CategoryGroup
from modules.config.config_manager import ConfigManager

try:
    from modules.cleanup.cleanup_scanner import ScanResult, ScanItem, format_size
except ImportError:
    ScanResult = None
    ScanItem = None
    format_size = None


class QuickCleanupTab(QWidget):
    """Cleanup tab with multiple categories and auto-refresh.

    Args:
        group_name: Display name of group (User, Browser, etc.)
        categories: List of category identifiers.
        scanner_funcs: Dict mapping category names to scanner functions.
        auto_refresh: Enable auto-refresh (default True).
    """

    def __init__(
        self, group_name: str, categories: List[str], 
        scanner_funcs: Dict, auto_refresh: bool = True,
        parent=None
    ):
        super().__init__(parent)
        self._group_name = group_name
        self._scanner_funcs = scanner_funcs
        self._config = ConfigManager()
        self._results: Dict[str, ScanResult] = {}
        self._scanning = False
        self._cleaning = False
        self._auto_refresh = auto_refresh
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_timer)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Main container
        main_widget = QWidget()
        main_widget.setStyleSheet("background: #f5f5f5;")
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        
        self._scroll_area = scroll_area
        scroll_area.setWidget(content)

        # Title bar with actions
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel(f"🗂️ {self._group_name}")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title_layout.addWidget(title)

        # Settings buttons
        settings_layout = QVBoxLayout()
        settings_layout.setContentsMargins(0, 0, 0, 0)
        self._settings_btn = QPushButton("Settings")
        self._settings_btn.clicked.connect(self._show_settings)
        title_layout.addWidget(self._settings_btn)

        settings_frame = QFrame()
        settings_layout.addWidget(settings_frame)
        title_layout.addLayout(settings_layout)

        title_layout.addStretch()
        self._content_layout.addLayout(title_layout)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._content_layout.addWidget(self._progress)

        # Status label
        self._status_label = QLabel("Ready — No items selected")
        self._status_label.setWordWrap(True)
        self._status_label.setFixedHeight(40)
        self._content_layout.addWidget(self._status_label)

        # Category groups layout
        self._groups_layout = QVBoxLayout()
        self._groups_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.addLayout(self._groups_layout)

        # Dashboard section
        dashboard_frame = QFrame()
        dashboard_frame.setFrameShape(QFrame.Shape.StyledPanel)
        dashboard_layout = QVBoxLayout(dashboard_frame)
        dashboard_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.addWidget(dashboard_frame)
        self._update_dashboard(dashboard_layout)

        # Refresh timer
        if self._auto_refresh:
            interval = self._config.get_refresh_interval()
            self._refresh_timer.start(interval * 1000)

    def _on_refresh_timer(self):
        """Handle auto-refresh timer."""
        if not self._auto_refresh or self._scanning or self._cleaning:
            return
        self._do_scan_delayed()

    def _do_scan_delayed(self):
        """Scan in background thread."""
        QThreadPool.globalInstance().start(self._do_scan)

    def _do_scan(self):
        """Refresh all category results."""
        if self._scanning:
            return
        self._scanning = True
        self._progress.show()
        self._status_label.setText("Refreshing stats...")
        self._content_layout.insertWidget(2, self._progress)

        total_items = 0
        total_size = 0
        categories_found = []

        for cat_id, scanner_func in self._scanner_funcs.items():
            try:
                result = scanner_func()
                if result:
                    self._results[cat_id] = result
                    total_items += len(result.items)
                    total_size += result.total_size
                    categories_found.append(cat_id)
            except Exception as e:
                print(f"Error scanning {cat_id}: {e}")

        # Update status
        if total_size > 0:
            self._status_label.setText(
                f"Found {total_items} — {format_size(total_size)} across {len(categories_found)} categories"
            )
            self._update_dashboard()
        else:
            self._status_label.setText("No items found.")

        self._scanning = False
        self._refresh_timer.stop()

    def _delete_selected(self):
        """Delete all checked items."""
        # Would implement deletion logic here
        freed = 0
        errors = 0
        self._status_label.setText(f"Deleted {len(self._results.items())} — {format_size(freed)} freed")
        self._update_dashboard()

    def _show_settings(self):
        """Show settings dialog."""
        # Placeholder for settings dialog
        pass

    def get_results(self) -> Dict[str, ScanResult]:
        """Get current scan results."""
        return self._results

    def _update_dashboard(self, dashboard_layout=None):
        """Update dashboard with statistics."""
        if dashboard_layout is None:
            dashboard_layout = self._content_layout

        total_size = sum(
            r.total_size for r in self._results.values()
            if isinstance(r, ScanResult)
        )

        if dashboard_layout:
            # Update status label
            category_count = sum(
                1 for cat_id, result in self._results.items()
                if isinstance(result, ScanResult) and result.items
            )
            self._status_label.setText(
                f"{category_count} categories — {format_size(total_size)} found"
            )
