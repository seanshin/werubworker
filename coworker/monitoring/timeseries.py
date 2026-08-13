"""TimeSeriesStore — SQLite-backed time-series storage for server metrics.

Stores raw metrics at 1-minute resolution and automatically downsamples to
5-minute, 1-hour, and 1-day aggregates. Each tier has its own retention policy.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

# Aggregated table columns shared by metrics_5m, metrics_1h, metrics_1d
_AGG_SCHEMA = """
    server_id TEXT NOT NULL,
    ts INTEGER NOT NULL,
    cpu_avg REAL, cpu_max REAL,
    mem_avg REAL, mem_max REAL,
    disk_avg REAL, disk_max REAL,
    net_rx_sum INTEGER, net_tx_sum INTEGER,
    load_avg REAL,
    sample_count INTEGER DEFAULT 0,
    PRIMARY KEY (server_id, ts)
"""


class TimeSeriesStore:
    """Multi-resolution time-series store backed by SQLite (WAL mode)."""

    RETENTION: dict[str, int] = {
        "metrics_raw": 7,
        "metrics_5m": 30,
        "metrics_1h": 90,
        "metrics_1d": 365,
    }

    DOWNSAMPLE_MAP: list[tuple[str, str, int]] = [
        ("metrics_raw", "metrics_5m", 300),
        ("metrics_5m", "metrics_1h", 3600),
        ("metrics_1h", "metrics_1d", 86400),
    ]

    def __init__(self, data_dir: Path):
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Connection & schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self._db.exists()
        conn = sqlite3.connect(str(self._db), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        if is_new:
            try:
                import os

                os.chmod(self._db, 0o600)
            except OSError:
                pass
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(f"""
                CREATE TABLE IF NOT EXISTS metrics_raw (
                    server_id TEXT NOT NULL,
                    ts INTEGER NOT NULL,
                    cpu REAL, memory REAL, disk REAL,
                    net_rx INTEGER, net_tx INTEGER,
                    load_1m REAL,
                    custom TEXT DEFAULT '{{}}',
                    PRIMARY KEY (server_id, ts)
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS metrics_5m (
                    {_AGG_SCHEMA}
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS metrics_1h (
                    {_AGG_SCHEMA}
                ) WITHOUT ROWID;

                CREATE TABLE IF NOT EXISTS metrics_1d (
                    {_AGG_SCHEMA}
                ) WITHOUT ROWID;

                CREATE INDEX IF NOT EXISTS idx_metrics_raw_ts ON metrics_raw(ts);
                CREATE INDEX IF NOT EXISTS idx_metrics_5m_ts ON metrics_5m(ts);
                CREATE INDEX IF NOT EXISTS idx_metrics_1h_ts ON metrics_1h(ts);
                CREATE INDEX IF NOT EXISTS idx_metrics_1d_ts ON metrics_1d(ts);
            """)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def record(
        self,
        server_id: str,
        cpu: float,
        memory: float,
        disk: float,
        net_rx: int = 0,
        net_tx: int = 0,
        load_1m: float = 0.0,
        custom: dict | None = None,
    ) -> dict:
        """메트릭 한 건 저장. ts는 현재 epoch초 (1분 단위로 반올림)."""
        ts = int(time.time()) // 60 * 60
        custom_json = json.dumps(custom or {})
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO metrics_raw "
                    "(server_id, ts, cpu, memory, disk, net_rx, net_tx, load_1m, custom) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (server_id, ts, cpu, memory, disk, net_rx, net_tx, load_1m, custom_json),
                )
            return {"ok": True, "server_id": server_id, "ts": ts}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def record_batch(self, points: list[dict]) -> dict:
        """다중 서버 메트릭 일괄 저장."""
        ts = int(time.time()) // 60 * 60
        inserted = 0
        errors: list[str] = []
        try:
            with self._lock, self._connect() as conn:
                for pt in points:
                    try:
                        conn.execute(
                            "INSERT OR REPLACE INTO metrics_raw "
                            "(server_id, ts, cpu, memory, disk, net_rx, net_tx, "
                            "load_1m, custom) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                pt["server_id"],
                                pt.get("ts", ts),
                                pt.get("cpu", 0.0),
                                pt.get("memory", 0.0),
                                pt.get("disk", 0.0),
                                pt.get("net_rx", 0),
                                pt.get("net_tx", 0),
                                pt.get("load_1m", 0.0),
                                json.dumps(pt.get("custom") or {}),
                            ),
                        )
                        inserted += 1
                    except Exception as exc:
                        errors.append(f"{pt.get('server_id', '?')}: {exc}")
            return {"ok": True, "inserted": inserted, "errors": errors}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def query(
        self,
        server_id: str,
        start: int,
        end: int,
        table: str = "metrics_raw",
    ) -> list[dict]:
        """시간 범위로 메트릭 조회. 적절한 테이블 자동 선택."""
        if table == "metrics_raw":
            table = self.auto_select_table(end - start)
        if table not in self.RETENTION:
            return []
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM {table} "  # noqa: S608
                    "WHERE server_id = ? AND ts >= ? AND ts <= ? ORDER BY ts ASC",
                    (server_id, start, end),
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def query_latest(self, server_id: str | None = None) -> list[dict]:
        """각 서버의 최신 메트릭 1건씩."""
        try:
            with self._connect() as conn:
                if server_id:
                    rows = conn.execute(
                        "SELECT * FROM metrics_raw "
                        "WHERE server_id = ? ORDER BY ts DESC LIMIT 1",
                        (server_id,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT m.* FROM metrics_raw m "
                        "INNER JOIN ("
                        "  SELECT server_id, MAX(ts) AS max_ts FROM metrics_raw "
                        "  GROUP BY server_id"
                        ") latest ON m.server_id = latest.server_id AND m.ts = latest.max_ts"
                    ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def auto_select_table(self, range_seconds: int) -> str:
        """조회 범위에 따라 최적 테이블 선택.

        <=2h: raw, <=7d: 5m, <=90d: 1h, else: 1d
        """
        if range_seconds <= 7200:
            return "metrics_raw"
        if range_seconds <= 7 * 86400:
            return "metrics_5m"
        if range_seconds <= 90 * 86400:
            return "metrics_1h"
        return "metrics_1d"

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def downsample(self) -> dict:
        """raw->5m, 5m->1h, 1h->1d 다운샘플링 실행.

        각 소스 테이블에서 아직 집계되지 않은 구간을 AVG/MAX/SUM으로 집계.
        """
        results: dict[str, int] = {}
        try:
            with self._lock, self._connect() as conn:
                for src, dst, interval in self.DOWNSAMPLE_MAP:
                    if src == "metrics_raw":
                        # raw -> aggregated
                        sql = f"""
                            INSERT OR IGNORE INTO {dst}
                            (server_id, ts, cpu_avg, cpu_max, mem_avg, mem_max,
                             disk_avg, disk_max, net_rx_sum, net_tx_sum,
                             load_avg, sample_count)
                            SELECT
                                server_id,
                                (ts / {interval}) * {interval} AS bucket,
                                AVG(cpu), MAX(cpu),
                                AVG(memory), MAX(memory),
                                AVG(disk), MAX(disk),
                                SUM(net_rx), SUM(net_tx),
                                AVG(load_1m),
                                COUNT(*)
                            FROM {src}
                            GROUP BY server_id, bucket
                            HAVING bucket NOT IN (
                                SELECT ts FROM {dst}
                                WHERE server_id = {src}.server_id
                            )
                        """
                    else:
                        # aggregated -> aggregated
                        sql = f"""
                            INSERT OR IGNORE INTO {dst}
                            (server_id, ts, cpu_avg, cpu_max, mem_avg, mem_max,
                             disk_avg, disk_max, net_rx_sum, net_tx_sum,
                             load_avg, sample_count)
                            SELECT
                                server_id,
                                (ts / {interval}) * {interval} AS bucket,
                                AVG(cpu_avg), MAX(cpu_max),
                                AVG(mem_avg), MAX(mem_max),
                                AVG(disk_avg), MAX(disk_max),
                                SUM(net_rx_sum), SUM(net_tx_sum),
                                AVG(load_avg),
                                SUM(sample_count)
                            FROM {src}
                            GROUP BY server_id, bucket
                            HAVING bucket NOT IN (
                                SELECT ts FROM {dst}
                                WHERE server_id = {src}.server_id
                            )
                        """
                    cursor = conn.execute(sql)
                    results[dst] = cursor.rowcount
            return {"ok": True, "downsampled": results}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def prune(self) -> dict:
        """RETENTION 정책에 따라 오래된 데이터 삭제."""
        now = int(time.time())
        deleted: dict[str, int] = {}
        try:
            with self._lock, self._connect() as conn:
                for table, days in self.RETENTION.items():
                    cutoff = now - days * 86400
                    cursor = conn.execute(
                        f"DELETE FROM {table} WHERE ts < ?",  # noqa: S608
                        (cutoff,),
                    )
                    deleted[table] = cursor.rowcount
            return {"ok": True, "deleted": deleted}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def server_list(self) -> list[str]:
        """메트릭이 존재하는 서버 ID 목록."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT server_id FROM metrics_raw ORDER BY server_id"
                ).fetchall()
            return [r["server_id"] for r in rows]
        except Exception:
            return []
