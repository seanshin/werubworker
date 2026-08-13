"""IncidentManager — structured incident tracking with timeline and postmortem.

Tracks incidents from creation through investigation to resolution,
maintaining a timeline of events and supporting AI-generated postmortems.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_VALID_SEVERITIES = {"P1", "P2", "P3", "P4"}
_VALID_STATUSES = {"investigating", "identified", "monitoring", "resolved"}
_ACTIVE_STATUSES = ("investigating", "identified", "monitoring")
_VALID_TIMELINE_TYPES = {"alert", "action", "note", "status_change", "escalation"}


@dataclass
class TimelineEntry:
    timestamp: float
    type: str  # "alert", "action", "note", "status_change", "escalation"
    author: str  # "system" 또는 사용자명
    content: str
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "type": self.type,
            "author": self.author,
            "content": self.content,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TimelineEntry:
        return cls(
            timestamp=float(d.get("timestamp", 0.0)),
            type=d.get("type", "note"),
            author=d.get("author", "system"),
            content=d.get("content", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class Incident:
    id: str  # "inc-{hex}"
    title: str
    severity: str  # "P1", "P2", "P3", "P4"
    status: str = "investigating"  # investigating, identified, monitoring, resolved
    created_at: float = 0.0
    resolved_at: float | None = None
    affected_services: list[str] = field(default_factory=list)
    related_alerts: list[str] = field(default_factory=list)
    assignee: str | None = None
    postmortem_page_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "affected_services": self.affected_services,
            "related_alerts": self.related_alerts,
            "assignee": self.assignee,
            "postmortem_page_id": self.postmortem_page_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Incident:
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            severity=d.get("severity", "P4"),
            status=d.get("status", "investigating"),
            created_at=float(d.get("created_at", 0.0)),
            resolved_at=d.get("resolved_at"),
            affected_services=d.get("affected_services", []),
            related_alerts=d.get("related_alerts", []),
            assignee=d.get("assignee"),
            postmortem_page_id=d.get("postmortem_page_id"),
        )


class IncidentManager:
    """구조적 인시던트 추적 및 타임라인 관리."""

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
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'P4',
                    status TEXT NOT NULL DEFAULT 'investigating',
                    created_at REAL NOT NULL,
                    resolved_at REAL,
                    affected_services TEXT NOT NULL DEFAULT '[]',
                    related_alerts TEXT NOT NULL DEFAULT '[]',
                    assignee TEXT,
                    postmortem_page_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_status
                    ON incidents(status);
                CREATE INDEX IF NOT EXISTS idx_incidents_severity
                    ON incidents(severity);

                CREATE TABLE IF NOT EXISTS incident_timeline (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    type TEXT NOT NULL DEFAULT 'note',
                    author TEXT NOT NULL DEFAULT 'system',
                    content TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (incident_id) REFERENCES incidents(id)
                );
                CREATE INDEX IF NOT EXISTS idx_timeline_incident
                    ON incident_timeline(incident_id);
            """)

    def create(
        self,
        title: str,
        severity: str,
        affected_services: list[str] | None = None,
        related_alerts: list[str] | None = None,
    ) -> dict:
        """인시던트 생성 + 초기 타임라인 엔트리."""
        if severity not in _VALID_SEVERITIES:
            return {"ok": False, "error": f"invalid severity: {severity}"}

        now = time.time()
        inc_id = f"inc-{os.urandom(5).hex()}"
        services = affected_services or []
        alerts = related_alerts or []

        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO incidents "
                "(id, title, severity, status, created_at, affected_services, "
                "related_alerts) VALUES (?, ?, ?, 'investigating', ?, ?, ?)",
                (
                    inc_id,
                    title,
                    severity,
                    now,
                    json.dumps(services),
                    json.dumps(alerts),
                ),
            )
            conn.execute(
                "INSERT INTO incident_timeline "
                "(incident_id, timestamp, type, author, content, metadata) "
                "VALUES (?, ?, 'status_change', 'system', ?, ?)",
                (
                    inc_id,
                    now,
                    f"인시던트 생성: {title} [{severity}]",
                    json.dumps({"status": "investigating"}),
                ),
            )

        log.info("incident created: %s — %s [%s]", inc_id, title, severity)
        return {"ok": True, "incident_id": inc_id, "created_at": now}

    def update_status(self, incident_id: str, status: str, note: str = "") -> dict:
        """상태 변경 + 타임라인 기록."""
        if status not in _VALID_STATUSES:
            return {"ok": False, "error": f"invalid status: {status}"}

        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, status FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "incident not found"}

            old_status = row["status"]
            if old_status == status:
                return {"ok": False, "error": f"already in status: {status}"}

            updates = {"status": status}
            if status == "resolved":
                conn.execute(
                    "UPDATE incidents SET status = ?, resolved_at = ? WHERE id = ?",
                    (status, now, incident_id),
                )
                updates["resolved_at"] = now
            else:
                conn.execute(
                    "UPDATE incidents SET status = ? WHERE id = ?",
                    (status, incident_id),
                )

            content = f"상태 변경: {old_status} → {status}"
            if note:
                content += f" — {note}"
            conn.execute(
                "INSERT INTO incident_timeline "
                "(incident_id, timestamp, type, author, content, metadata) "
                "VALUES (?, ?, 'status_change', 'system', ?, ?)",
                (incident_id, now, content, json.dumps(updates)),
            )

        return {"ok": True, "old_status": old_status, "new_status": status}

    def add_timeline(
        self,
        incident_id: str,
        type: str,
        content: str,
        author: str = "system",
        metadata: dict | None = None,
    ) -> dict:
        """타임라인 엔트리 추가."""
        if type not in _VALID_TIMELINE_TYPES:
            return {"ok": False, "error": f"invalid timeline type: {type}"}

        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "incident not found"}

            conn.execute(
                "INSERT INTO incident_timeline "
                "(incident_id, timestamp, type, author, content, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    incident_id,
                    now,
                    type,
                    author,
                    content,
                    json.dumps(metadata or {}),
                ),
            )
        return {"ok": True, "timestamp": now}

    def assign(self, incident_id: str, assignee: str) -> dict:
        """인시던트 담당자 지정."""
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "incident not found"}

            conn.execute(
                "UPDATE incidents SET assignee = ? WHERE id = ?",
                (assignee, incident_id),
            )
            conn.execute(
                "INSERT INTO incident_timeline "
                "(incident_id, timestamp, type, author, content, metadata) "
                "VALUES (?, ?, 'action', 'system', ?, ?)",
                (
                    incident_id,
                    now,
                    f"담당자 지정: {assignee}",
                    json.dumps({"assignee": assignee}),
                ),
            )
        return {"ok": True, "assignee": assignee}

    def resolve(self, incident_id: str, resolution: str = "") -> dict:
        """resolved 상태로 변경, resolved_at 기록, 타임라인 추가."""
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id, status FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "incident not found"}
            if row["status"] == "resolved":
                return {"ok": False, "error": "already resolved"}

            conn.execute(
                "UPDATE incidents SET status = 'resolved', resolved_at = ? WHERE id = ?",
                (now, incident_id),
            )
            content = "인시던트 해결"
            if resolution:
                content += f": {resolution}"
            conn.execute(
                "INSERT INTO incident_timeline "
                "(incident_id, timestamp, type, author, content, metadata) "
                "VALUES (?, ?, 'status_change', 'system', ?, ?)",
                (
                    incident_id,
                    now,
                    content,
                    json.dumps({"status": "resolved", "resolution": resolution}),
                ),
            )

        log.info("incident resolved: %s", incident_id)
        return {"ok": True, "resolved_at": now}

    def get(self, incident_id: str) -> dict | None:
        """인시던트 + 타임라인 전체 조회."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return None

            d = dict(row)
            try:
                d["affected_services"] = json.loads(d.get("affected_services", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["affected_services"] = []
            try:
                d["related_alerts"] = json.loads(d.get("related_alerts", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["related_alerts"] = []

            timeline_rows = conn.execute(
                "SELECT * FROM incident_timeline WHERE incident_id = ? "
                "ORDER BY timestamp ASC",
                (incident_id,),
            ).fetchall()
            timeline = []
            for t in timeline_rows:
                entry = dict(t)
                try:
                    entry["metadata"] = json.loads(entry.get("metadata", "{}"))
                except (json.JSONDecodeError, TypeError):
                    entry["metadata"] = {}
                timeline.append(entry)
            d["timeline"] = timeline

        return d

    def list_incidents(self, status: str = "", limit: int = 50) -> list[dict]:
        """인시던트 목록 (타임라인 제외)."""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM incidents WHERE status = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            try:
                d["affected_services"] = json.loads(d.get("affected_services", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["affected_services"] = []
            try:
                d["related_alerts"] = json.loads(d.get("related_alerts", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["related_alerts"] = []
            result.append(d)
        return result

    def active_incidents(self) -> list[dict]:
        """investigating + identified + monitoring 상태."""
        with self._connect() as conn:
            placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
            rows = conn.execute(
                f"SELECT * FROM incidents WHERE status IN ({placeholders}) "
                "ORDER BY created_at DESC",
                _ACTIVE_STATUSES,
            ).fetchall()

        result = []
        for row in rows:
            d = dict(row)
            try:
                d["affected_services"] = json.loads(d.get("affected_services", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["affected_services"] = []
            try:
                d["related_alerts"] = json.loads(d.get("related_alerts", "[]"))
            except (json.JSONDecodeError, TypeError):
                d["related_alerts"] = []
            result.append(d)
        return result

    def link_postmortem(self, incident_id: str, page_id: str) -> dict:
        """Wiki 사후분석 페이지 연결."""
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
            if not row:
                return {"ok": False, "error": "incident not found"}

            conn.execute(
                "UPDATE incidents SET postmortem_page_id = ? WHERE id = ?",
                (page_id, incident_id),
            )
            conn.execute(
                "INSERT INTO incident_timeline "
                "(incident_id, timestamp, type, author, content, metadata) "
                "VALUES (?, ?, 'note', 'system', ?, ?)",
                (
                    incident_id,
                    now,
                    f"사후분석 페이지 연결: {page_id}",
                    json.dumps({"postmortem_page_id": page_id}),
                ),
            )
        return {"ok": True, "postmortem_page_id": page_id}

    async def sync_to_gitea(self, incident_id: str, secrets=None) -> dict:
        """인시던트를 Gitea Issue로 동기화 (itms.weve.io.kr 등)."""
        from ..connectors.gitea import get_gitea_connector

        connector = get_gitea_connector(secrets) if secrets else None
        if not connector:
            return {"ok": False, "error": "Gitea not configured"}

        inc = self.get(incident_id)
        if not inc:
            return {"ok": False, "error": "incident not found"}

        title = f"[{inc['severity']}] {inc['title']}"
        timeline_md = "\n".join(
            f"- **{t.get('type', '')}** ({t.get('author', '')}): {t.get('content', '')}"
            for t in inc.get("timeline", [])
        )
        body = (
            f"## 인시던트 보고서\n\n"
            f"- **심각도**: {inc['severity']}\n"
            f"- **상태**: {inc['status']}\n"
            f"- **영향 서비스**: {', '.join(inc.get('affected_services', []))}\n\n"
            f"## 타임라인\n\n{timeline_md}\n"
        )
        labels = [f"incident:{inc['severity'].lower()}", "auto-created"]
        result = await connector.create_issue(title, body, labels)
        if isinstance(result, dict) and result.get("number"):
            self.add_timeline(
                incident_id, "note",
                f"Gitea Issue #{result['number']} 생성됨",
                author="system",
                metadata={"gitea_issue": result.get("number")},
            )
        return {"ok": True, "issue": result}
