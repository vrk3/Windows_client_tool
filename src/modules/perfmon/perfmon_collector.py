import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


def collect_snapshot() -> Dict[str, float]:
    """Collect a single snapshot of performance counters."""
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("C:/")
    net = psutil.net_io_counters()
    return {
        "cpu_total": psutil.cpu_percent(interval=None),
        "memory_percent": mem.percent,
        "memory_used_mb": mem.used / (1024 * 1024),
        "memory_available_mb": mem.available / (1024 * 1024),
        "disk_percent": disk.percent,
        "disk_read_bytes": psutil.disk_io_counters().read_bytes if psutil.disk_io_counters() else 0,
        "disk_write_bytes": psutil.disk_io_counters().write_bytes if psutil.disk_io_counters() else 0,
        "net_sent_bytes": net.bytes_sent,
        "net_recv_bytes": net.bytes_recv,
    }


class PerfMonStore:
    """SQLite-backed storage for historical performance data."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS perfmon (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                counter TEXT NOT NULL,
                value REAL NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_perfmon_ts ON perfmon(timestamp)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_perfmon_counter ON perfmon(counter)
        """)
        self._conn.commit()

    def store_snapshot(self, snapshot: Dict[str, float]) -> None:
        """Store a performance snapshot."""
        if not self._conn:
            return
        ts = datetime.now().isoformat()
        rows = [(ts, counter, value) for counter, value in snapshot.items()]
        self._conn.executemany(
            "INSERT INTO perfmon (timestamp, counter, value) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def query(self, counter: str, hours_back: int = 1) -> List[tuple]:
        """Return (timestamp_str, value) tuples for a counter."""
        if not self._conn:
            return []
        cutoff = (datetime.now() - timedelta(hours=hours_back)).isoformat()
        cursor = self._conn.execute(
            "SELECT timestamp, value FROM perfmon WHERE counter = ? AND timestamp > ? ORDER BY timestamp",
            (counter, cutoff),
        )
        return cursor.fetchall()

    def cleanup_old(self, days: int = 7) -> None:
        """Delete records older than N days."""
        if not self._conn:
            return
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self._conn.execute("DELETE FROM perfmon WHERE timestamp < ?", (cutoff,))
        self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
