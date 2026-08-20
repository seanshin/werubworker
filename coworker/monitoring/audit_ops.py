"""OpsAuditStore — operational audit log for compliance and post-incident analysis.

Records every consequential action taken by agents or users: SSH commands,
Docker restarts, K8s scaling, DB queries, etc. The audit trail is immutable
(append-only) and retained for 1 year.

Security features:
- Command-level sensitive data masking (passwords, tokens, keys)
- SHA-256 hash chain for tamper detection
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..security.hash_chain import GENESIS_HASH, HashChain
from ..security.sensitive_filter import sanitize_command

log = logging.getLogger(__name__)

# Fields included in hash chain computation
_HASH_FIELDS = ("ts", "user", "action", "target", "command")

_INSERT_SQL = (
    "INSERT INTO ops_audit "
    "(ts, user, action, target, command, result, session_id, "
    "approval_id, metadata, prev_hash, hash) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


@dataclass
class OpsAuditEntry:
    timestamp: float
    user: str  # 실행한 사용자/에이전트 ("agent:ops", "user:admin")
    action: str  # "ssh_execute", "docker_restart", "k8s_scale", "db_query", "remediation"
    target: str  # 대상 서버/서비스/DB ("ssh:web-01", "docker:nginx", "db:production")
    command: str  # 실행된 명령
    result: str  # "success", "failed", "denied", "approval_required"
    session_id: str = ""
    approval_id: str = ""
    metadata: dict | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "user": self.user,
            "action": self.action,
            "target": self.target,
            "command": self.command,
            "result": self.result,
            "session_id": self.session_id,
            "approval_id": self.approval_id,
            "metadata": self.metadata,
        }


class OpsAuditStore:
    """운영 감사 로그 저장소."""

    def __init__(self, data_dir: Path):
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._local = threading.local()  # thread-local connection pool
        self._init_db()
        self._last_hash = self._load_last_hash()
        self._anchor = self._load_anchor()

    def _connect(self) -> sqlite3.Connection:
        """Get or create a thread-local SQLite connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn
        self._db.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self._db.exists()
        conn = sqlite3.connect(str(self._db), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        if is_new:
            try:
                os.chmod(self._db, 0o600)
            except OSError:
                pass
        self._local.conn = conn
        return conn

    def _load_last_hash(self) -> str:
        """Load the most recent hash once at init."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT hash FROM ops_audit ORDER BY rowid DESC LIMIT 1"
                ).fetchone()
            return row["hash"] if row and row["hash"] else GENESIS_HASH
        except Exception:
            return GENESIS_HASH

    def _load_anchor(self) -> str:
        """정리(prune)로 잘려나간 체인의 시작 해시. 없으면 GENESIS."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM ops_audit_meta WHERE key = 'chain_anchor'"
                ).fetchone()
            return row["value"] if row and row["value"] else GENESIS_HASH
        except Exception:
            return GENESIS_HASH

    def _save_anchor(self, conn: sqlite3.Connection, value: str) -> None:
        conn.execute(
            "INSERT OR REPLACE INTO ops_audit_meta (key, value) VALUES "
            "('chain_anchor', ?)",
            (value,),
        )
        self._anchor = value

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS ops_audit_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ops_audit (
                    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    user TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    command TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL DEFAULT '',
                    session_id TEXT NOT NULL DEFAULT '',
                    approval_id TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_ops_audit_ts ON ops_audit(ts);
                CREATE INDEX IF NOT EXISTS idx_ops_audit_action ON ops_audit(action);
                CREATE INDEX IF NOT EXISTS idx_ops_audit_target ON ops_audit(target);
            """)
            self._migrate_hash_columns(conn)

    def _migrate_hash_columns(self, conn: sqlite3.Connection) -> None:
        """Add prev_hash/hash columns if they don't exist yet."""
        cursor = conn.execute("PRAGMA table_info(ops_audit)")
        columns = {row[1] for row in cursor.fetchall()}
        if "prev_hash" not in columns:
            conn.execute(
                "ALTER TABLE ops_audit ADD COLUMN prev_hash TEXT DEFAULT ''"
            )
        if "hash" not in columns:
            conn.execute(
                "ALTER TABLE ops_audit ADD COLUMN hash TEXT DEFAULT ''"
            )

    @staticmethod
    def _build_row(entry: OpsAuditEntry, prev_hash: str) -> tuple[tuple, str]:
        """항목을 INSERT 파라미터 튜플과 체인 해시로 변환."""
        filtered_command = sanitize_command(entry.command)
        ts = entry.timestamp or time.time()

        current_hash = HashChain.compute_hash(
            prev_hash, ts, entry.user, entry.action,
            entry.target, filtered_command,
        )

        row = (
            ts,
            entry.user,
            entry.action,
            entry.target,
            filtered_command,
            entry.result,
            entry.session_id,
            entry.approval_id,
            json.dumps(entry.metadata or {}),
            prev_hash,
            current_hash,
        )
        return row, current_hash

    def record(self, entry: OpsAuditEntry) -> dict:
        """감사 로그 기록 (민감정보 필터 + 해시체인)."""
        try:
            with self._lock, self._connect() as conn:
                row, current_hash = self._build_row(entry, self._last_hash)
                conn.execute(_INSERT_SQL, row)
            self._last_hash = current_hash
            return {"ok": True}
        except Exception as exc:
            log.exception("audit record failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def record_many(self, entries: list[OpsAuditEntry]) -> dict:
        """여러 항목을 한 트랜잭션에 일괄 기록.

        해시체인은 메모리에서 연쇄 계산한 뒤 executemany로 한 번에
        INSERT한다. 체인 순서는 리스트 순서를 따른다.
        """
        if not entries:
            return {"ok": True, "inserted": 0}
        try:
            with self._lock, self._connect() as conn:
                prev_hash = self._last_hash
                rows: list[tuple] = []
                for entry in entries:
                    row, prev_hash = self._build_row(entry, prev_hash)
                    rows.append(row)
                conn.executemany(_INSERT_SQL, rows)
            self._last_hash = prev_hash
            return {"ok": True, "inserted": len(rows)}
        except Exception as exc:
            log.exception("audit record_many failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def verify_chain(self) -> tuple[bool, int | None]:
        """운영 감사 로그 해시체인 무결성 검증 (스트리밍, O(1) 메모리).

        보관정책으로 오래된 기록이 삭제된 경우 남아 있는 첫 기록은 GENESIS가
        아니라 삭제 시점에 저장한 앵커에 연결된다.
        """
        conn = self._connect()
        cursor = conn.execute(
            "SELECT * FROM ops_audit ORDER BY rowid ASC"
        )
        rows = (dict(r) for r in cursor)
        return HashChain.verify_chain_streaming(
            rows, field_keys=list(_HASH_FIELDS), start_hash=self._anchor,
        )

    def chain_anchor(self) -> str:
        """현재 체인 검증의 시작 해시 (정리 이력이 없으면 GENESIS)."""
        return self._anchor

    def chain_head(self) -> str:
        """현재 체인의 마지막 해시값 반환 (메모리 캐시)."""
        return self._last_hash

    def query(
        self,
        server: str = "",
        action: str = "",
        user: str = "",
        since: float = 0,
        until: float = 0,
        limit: int = 200,
    ) -> list[dict]:
        """필터 기반 감사 로그 조회. 조건은 AND로 결합."""
        clauses: list[str] = []
        params: list[Any] = []

        if server:
            clauses.append("target LIKE ?")
            params.append(f"%{server}%")
        if action:
            clauses.append("action = ?")
            params.append(action)
        if user:
            clauses.append("user = ?")
            params.append(user)
        if since > 0:
            clauses.append("ts >= ?")
            params.append(since)
        if until > 0:
            clauses.append("ts <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM ops_audit {where} ORDER BY ts DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def recent(self, limit: int = 50) -> list[dict]:
        """최근 감사 로그."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ops_audit ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def count_by_action(self, since: float = 0) -> list[dict]:
        """액션별 집계 (GROUP BY action)."""
        if since > 0:
            sql = (
                "SELECT action, COUNT(*) as cnt FROM ops_audit "
                "WHERE ts >= ? GROUP BY action ORDER BY cnt DESC"
            )
            params: tuple = (since,)
        else:
            sql = (
                "SELECT action, COUNT(*) as cnt FROM ops_audit "
                "GROUP BY action ORDER BY cnt DESC"
            )
            params = ()

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [{"action": r["action"], "count": r["cnt"]} for r in rows]

    def export_csv(self, since: float = 0) -> str:
        """CSV 형식 내보내기."""
        if since > 0:
            sql = "SELECT * FROM ops_audit WHERE ts >= ? ORDER BY ts ASC"
            params: tuple = (since,)
        else:
            sql = "SELECT * FROM ops_audit ORDER BY ts ASC"
            params = ()

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "timestamp", "user", "action", "target", "command",
            "result", "session_id", "approval_id", "metadata",
        ])
        for r in rows:
            writer.writerow([
                r["ts"], r["user"], r["action"], r["target"], r["command"],
                r["result"], r["session_id"], r["approval_id"], r["metadata"],
            ])
        return buf.getvalue()

    def stats_by_period(self, days: int = 7) -> dict:
        """기간별 감사 통계."""
        cutoff = time.time() - days * 86400
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT date(ts, 'unixepoch', 'localtime') as day, COUNT(*) as cnt, "
                "SUM(CASE WHEN result IN ('denied', 'failed') THEN 1 ELSE 0 END) as risky "
                "FROM ops_audit WHERE ts >= ? GROUP BY day ORDER BY day",
                (cutoff,),
            ).fetchall()
        return {
            "ok": True,
            "period_days": days,
            "daily": [{"date": r["day"], "total": r["cnt"], "risky": r["risky"]} for r in rows],
        }

    def stats_by_user(self, days: int = 7) -> dict:
        """사용자별 활동 통계."""
        cutoff = time.time() - days * 86400
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT user, COUNT(*) as cnt, "
                "SUM(CASE WHEN result IN ('denied', 'failed') THEN 1 ELSE 0 END) as risky "
                "FROM ops_audit WHERE ts >= ? GROUP BY user ORDER BY cnt DESC",
                (cutoff,),
            ).fetchall()
        return {
            "ok": True,
            "users": [{"user": r["user"], "total": r["cnt"], "risky": r["risky"]} for r in rows],
        }

    def flagged_actions(self, limit: int = 50) -> list[dict]:
        """위험 행동으로 플래깅된 항목."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, user, action, target, result, command FROM ops_audit "
                "WHERE result IN ('denied', 'failed') "
                "OR action LIKE '%delete%' OR action LIKE '%drop%' "
                "OR action LIKE '%kill%' OR action LIKE '%force%' "
                "ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "ts": r["ts"],
                "user": r["user"],
                "action": r["action"],
                "target": r["target"],
                "result": r["result"],
                "detail": r["command"] or "",
            }
            for r in rows
        ]

    def export_csv_by_days(self, days: int = 30) -> str:
        """CSV 형식으로 감사 로그 내보내기 (일수 기준)."""
        cutoff = time.time() - days * 86400
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ts, user, action, target, result, command FROM ops_audit "
                "WHERE ts >= ? ORDER BY ts DESC",
                (cutoff,),
            ).fetchall()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["시간", "사용자", "작업", "대상", "결과", "상세"])
        for r in rows:
            ts_str = (
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"]))
                if r["ts"]
                else ""
            )
            writer.writerow([ts_str, r["user"], r["action"], r["target"], r["result"], r["command"] or ""])
        return buf.getvalue()

    def prune(self, retention_days: int = 365) -> dict:
        """보관 기간 초과 로그 삭제.

        삭제하면 남은 첫 기록이 연결하던 앞 기록이 사라지므로, 그 기록의
        prev_hash를 새 체인 앵커로 저장한다. 저장하지 않으면 이후
        ``verify_chain()``이 0번 인덱스에서 영구히 실패한다.
        """
        cutoff = time.time() - (retention_days * 86400)
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute("DELETE FROM ops_audit WHERE ts < ?", (cutoff,))
                deleted = cur.rowcount
                if deleted:
                    row = conn.execute(
                        "SELECT prev_hash FROM ops_audit ORDER BY rowid ASC LIMIT 1"
                    ).fetchone()
                    # 전부 삭제됐다면 다음 기록은 현재 head에 연결된다
                    anchor = row["prev_hash"] if row else self._last_hash
                    self._save_anchor(conn, anchor or GENESIS_HASH)
            return {"ok": True, "deleted": deleted, "chain_anchor": self._anchor}
        except Exception as exc:
            log.exception("prune failed: %s", exc)
            return {"ok": False, "error": str(exc)}

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["timestamp"] = d.pop("ts", 0)
        meta = d.get("metadata", "{}")
        try:
            d["metadata"] = json.loads(meta) if isinstance(meta, str) else meta
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        return d
