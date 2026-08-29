# src/core/backup_service.py
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StepRecord:
    step_type: str   # registry | service | appx | command | script | file | scheduled_task
    target: str
    before_value: Any
    after_value: Any
    revert_command: Optional[str] = None
    value_name: str = ""        # registry only — the value name under `target` (the key path)
    reg_kind: Optional[int] = None  # registry only — winreg.REG_* type, needed to write before_value back
    rc: Optional[int] = None    # command/script only — the process exit code
    stdout: str = ""            # command/script only — netsh and dism put refusals HERE, not on stderr
    stderr: str = ""            # command/script only


@dataclass
class RestoreResult:
    success: bool
    partial: bool
    failed_steps: List[str]
    errors: List[str]
    #: The tweak ids this revert touched, and the subset whose steps did not
    #: come back. `failed_steps` names STEPS, which nothing above this layer
    #: can map to a control -- so a batch revert could not say what it had
    #: reverted, and therefore could not check any of it. Guessing which
    #: controls a restore point covered is not an option.
    reverted_ids: List[str] = field(default_factory=list)
    failed_ids: List[str] = field(default_factory=list)


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
                revert_command   TEXT,
                reverted_at      DATETIME,
                revert_error     TEXT
            );
        """)
        # Add revert_command column if upgrading from older schema
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(tweak_steps)")}
        if "revert_command" not in cols:
            self._conn.execute(
                "ALTER TABLE tweak_steps ADD COLUMN revert_command TEXT")
            logger.info("added revert_command column to tweak_steps")
        if "value_name" not in cols:
            self._conn.execute(
                "ALTER TABLE tweak_steps ADD COLUMN value_name TEXT")
            logger.info("added value_name column to tweak_steps")
        if "reg_kind" not in cols:
            self._conn.execute(
                "ALTER TABLE tweak_steps ADD COLUMN reg_kind INTEGER")
            logger.info("added reg_kind column to tweak_steps")
        for name in ("rc", "stdout", "stderr"):
            if name not in cols:
                self._conn.execute(f"ALTER TABLE tweak_steps ADD COLUMN {name} TEXT")
                logger.info("added %s column to tweak_steps", name)
        self._conn.commit()

    def create_restore_point(self, label: str, module: str) -> str:
        rp_id = uuid.uuid4().hex
        now = datetime.now().isoformat()
        ts = now[:19].replace(":", "-").replace("T", "_")
        safe_label = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', label)
        safe_label = re.sub(r'\s+', '_', safe_label).strip()[:40]
        safe_label = safe_label.rstrip(' ._')
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

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """bytes (REG_BINARY before/after values) aren't JSON-serializable — hex-encode them."""
        return value.hex() if isinstance(value, (bytes, bytearray)) else value

    def record_steps(self, tweak_id: str, steps: List[StepRecord],
                     restore_point_id: str) -> None:
        now = datetime.now().isoformat()
        for step in steps:
            self._conn.execute(
                """INSERT INTO tweak_steps
                   (id, tweak_id, restore_point_id, applied_at,
                    step_type, target, before_value, after_value, revert_command,
                    value_name, reg_kind, rc, stdout, stderr)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (uuid.uuid4().hex, tweak_id, restore_point_id, now,
                 step.step_type, step.target,
                 json.dumps(self._json_safe(step.before_value)),
                 json.dumps(self._json_safe(step.after_value)),
                 getattr(step, 'revert_command', None),
                 getattr(step, 'value_name', ""),
                 getattr(step, 'reg_kind', None),
                 getattr(step, 'rc', None),
                 getattr(step, 'stdout', ""),
                 getattr(step, 'stderr', "")),
            )
        self._conn.commit()

    def backup_registry_key(self, key_path: str, restore_point_id: str) -> None:
        folder = self._get_restore_point_folder(restore_point_id)
        if folder is None:
            return
        safe = key_path.replace("\\", "_").replace("/", "_")[:80]
        out = os.path.join(folder, "registry", f"{safe}.reg")
        result = subprocess.run(
            ["reg", "export", key_path, out, "/y"],
            capture_output=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            logger.warning("reg export failed (rc=%d) for %s", result.returncode, key_path)

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
            try:
                with open(path, encoding="utf-8") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("backup_appx_package: could not read %s (%s), starting fresh", path, e)
                existing = []
        existing.append(package_full_name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f)

    def _revert_steps(self, step_ids: List[str]) -> RestoreResult:
        failed: List[str] = []
        errors: List[str] = []
        touched: List[str] = []
        failed_ids: List[str] = []
        for step_id in step_ids:
            tweak_id = self._tweak_id_of(step_id)
            if tweak_id is not None and tweak_id not in touched:
                touched.append(tweak_id)
            ok = self.revert_step(step_id)
            if not ok:
                failed.append(step_id)
                if tweak_id is not None and tweak_id not in failed_ids:
                    failed_ids.append(tweak_id)
                err_row = self._conn.execute(
                    "SELECT revert_error FROM tweak_steps WHERE id=?", (step_id,)
                ).fetchone()
                errors.append(err_row["revert_error"] or "Unknown error")
        success = len(failed) == 0
        partial = bool(failed) and len(failed) < len(step_ids)
        return RestoreResult(success=success, partial=partial,
                             failed_steps=failed, errors=errors,
                             reverted_ids=touched, failed_ids=failed_ids)

    def _tweak_id_of(self, step_id: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT tweak_id FROM tweak_steps WHERE id=?", (step_id,)
        ).fetchone()
        return row["tweak_id"] if row else None

    def control_ids_in(self, restore_point_id: str) -> List[str]:
        """The still-applied tweak ids in a restore point, in the order they
        were recorded. Asked BEFORE a revert, so the caller can read what the
        machine says now and compare afterwards."""
        rows = self._conn.execute(
            "SELECT DISTINCT tweak_id FROM tweak_steps "
            "WHERE restore_point_id=? AND reverted_at IS NULL ORDER BY rowid",
            (restore_point_id,),
        ).fetchall()
        return [row["tweak_id"] for row in rows]

    def restore_point(self, restore_point_id: str) -> RestoreResult:
        rows = self._conn.execute(
            "SELECT id FROM tweak_steps WHERE restore_point_id=? AND reverted_at IS NULL",
            (restore_point_id,),
        ).fetchall()
        result = self._revert_steps([row["id"] for row in rows])
        status = "restored" if result.success else "partial"
        self._conn.execute(
            "UPDATE restore_points SET status=? WHERE id=?",
            (status, restore_point_id),
        )
        self._conn.commit()
        return result

    def revert_tweak(self, tweak_id: str) -> RestoreResult:
        """Revert just the most recent still-applied steps for ONE tweak, regardless
        of whether it was applied alone or as part of a bigger 'Apply Selected'
        session. Powers the per-row Disable button in the Tweaks tab — distinct
        from restore_point(), which undoes an entire session at once.

        Only the latest apply is targeted: if the same tweak was applied, reverted,
        then re-applied, this reverts the re-apply, not the whole history.
        """
        latest = self._conn.execute(
            "SELECT restore_point_id FROM tweak_steps "
            "WHERE tweak_id=? AND reverted_at IS NULL ORDER BY rowid DESC LIMIT 1",
            (tweak_id,),
        ).fetchone()
        if latest is None:
            return RestoreResult(success=False, partial=False, failed_steps=[],
                                 errors=["No applied (unreverted) steps found for this tweak."])
        rows = self._conn.execute(
            "SELECT id FROM tweak_steps WHERE tweak_id=? AND restore_point_id=? "
            "AND reverted_at IS NULL",
            (tweak_id, latest["restore_point_id"]),
        ).fetchall()
        return self._revert_steps([row["id"] for row in rows])

    def revert_step(self, step_id: str) -> bool:
        row = self._conn.execute(
            "SELECT step_type, target, before_value, revert_command, restore_point_id, "
            "value_name, reg_kind FROM tweak_steps WHERE id=?",
            (step_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            step_type = row["step_type"]
            target = row["target"]
            before = (json.loads(row["before_value"])
                      if row["before_value"] else None)
            revert_cmd = row["revert_command"]
            if step_type == "registry":
                # Direct per-value revert from the recorded before_value — NOT a whole-key
                # .reg re-import. A .reg re-import is unreliable here: it's missing entirely
                # for keys that didn't exist before the tweak created them (reg export fails
                # silently on a nonexistent key), and gets overwritten every time the same key
                # is touched by a later step, so a key hit by two tweaks in one session would
                # only unwind the *last* touch. The before_value captured at apply time doesn't
                # have either problem.
                import winreg
                value_name = row["value_name"] or ""
                reg_kind = row["reg_kind"]
                hive_name, _, sub = target.partition("\\")
                hive = {
                    "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER,
                    "HKCR": winreg.HKEY_CLASSES_ROOT, "HKU": winreg.HKEY_USERS,
                    "HKCC": winreg.HKEY_CURRENT_CONFIG,
                }.get(hive_name.upper(), winreg.HKEY_LOCAL_MACHINE)
                if before is None:
                    # No prior value recorded — the tweak created it from nothing, so
                    # reverting means removing it, not writing some other value.
                    try:
                        with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE) as k:
                            winreg.DeleteValue(k, value_name)
                    except FileNotFoundError:
                        pass  # already absent — fine
                else:
                    kind = reg_kind if reg_kind is not None else winreg.REG_DWORD
                    if kind == winreg.REG_BINARY and isinstance(before, str):
                        before = bytes.fromhex(before)
                    with winreg.CreateKeyEx(hive, sub, access=winreg.KEY_SET_VALUE) as k:
                        winreg.SetValueEx(k, value_name, 0, kind, before)
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
            elif step_type == "script" and revert_cmd:
                subprocess.run(
                    revert_cmd, shell=True, check=False, capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
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
            -- rowid breaks the tie, and the tie is common: `created_at` is a
            -- datetime.now() string, and a batch apply creates several points
            -- inside one clock tick. Without it SQLite falls back to scanning
            -- the PRIMARY KEY index -- which is a random uuid4 -- so "newest
            -- first" came out in random order and someone reverting the most
            -- recent point could revert a different one.
            ORDER BY rp.created_at DESC, rp.rowid DESC
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
