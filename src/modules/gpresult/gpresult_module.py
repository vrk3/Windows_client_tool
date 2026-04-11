import os
import uuid
import tempfile
import threading
import subprocess
import datetime
from typing import Optional
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTreeWidget,
    QTreeWidgetItem, QTabWidget, QSplitter, QProgressBar, QFileDialog,
    QPlainTextEdit,
)
from PyQt6.QtCore import Qt

from core.base_module import BaseModule
from core.module_groups import ModuleGroup
from core.worker import Worker

# GPResult XML namespace
_NS = {
    "rsop": "http://www.microsoft.com/GroupPolicy/Rsop",
    "settings": "http://www.microsoft.com/GroupPolicy/Settings",
    "b": "http://www.microsoft.com/GroupPolicy/Base",
    "core": "http://www.microsoft.com/GroupPolicy/Core",
}


def _find_text(elem, *paths):
    """Try multiple XPath paths, return first match text or ''."""
    for path in paths:
        try:
            e = elem.find(path, _NS)
            if e is not None and e.text:
                return e.text.strip()
        except Exception:
            pass
    return ""


def _parse_gpresult_xml(xml_path: str) -> dict:
    """
    Parse gpresult /x XML. Returns dict with:
    {
        "computer_gpos": [{"name": ..., "guid": ...}],
        "user_gpos": [{"name": ..., "guid": ...}],
        "computer_settings": [("setting_name", "value")],
        "user_settings": [("setting_name", "value")],
        "dc_name": str,
        "site": str,
        "last_time": str,
    }
    """
    result = {
        "computer_gpos": [], "user_gpos": [],
        "computer_settings": [], "user_settings": [],
        "dc_name": "", "site": "", "last_time": "",
    }
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # The XML structure from gpresult /x can vary. Try to find GPOs generically.
        # Walk all elements looking for GPO names
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag in ("GPO", "AppliedGPO", "FilteredGPO"):
                name_elem = elem.find(".//{*}Name")
                guid_elem = elem.find(".//{*}Identifier/{*}Identifier")
                if guid_elem is None:
                    guid_elem = elem.find(".//{*}GUID")
                name = (name_elem.text if name_elem is not None else "")
                guid = (guid_elem.text if guid_elem is not None else "")
                # Determine if computer or user section
                # Walk up (hard in ElementTree) — just add to both and deduplicate
                result["computer_gpos"].append({"name": name, "guid": guid})

        # Try to get DC and site
        for elem in root.iter():
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "DomainControllerName" and elem.text:
                result["dc_name"] = elem.text.strip()
            if tag == "Site" and elem.text:
                result["site"] = elem.text.strip()

        result["last_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Deduplicate GPOs
        seen = set()
        deduped = []
        for gpo in result["computer_gpos"]:
            key = gpo["name"]
            if key not in seen:
                seen.add(key)
                deduped.append(gpo)
        result["computer_gpos"] = deduped

    except ET.ParseError as e:
        result["error"] = str(e)
    except Exception as e:
        result["error"] = str(e)
    return result


class GPResultModule(BaseModule):
    name = "Group Policy"
    icon = "📋"
    description = "Group Policy result viewer"
    requires_admin = False
    group = ModuleGroup.MANAGE

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._worker: Optional[Worker] = None

    def on_activate(self) -> None:
        pass

    def on_deactivate(self) -> None:
        self.cancel_all_workers()

    def refresh_data(self) -> None:
        if hasattr(self, "_refresh_fn"):
            self._refresh_fn()

    def get_refresh_interval(self) -> Optional[int]:
        """Auto-refresh every 120 seconds (gpresult is expensive)."""
        return 120_000

    def on_start(self, app) -> None:
        self.app = app

    def on_stop(self) -> None:
        self.cancel_all_workers()

    def create_widget(self, parent=None) -> QWidget:
        w = QWidget(parent)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)

        # Toolbar
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("Refresh")
        export_btn = QPushButton("Export HTML")
        status_lbl = QLabel("Click Refresh to run gpresult.")
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(export_btn)
        toolbar.addStretch()
        toolbar.addWidget(status_lbl)
        layout.addLayout(toolbar)

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setFixedHeight(4)
        progress.hide()
        layout.addWidget(progress)

        # Info bar
        info_lbl = QLabel("")
        info_lbl.setStyleSheet("color: gray;")
        layout.addWidget(info_lbl)

        # GPO list
        gpo_tree = QTreeWidget()
        gpo_tree.setHeaderLabels(["Applied Group Policy Objects", "GUID"])
        gpo_tree.header().setStretchLastSection(True)
        layout.addWidget(gpo_tree, 1)

        def do_refresh():
            if not self._lock.acquire(blocking=False):
                status_lbl.setText("Already running — please wait.")
                return
            refresh_btn.setEnabled(False)
            status_lbl.setText("Running gpresult...")
            progress.show()
            gpo_tree.clear()

            # Worker passes itself as first arg; accept and ignore it
            def run_gpresult(worker):
                tmp = os.path.join(tempfile.gettempdir(),
                                   f"wt_gpresult_{uuid.uuid4().hex}.xml")
                try:
                    proc = subprocess.run(
                        ["gpresult", "/x", tmp, "/f"],
                        capture_output=True, text=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        timeout=60,
                    )
                    if not os.path.exists(tmp):
                        return {"error": f"gpresult failed: {proc.stderr.strip()}"}
                    return _parse_gpresult_xml(tmp)
                finally:
                    try:
                        if os.path.exists(tmp):
                            os.remove(tmp)
                    except OSError:
                        pass

            def on_result(data: dict):
                self._lock.release()
                refresh_btn.setEnabled(True)
                progress.hide()
                if "error" in data:
                    status_lbl.setText(f"Error: {data['error']}")
                    return
                gpo_tree.clear()
                gpos = data.get("computer_gpos", [])
                for gpo in gpos:
                    item = QTreeWidgetItem([gpo["name"], gpo.get("guid", "")])
                    gpo_tree.addTopLevelItem(item)
                dc = data.get("dc_name", "")
                site = data.get("site", "")
                last = data.get("last_time", "")
                info_parts = [f"Last: {last}"]
                if dc:
                    info_parts.append(f"DC: {dc}")
                if site:
                    info_parts.append(f"Site: {site}")
                info_lbl.setText(" | ".join(info_parts))
                status_lbl.setText(f"{len(gpos)} GPO(s) applied.")

            def on_error(err_str: str):
                self._lock.release()
                refresh_btn.setEnabled(True)
                progress.hide()
                status_lbl.setText(f"Error: {err_str}")

            self._worker = Worker(run_gpresult)
            self._worker.signals.result.connect(on_result)
            self._worker.signals.error.connect(on_error)
            self._workers.append(self._worker)
            self.thread_pool.start(self._worker)

        def do_export():
            path, _ = QFileDialog.getSaveFileName(w, "Export HTML", "gpresult.html", "HTML (*.html)")
            if not path:
                return
            try:
                subprocess.run(
                    ["gpresult", "/h", path, "/f"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=60,
                )
                if os.path.exists(path):
                    os.startfile(path)
                    status_lbl.setText("HTML report opened in browser.")
                else:
                    status_lbl.setText("Export failed.")
            except Exception as e:
                status_lbl.setText(f"Export error: {e}")

        refresh_btn.clicked.connect(do_refresh)
        export_btn.clicked.connect(do_export)
        self._refresh_fn = do_refresh
        return w
