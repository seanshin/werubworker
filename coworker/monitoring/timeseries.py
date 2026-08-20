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

from .batch_writer import BatchWriter

# metrics_raw INSERT — record()/record_batch()/배치 플러시가 공유
_RAW_INSERT = (
    "INSERT OR REPLACE INTO metrics_raw "
    "(server_id, ts, cpu, memory, disk, net_rx, net_tx, load_1m, custom) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

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

    def __init__(
        self,
        data_dir: Path,
        batch_writes: bool = False,
        flush_size: int = 50,
        flush_interval: float = 0.1,
    ):
        """시계열 저장소.

        batch_writes=True면 ``record()`` 단건 호출을 메모리 버퍼에 모아
        ``flush_size``건 또는 ``flush_interval``초마다 일괄 INSERT한다.
        조회/유지보수 메서드는 진입 시 자동으로 버퍼를 비우므로 같은
        인스턴스에서의 read-after-write 일관성은 유지된다. 다만 다른
        프로세스나 다른 인스턴스는 플러시 전 데이터를 볼 수 없으므로
        기본값은 False다.
        """
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._local = threading.local()  # thread-local connection pool
        self._init_db()
        self._writer: BatchWriter | None = (
            BatchWriter(self._write_rows, flush_size, flush_interval)
            if batch_writes
            else None
        )

    # ------------------------------------------------------------------
    # Connection & schema
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self._db.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self._db.exists()
        conn = sqlite3.connect(str(self._db), timeout=5)
        conn.row_factory = sqlite3.Row
        if is_new:
            # page_size는 첫 테이블 생성 전에만 반영된다. 시계열은 행이
            # 작고 순차적이라 8KB 페이지가 페이지당 행 수를 늘려준다.
            conn.execute("PRAGMA page_size=8192")
        conn.execute("PRAGMA journal_mode=WAL")
        # WAL에서 NORMAL은 커밋마다 fsync하지 않는다 (OS 크래시 시에만
        # 마지막 트랜잭션 유실 가능). 메트릭 쓰기 처리량에 가장 크게 기여.
        conn.execute("PRAGMA synchronous=NORMAL")
        if is_new:
            try:
                import os

                os.chmod(self._db, 0o600)
            except OSError:
                pass
        self._local.conn = conn
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
        """메트릭 한 건 저장. ts는 현재 epoch초 (1분 단위로 반올림).

        batch_writes 모드에서는 버퍼에 적재만 하고 즉시 반환한다.
        """
        ts = int(time.time()) // 60 * 60
        row = (
            server_id, ts, cpu, memory, disk,
            net_rx, net_tx, load_1m, json.dumps(custom or {}),
        )
        try:
            if self._writer is not None:
                self._writer.enqueue(row)
            else:
                self._write_rows([row])
            return {"ok": True, "server_id": server_id, "ts": ts}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def record_batch(self, points: list[dict]) -> dict:
        """다중 서버 메트릭 일괄 저장 (executemany 단일 트랜잭션)."""
        default_ts = int(time.time()) // 60 * 60
        rows: list[tuple] = []
        errors: list[str] = []
        for pt in points:
            try:
                rows.append(self._build_row(pt, default_ts))
            except Exception as exc:
                errors.append(f"{pt.get('server_id', '?')}: {exc}")
        try:
            self._write_rows(rows)
            return {"ok": True, "inserted": len(rows), "errors": errors}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    @staticmethod
    def _build_row(pt: dict, default_ts: int) -> tuple:
        """포인트 dict를 metrics_raw INSERT 파라미터 튜플로 변환."""
        return (
            pt["server_id"],
            pt.get("ts", default_ts),
            pt.get("cpu", 0.0),
            pt.get("memory", 0.0),
            pt.get("disk", 0.0),
            pt.get("net_rx", 0),
            pt.get("net_tx", 0),
            pt.get("load_1m", 0.0),
            json.dumps(pt.get("custom") or {}),
        )

    def _write_rows(self, rows: list[tuple]) -> None:
        """metrics_raw에 일괄 INSERT. 트랜잭션 1회로 커밋."""
        if not rows:
            return
        with self._lock, self._connect() as conn:
            conn.executemany(_RAW_INSERT, rows)

    def flush(self) -> int:
        """배치 버퍼를 즉시 비운다. 반환값은 기록된 건수."""
        return self._writer.flush() if self._writer is not None else 0

    def close(self) -> None:
        """버퍼를 플러시하고 현재 스레드의 커넥션을 닫는다."""
        if self._writer is not None:
            self._writer.close()
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

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
        self.flush()
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
        self.flush()
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
        self.flush()
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
        self.flush()
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
        self.flush()
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT DISTINCT server_id FROM metrics_raw ORDER BY server_id"
                ).fetchall()
            return [r["server_id"] for r in rows]
        except Exception:
            return []
