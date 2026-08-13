"""OpsAuditStore — operational audit log for compliance and post-incident analysis.

Records every consequential action taken by agents or users: SSH commands,
Docker restarts, K8s scaling, DB queries, etc. The audit trail is immutable
(append-only) and retained for 1 year.
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

log = logging.getLogger(__name__)


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
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
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
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
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

    def record(self, entry: OpsAuditEntry) -> dict:
        """감사 로그 기록."""
        try:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT INTO ops_audit "
                    "(ts, user, action, target, command, result, session_id, "
                    "approval_id, metadata) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.timestamp or time.time(),
                        entry.user,
                        entry.action,
                        entry.target,
                        entry.command,
                        entry.result,
                        entry.session_id,
                        entry.approval_id,
                        json.dumps(entry.metadata or {}),
                    ),
                )
            return {"ok": True}
        except Exception as exc:
            log.exception("audit record failed: %s", exc)
            return {"ok": False, "error": str(exc)}

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

    def prune(self, retention_days: int = 365) -> dict:
        """보관 기간 초과 로그 삭제."""
        cutoff = time.time() - (retention_days * 86400)
        try:
            with self._lock, self._connect() as conn:
                cur = conn.execute("DELETE FROM ops_audit WHERE ts < ?", (cutoff,))
                deleted = cur.rowcount
            return {"ok": True, "deleted": deleted}
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
