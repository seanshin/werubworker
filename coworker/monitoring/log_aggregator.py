"""LogAggregator — multi-server log collection and pattern analysis via SSH."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SEVERITY_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(CRITICAL|FATAL)\b", re.IGNORECASE), "critical"),
    (re.compile(r"\bERROR\b", re.IGNORECASE), "error"),
    (re.compile(r"\bWARN(?:ING)?\b", re.IGNORECASE), "warning"),
    (re.compile(r"\bDEBUG\b", re.IGNORECASE), "debug"),
]


@dataclass
class LogSource:
    id: str
    server_id: str
    type: str  # "file", "journalctl", "docker", "k8s"
    path: str  # 로그 경로 또는 서비스명/컨테이너명
    patterns: list[str] = field(default_factory=list)  # 관심 패턴 (정규식)
    severity_filter: str = "all"  # "error", "warning", "all"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "type": self.type,
            "path": self.path,
            "patterns": self.patterns,
            "severity_filter": self.severity_filter,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LogSource:
        return cls(
            id=d["id"],
            server_id=d.get("server_id", ""),
            type=d.get("type", "file"),
            path=d.get("path", ""),
            patterns=d.get("patterns", []),
            severity_filter=d.get("severity_filter", "all"),
        )


@dataclass
class LogEntry:
    source_id: str
    server_id: str
    timestamp: float
    line: str
    severity: str = "info"  # "debug", "info", "warning", "error", "critical"
    matched_pattern: str = ""

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "server_id": self.server_id,
            "timestamp": self.timestamp,
            "line": self.line,
            "severity": self.severity,
            "matched_pattern": self.matched_pattern,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LogEntry:
        return cls(
            source_id=d.get("source_id", ""),
            server_id=d.get("server_id", ""),
            timestamp=float(d.get("timestamp", 0.0)),
            line=d.get("line", ""),
            severity=d.get("severity", "info"),
            matched_pattern=d.get("matched_pattern", ""),
        )


class LogAggregator:
    """다중 서버 로그 수집 및 패턴 분석."""

    def __init__(self, data_dir: Path, secrets: Any = None):
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._secrets = secrets  # SSH 접속 정보 등
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
                CREATE TABLE IF NOT EXISTS log_sources (
                    id TEXT PRIMARY KEY,
                    server_id TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT 'file',
                    path TEXT NOT NULL,
                    patterns TEXT NOT NULL DEFAULT '[]',
                    severity_filter TEXT NOT NULL DEFAULT 'all'
                );
                CREATE INDEX IF NOT EXISTS idx_log_sources_server
                    ON log_sources(server_id);

                CREATE TABLE IF NOT EXISTS log_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    server_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    line TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info',
                    matched_pattern TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_log_entries_server
                    ON log_entries(server_id);
                CREATE INDEX IF NOT EXISTS idx_log_entries_ts
                    ON log_entries(timestamp);
                CREATE INDEX IF NOT EXISTS idx_log_entries_severity
                    ON log_entries(severity);
            """)

    # -- Source 관리 --

    def add_source(self, source: LogSource) -> dict:
        """로그 소스 등록."""
        if not source.id:
            source.id = f"logsrc-{os.urandom(5).hex()}"
        valid_types = {"file", "journalctl", "docker", "k8s"}
        if source.type not in valid_types:
            return {"ok": False, "error": f"invalid type: {source.type}"}

        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO log_sources "
                "(id, server_id, type, path, patterns, severity_filter) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    source.id,
                    source.server_id,
                    source.type,
                    source.path,
                    json.dumps(source.patterns),
                    source.severity_filter,
                ),
            )
        return {"ok": True, "source_id": source.id}

    def remove_source(self, source_id: str) -> dict:
        """로그 소스 제거."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM log_sources WHERE id = ?", (source_id,))
        return {"ok": True}

    def list_sources(self) -> list[dict]:
        """등록된 로그 소스 목록."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM log_sources").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["patterns"] = json.loads(d.get("patterns", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["patterns"] = []
            result.append(d)
        return result

    # -- 원격 로그 조회 --

    def _build_tail_cmd(self, source_type: str, path: str, lines: int) -> str:
        """소스 타입별 tail 명령어 생성."""
        cmds = {
            "file": f"tail -n {lines} {path}",
            "journalctl": f"journalctl -u {path} -n {lines} --no-pager",
            "docker": f"docker logs --tail {lines} {path}",
            "k8s": f"kubectl logs --tail={lines} {path}",
        }
        return cmds.get(source_type, f"tail -n {lines} {path}")

    def _build_search_cmd(
        self, source_type: str, path: str, pattern: str, hours: int
    ) -> str:
        """소스 타입별 검색 명령어 생성."""
        cmds = {
            "file": f"grep -n '{pattern}' {path} | tail -500",
            "journalctl": (
                f"journalctl -u {path} --since '{hours} hours ago' "
                f"--no-pager | grep '{pattern}' | tail -500"
            ),
            "docker": (
                f"docker logs --since {hours}h {path} 2>&1 "
                f"| grep '{pattern}' | tail -500"
            ),
            "k8s": (
                f"kubectl logs --since={hours}h {path} "
                f"| grep '{pattern}' | tail -500"
            ),
        }
        return cmds.get(source_type, f"grep -n '{pattern}' {path} | tail -500")

    async def _ssh_exec(self, server_id: str, command: str) -> tuple[str, str]:
        """SSH로 원격 명령 실행. (server_id → 호스트 정보 조회)"""
        # secrets에서 SSH 정보 조회
        host = server_id
        ssh_key = ""
        user = "root"
        port = 22

        if self._secrets:
            get = getattr(self._secrets, "get", None)
            if get:
                info = get(f"server:{server_id}")
                if isinstance(info, dict):
                    host = info.get("host", server_id)
                    user = info.get("user", "root")
                    port = info.get("port", 22)
                    ssh_key = info.get("ssh_key", "")

        ssh_args = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-p", str(port),
        ]
        if ssh_key:
            ssh_args.extend(["-i", ssh_key])
        ssh_args.append(f"{user}@{host}")
        ssh_args.append(command)

        try:
            proc = await asyncio.create_subprocess_exec(
                *ssh_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            return stdout.decode(errors="replace"), stderr.decode(errors="replace")
        except asyncio.TimeoutError:
            return "", "SSH command timed out"
        except Exception as e:
            return "", str(e)

    async def tail(self, server_id: str, source_id: str, lines: int = 100) -> dict:
        """SSH로 원격 로그 tail. type별 명령어 분기."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM log_sources WHERE id = ? AND server_id = ?",
                (source_id, server_id),
            ).fetchone()
        if not row:
            return {"ok": False, "error": "source not found"}

        source = dict(row)
        cmd = self._build_tail_cmd(source["type"], source["path"], lines)
        stdout, stderr = await self._ssh_exec(server_id, cmd)

        if stderr and not stdout:
            return {"ok": False, "error": stderr.strip()}

        output_lines = stdout.strip().splitlines() if stdout.strip() else []

        # 패턴/심각도 분석 및 저장
        try:
            patterns = json.loads(source.get("patterns", "[]"))
        except (json.JSONDecodeError, TypeError):
            patterns = []

        entries: list[LogEntry] = []
        now = time.time()
        for raw_line in output_lines:
            severity = self.classify_severity(raw_line)
            matched = self.match_patterns(raw_line, patterns)
            entries.append(
                LogEntry(
                    source_id=source_id,
                    server_id=server_id,
                    timestamp=now,
                    line=raw_line,
                    severity=severity,
                    matched_pattern=matched,
                )
            )

        if entries:
            self._record_entries(entries)

        return {
            "ok": True,
            "server_id": server_id,
            "source_id": source_id,
            "lines": [e.to_dict() for e in entries],
            "count": len(entries),
        }

    async def search(
        self,
        pattern: str,
        server_ids: list[str] | None = None,
        hours: int = 1,
        source_id: str = "",
    ) -> dict:
        """다중 서버 로그 검색 (grep). 최근 N시간."""
        with self._connect() as conn:
            if source_id:
                rows = conn.execute(
                    "SELECT * FROM log_sources WHERE id = ?", (source_id,)
                ).fetchall()
            elif server_ids:
                placeholders = ",".join("?" for _ in server_ids)
                rows = conn.execute(
                    f"SELECT * FROM log_sources WHERE server_id IN ({placeholders})",
                    server_ids,
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM log_sources").fetchall()

        if not rows:
            return {"ok": False, "error": "no matching sources found"}

        sources = []
        for r in rows:
            d = dict(r)
            try:
                d["patterns"] = json.loads(d.get("patterns", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["patterns"] = []
            sources.append(d)

        # 각 소스에 대해 비동기 검색 실행
        async def _search_one(src: dict) -> dict:
            cmd = self._build_search_cmd(src["type"], src["path"], pattern, hours)
            stdout, stderr = await self._ssh_exec(src["server_id"], cmd)
            matched_lines = stdout.strip().splitlines() if stdout.strip() else []
            return {
                "server_id": src["server_id"],
                "source_id": src["id"],
                "matches": matched_lines,
                "count": len(matched_lines),
                "error": stderr.strip() if stderr and not matched_lines else "",
            }

        tasks = [_search_one(s) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        search_results = []
        total = 0
        for r in results:
            if isinstance(r, Exception):
                search_results.append({"error": str(r)})
            else:
                search_results.append(r)
                total += r.get("count", 0)

        return {
            "ok": True,
            "pattern": pattern,
            "hours": hours,
            "results": search_results,
            "total_matches": total,
        }

    # -- 분류/매칭 --

    def classify_severity(self, line: str) -> str:
        """로그 라인의 심각도 자동 분류.

        CRITICAL/FATAL -> critical, ERROR -> error, WARN -> warning,
        DEBUG -> debug, 나머지 -> info
        """
        for pat, severity in _SEVERITY_PATTERNS:
            if pat.search(line):
                return severity
        return "info"

    def match_patterns(self, line: str, patterns: list[str]) -> str:
        """정규식 패턴 매칭. 매칭된 패턴 반환 (첫 매칭)."""
        for p in patterns:
            try:
                if re.search(p, line):
                    return p
            except re.error:
                continue
        return ""

    # -- 저장/조회 --

    def _record_entries(self, entries: list[LogEntry]) -> None:
        """SQLite에 로그 엔트리 배치 저장."""
        if not entries:
            return
        rows = [
            (e.source_id, e.server_id, e.timestamp, e.line, e.severity, e.matched_pattern)
            for e in entries
        ]
        with self._lock, self._connect() as conn:
            conn.executemany(
                "INSERT INTO log_entries "
                "(source_id, server_id, timestamp, line, severity, matched_pattern) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )

    def recent_entries(
        self,
        server_id: str = "",
        severity: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """최근 로그 엔트리 조회 (필터 적용)."""
        conditions: list[str] = []
        params: list[Any] = []

        if server_id:
            conditions.append("server_id = ?")
            params.append(server_id)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM log_entries {where} ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()

        return [dict(r) for r in rows]

    def prune(self, retention_days: int = 7) -> dict:
        """보관 기간 초과 로그 엔트리 삭제."""
        cutoff = time.time() - retention_days * 86400
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM log_entries WHERE timestamp < ?", (cutoff,)
            )
        return {"ok": True, "pruned": cursor.rowcount}
