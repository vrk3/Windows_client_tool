"""_OverviewTab — summary of all cleanup categories, scans all in parallel."""
import logging
from typing import Optional

from PyQt6.QtCore import Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QProgressBar,
    QHeaderView,
)

from core.worker import Worker
from modules.cleanup import cleanup_scanner as cs
from modules.cleanup import browser_scanner as bs


logger = logging.getLogger(__name__)


_OV_GROUPS = [
    ("System Junk", [
        cs.scan_temp_files, cs.scan_prefetch, cs.scan_thumbnail_cache, cs.scan_user_crash_dumps,
    ]),
    ("Browser Caches", None),    # handled specially via bs.detect_browsers()
    ("App & Game Caches", [
        cs.scan_app_caches, cs.scan_d3d_shader_cache, cs.scan_appdata_autodiscover,
        cs.scan_steam_cache, cs.scan_stremio_cache, cs.scan_outlook_cache,
        cs.scan_winget_packages, cs.scan_store_app_caches,
        cs.scan_discord_cache, cs.scan_spotify_cache, cs.scan_zoom_cache,
        cs.scan_slack_cache, cs.scan_discord_full_cache, cs.scan_teams_cache,
        cs.scan_telegram_cache, cs.scan_brave_cache, cs.scan_vivaldi_cache,
        cs.scan_opera_cache, cs.scan_edge_cache, cs.scan_firefox_cache, cs.scan_chrome_cache,
        cs.scan_game_caches, cs.scan_epic_launcher_cache, cs.scan_ea_app_cache,
        cs.scan_ubisoft_cache, cs.scan_battlenet_cache, cs.scan_gog_cache,
        cs.scan_rockstar_cache, cs.scan_minecraft_cache, cs.scan_rust_game_cache,
    ]),
    ("Windows Update", [
        cs.scan_wu_cache, cs.scan_delivery_optimization, cs.scan_update_cleanup,
        cs.scan_windows_old, cs.scan_installer_patch_cache,
    ]),
    ("Logs & Reports", [
        cs.scan_windows_logs, cs.scan_event_logs, cs.scan_wer_reports,
        cs.scan_memory_dumps, cs.scan_panther_logs, cs.scan_dmf_logs,
        cs.scan_onedrive_logs, cs.scan_defender_history, cs.scan_diag_logs,
        cs.scan_powershell_logs, cs.scan_sysprep_logs, cs.scan_msi_logs,
        cs.scan_wmi_logs, cs.scan_sfc_logs, cs.scan_group_policy_logs,
    ]),
    ("Large Items", [
        cs.scan_windows_old, cs.scan_recycle_bin, cs.scan_installer_patch_cache,
    ]),
    ("Dev Tools", [
        cs.scan_dev_tool_caches, cs.scan_vscode_cache, cs.scan_jetbrains_cache,
        cs.scan_npm_cache, cs.scan_pip_cache, cs.scan_nuget_cache,
        cs.scan_golang_cache, cs.scan_rust_cache, cs.scan_java_cache,
        cs.scan_unity_cache, cs.scan_unreal_cache,
    ]),
    ("Cloud Storage", [
        cs.scan_dropbox_cache, cs.scan_google_drive_cache, cs.scan_mega_cache,
        cs.scan_pcloud_cache, cs.scan_icloud_cache, cs.scan_onedrive_full_cache,
    ]),
    ("Media Production", [
        cs.scan_obs_cache, cs.scan_davinci_cache, cs.scan_premiere_cache,
        cs.scan_blender_cache, cs.scan_audacity_cache, cs.scan_handbrake_cache,
    ]),
]

_OV_COLS = ["Group", "Total Size", "Safe Size", "Items", "Status"]


class _OverviewTab(QWidget):
    """Summary of all cleanup categories — scans all in parallel on first activation."""
    freed_bytes = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: dict = {}    # group_name -> (total_size, safe_size, item_count)
        self._pending  = 0
        self._scanning = False
        self._scanned  = False
        self._scan_workers: list = []
        self._worker: Optional[Worker] = None
        self._thread_pool = QThreadPool.globalInstance()
        self._setup_ui()

    def _setup_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        tb = QHBoxLayout()
        self._scan_btn  = QPushButton("Scan All")
        self._clean_btn = QPushButton("Clean All Safe")
        self._status    = QLabel("")
        self._clean_btn.setEnabled(False)
        tb.addWidget(self._scan_btn)
        tb.addWidget(self._clean_btn)
        tb.addStretch()
        tb.addWidget(self._status)
        lay.addLayout(tb)

        self._prog = QProgressBar()
        self._prog.setFixedHeight(4)
        self._prog.setTextVisible(False)
        self._prog.hide()
        lay.addWidget(self._prog)

        # Table
        self._table = QTableWidget(0, len(_OV_COLS))
        self._table.setHorizontalHeaderLabels(_OV_COLS)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        lay.addWidget(self._table, 1)

        self._scan_btn.clicked.connect(self._do_scan_all)
        self._clean_btn.clicked.connect(self._do_clean_safe)

    def _build_table(self):
        self._table.setRowCount(0)
        for name, _ in _OV_GROUPS:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(name))
            self._table.setItem(row, 1, QTableWidgetItem("—"))
            self._table.setItem(row, 2, QTableWidgetItem("—"))
            self._table.setItem(row, 3, QTableWidgetItem("—"))
            status = QTableWidgetItem("Pending…")
            status.setForeground(QColor("#888888"))
            self._table.setItem(row, 4, status)

    def _update_row(self, group_name: str, total: int, safe: int, count: int):
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item is None:
                continue
            if item.text() == group_name:
                sz = QTableWidgetItem(cs.format_size(total))
                sz.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                sz.setForeground(QColor("#5cb85c" if total == 0 else "#cccccc"))
                self._table.setItem(row, 1, sz)

                sf = QTableWidgetItem(cs.format_size(safe))
                sf.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, 2, sf)

                ct = QTableWidgetItem(str(count))
                ct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, 3, ct)

                status_text = "✓ Clean" if total == 0 else f"{cs.format_size(total)} found"
                st = QTableWidgetItem(status_text)
                st.setForeground(QColor("#5cb85c" if total == 0 else "#cccccc"))
                self._table.setItem(row, 4, st)
                break

    def auto_scan(self):
        if not self._scanned:
            self._build_table()
            self._do_scan_all()

    def _do_scan_all(self):
        if self._scanning:
            return
        self._scanning = True
        self._scanned  = True
        self._results.clear()
        self._scan_btn.setEnabled(False)
        self._clean_btn.setEnabled(False)
        self._prog.setRange(0, 0)
        self._prog.show()
        self._status.setText("Scanning all categories…")

        # Reset status column
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 4)
            if item:
                item.setText("Scanning…")
                item.setForeground(QColor("#f0ad4e"))

        self._pending = len(_OV_GROUPS)

        for group_name, scanners in _OV_GROUPS:
            def _make_cb(gname=group_name, fns=scanners):
                def _run(_w):
                    total = safe = count = 0
                    if fns is None:
                        # Browser caches — use detect_browsers()
                        try:
                            browsers = bs.detect_browsers()
                            for b in browsers:
                                total += b.total_bytes
                                safe  += b.total_bytes   # browsers are always "safe"
                                count += sum(len(p.categories) for p in b.profiles)
                        except Exception as e:
                            logger.warning(f"Browser scan failed: {e}")
                    else:
                        for fn in fns:
                            try:
                                r = fn(min_age_days=0)
                                total += r.total_size
                                safe  += sum(i.size for i in r.items if i.safety == "safe")
                                count += len(r.items)
                            except Exception as e:
                                logger.warning(f"Scan {fn.__name__} failed: {e}")
                    return gname, total, safe, count

                def _res(data):
                    gn, tot, sf, cnt = data
                    self._results[gn] = (tot, sf, cnt)
                    self._pending -= 1
                    self._update_row(gn, tot, sf, cnt)
                    if self._pending == 0:
                        self._scan_done()

                def _err(_e):
                    self._pending -= 1
                    self._update_row(gname, 0, 0, 0)
                    if self._pending == 0:
                        self._scan_done()

                return _run, _res, _err

            run_fn, res_fn, err_fn = _make_cb()
            w = Worker(run_fn)
            w.signals.result.connect(res_fn)
            w.signals.error.connect(err_fn)
            self._scan_workers.append(w)
            self._thread_pool.start(w)

    def _scan_done(self):
        self._scanning = False
        self._scan_btn.setEnabled(True)
        self._prog.hide()
        total = sum(t for t, _, _ in self._results.values())
        safe  = sum(s for _, s, _ in self._results.values())
        self._status.setText(
            f"Total: {cs.format_size(total)} found — "
            f"{cs.format_size(safe)} in Safe categories"
        )
        self._clean_btn.setEnabled(safe > 0)

    def _do_clean_safe(self):
        """Clean all Safe-tagged items across all scanned categories (non-browser)."""
        all_items = []
        needs_wu = False
        total = 0

        for group_name, scanners in _OV_GROUPS:
            if scanners is None:
                continue  # skip browser (handled by its own tab)
            for fn in scanners:
                try:
                    r = fn(min_age_days=0)
                    for item in r.items:
                        if item.safety == "safe":
                            item.selected = True
                            all_items.append(item)
                            total += item.size
                    if fn == cs.scan_wu_cache:
                        needs_wu = True
                except Exception as e:
                    logger.warning(f"Clean scan {fn.__name__} failed: {e}")

        if not all_items:
            return
        if not self._confirm_large(total):
            return

        self._clean_btn.setEnabled(False)
        self._scan_btn.setEnabled(False)
        self._prog.setRange(0, 0)
        self._prog.show()
        self._status.setText("Cleaning Safe categories…")

        def _run(_w):
            return cs.delete_items(all_items, stop_wuauserv=needs_wu)

        def _done(result):
            deleted, errors = result
            self._prog.hide()
            self._scan_btn.setEnabled(True)
            self._status.setText(
                f"Cleaned {deleted} item(s)"
                + (f" — {errors} error(s)" if errors else "")
            )
            self.freed_bytes.emit(total)
            # Re-scan overview
            self._scanned = False
            self._build_table()
            self._do_scan_all()

        def _err(e: str):
            self._prog.hide()
            self._scan_btn.setEnabled(True)
            self._clean_btn.setEnabled(True)
            self._status.setText(f"Error: {e}")

        self._worker = Worker(_run)
        self._worker.signals.result.connect(_done)
        self._worker.signals.error.connect(_err)
        self._thread_pool.start(self._worker)

    def _confirm_large(self, nbytes: int) -> bool:
        from modules.cleanup.tabs._scan_tab import _confirm_large as _cf
        return _cf(self, nbytes)

    def _cancel_all(self) -> None:
        for w in self._scan_workers:
            w.cancel()
        self._scan_workers.clear()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
