# src/core/backup_service.py
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StepRecord:
    step_type: str   # registry | service | appx | command | file
    target: str
    before_value: Any
    after_value: Any


@dataclass
class RestoreResult:
    success: bool
    partial: bool
    failed_steps: List[str]
    errors: List[str]


@dataclass
class RestorePointInfo:
    id: str
    label: str
    created_at: str
    module: str
    status: str
    step_count: int


class BackupService:
    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._backup_dir = os.path.join(data_dir, "backups")
        os.makedirs(self._backup_dir, exist_ok=True)
        self._db_path = os.path.join(data_dir, "tweaks.db")
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS restore_points (
                id          TEXT PRIMARY KEY,
                label       TEXT NOT NULL,
                created_at  DATETIME NOT NULL,
                module      TEXT NOT NULL,
                status      TEXT DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS tweak_steps (
                id               TEXT PRIMARY KEY,
                tweak_id         TEXT NOT NULL,
                restore_point_id TEXT NOT NULL REFERENCES restore_points(id),
                applied_at       DATETIME NOT NULL,
                step_type        TEXT NOT NULL,
                target           TEXT NOT NULL,
                before_value     TEXT,
                after_value      TEXT,
                reverted_at      DATETIME,
                revert_error     TEXT
            );
        """)
        self._conn.commit()

    def create_restore_point(self, label: str, module: str) -> str:
        rp_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        ts = now[:19].replace(":", "-").replace("T", "_")
        safe_label = label.replace(" ", "_")[:20]
        folder = os.path.join(self._backup_dir, f"{ts}_{safe_label}")
        os.makedirs(folder, exist_ok=True)
        for sub in ("registry", "services", "appx", "files"):
            os.makedirs(os.path.join(folder, sub), exist_ok=True)
        manifest = {"id": rp_id, "label": label, "created_at": now,
                    "module": module, "folder": folder}
        with open(os.path.join(folder, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        self._conn.execute(
            "INSERT INTO restore_points (id, label, created_at, module) VALUES (?,?,?,?)",
            (rp_id, label, now, module),
        )
        self._conn.commit()
        return rp_id

    def record_steps(self, tweak_id: str, steps: List[StepRecord],
                     restore_point_id: str) -> None:
        now = datetime.now().isoformat()
        for step in steps:
            self._conn.execute(
                """INSERT INTO tweak_steps
                   (id, tweak_id, restore_point_id, applied_at,
                    step_type, target, before_value, after_value)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, tweak_id, restore_point_id, now,
                 step.step_type, step.target,
                 json.dumps(step.before_value), json.dumps(step.after_value)),
            )
        self._conn.commit()

    def backup_registry_key(self, key_path: str, restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        safe = key_path.replace("\\", "_").replace("/", "_")[:80]
        out = os.path.join(folder, "registry", f"{safe}.reg")
        subprocess.run(
            ["reg", "export", key_path, out, "/y"],
            capture_output=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def backup_service_state(self, service_name: str, restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        try:
            import win32service
            hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
            hs = win32service.OpenService(
                hscm, service_name,
                win32service.SERVICE_QUERY_CONFIG | win32service.SERVICE_QUERY_STATUS)
            config = win32service.QueryServiceConfig(hs)
            status = win32service.QueryServiceStatus(hs)
            state = {"name": service_name, "start_type": config[1], "state": status[1]}
            with open(os.path.join(folder, "services", f"{service_name}.json"),
                      "w", encoding="utf-8") as f:
                json.dump(state, f)
            win32service.CloseServiceHandle(hs)
            win32service.CloseServiceHandle(hscm)
        except Exception as e:
            logger.warning("backup_service_state failed for %s: %s", service_name, e)

    def backup_appx_package(self, package_full_name: str,
                            restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        path = os.path.join(folder, "appx", "removed_apps.json")
        existing: list = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                existing = json.load(f)
        existing.append(package_full_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f)

    def restore_point(self, restore_point_id: str) -> RestoreResult:
        rows = self._conn.execute(
            "SELECT id FROM tweak_steps WHERE restore_point_id=? AND reverted_at IS NULL",
            (restore_point_id,),
        ).fetchall()
        failed: List[str] = []
        errors: List[str] = []
        for row in rows:
            ok = self.revert_step(row["id"])
            if not ok:
                failed.append(row["id"])
                err_row = self._conn.execute(
                    "SELECT revert_error FROM tweak_steps WHERE id=?", (row["id"],)
                ).fetchone()
                errors.append(err_row["revert_error"] or "Unknown error")
        success = len(failed) == 0
        partial = bool(failed) and len(failed) < len(rows)
        status = "restored" if success else "partial"
        self._conn.execute(
            "UPDATE restore_points SET status=? WHERE id=?",
            (status, restore_point_id),
        )
        self._conn.commit()
        return RestoreResult(success=success, partial=partial,
                             failed_steps=failed, errors=errors)

    def revert_step(self, step_id: str) -> bool:
        row = self._conn.execute(
            "SELECT step_type, target, before_value FROM tweak_steps WHERE id=?",
            (step_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            step_type = row["step_type"]
            target = row["target"]
            before = (json.loads(row["before_value"])
                      if row["before_value"] else None)
            if step_type == "registry":
                subprocess.run(
                    ["reg", "import", target],
                    check=True, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif step_type == "service":
                import win32service
                hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
                hs = win32service.OpenService(hscm, target, win32service.SERVICE_CHANGE_CONFIG)
                win32service.ChangeServiceConfig(
                    hs, win32service.SERVICE_NO_CHANGE,
                    before, win32service.SERVICE_NO_CHANGE,
                    None, None, False, None, None, None, None)
                win32service.CloseServiceHandle(hs)
                win32service.CloseServiceHandle(hscm)
            elif step_type == "appx":
                subprocess.run(
                    ["winget", "install", target, "--silent",
                     "--accept-package-agreements"],
                    check=False, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            elif step_type == "file":
                src = before["src"]
                dest = before["dest"]
                shutil.copy2(src, dest)
            elif step_type == "command":
                logger.warning("command steps are not revertible: %s", target)
                # not a failure — mark as reverted
            now = datetime.now().isoformat()
            self._conn.execute(
                "UPDATE tweak_steps SET reverted_at=? WHERE id=?", (now, step_id))
            self._conn.commit()
            return True
        except Exception as e:
            self._conn.execute(
                "UPDATE tweak_steps SET revert_error=? WHERE id=?",
                (str(e), step_id))
            self._conn.commit()
            return False

    def list_restore_points(self) -> List[RestorePointInfo]:
        rows = self._conn.execute("""
            SELECT rp.id, rp.label, rp.created_at, rp.module, rp.status,
                   COUNT(ts.id) AS step_count
            FROM restore_points rp
            LEFT JOIN tweak_steps ts ON ts.restore_point_id = rp.id
            GROUP BY rp.id
            ORDER BY rp.created_at DESC
        """).fetchall()
        return [
            RestorePointInfo(id=r["id"], label=r["label"],
                             created_at=r["created_at"], module=r["module"],
                             status=r["status"], step_count=r["step_count"])
            for r in rows
        ]

    def _get_restore_point_folder(self, restore_point_id: str) -> Optional[str]:
        if not os.path.isdir(self._backup_dir):
            return None
        for entry in os.scandir(self._backup_dir):
            if not entry.is_dir():
                continue
            manifest = os.path.join(entry.path, "manifest.json")
            if os.path.exists(manifest):
                with open(manifest, encoding="utf-8") as f:
                    m = json.load(f)
                if m.get("id") == restore_point_id:
                    return entry.path
        return None

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()
