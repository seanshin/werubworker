"""WikiStore — SQLite-backed wiki for service documentation and credential metadata.

Each page lives in a category (e.g. "infrastructure", "api", "database") and can carry
structured credential metadata (keys only — actual secret values live in the Vault).
Full version history is kept so edits are never lost.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# Default templates for each category
WIKI_TEMPLATES: dict[str, dict] = {
    "model": {
        "name": "Model Card Template",
        "content": "# {{model_name}}\n\n## Overview\n\n## Capabilities\n\n## Pricing\n\n## Limitations\n",
        "structured_data": {
            "provider": "", "model_id": "", "context_window": 0,
            "input_price_per_1m": 0, "output_price_per_1m": 0,
            "capabilities": [], "release_date": "",
        },
    },
    "prompt": {
        "name": "Prompt Template",
        "content": "# {{prompt_name}}\n\n## System Prompt\n\n## Variables\n\n## Examples\n",
        "structured_data": {"target_models": [], "variables": [], "use_case": ""},
    },
    "runbook": {
        "name": "Runbook Template",
        "content": "# {{runbook_name}}\n\n## Trigger\n\n## Steps\n\n1. \n2. \n3. \n\n## Resolution\n",
        "structured_data": {"trigger": "", "severity": "medium", "steps": []},
    },
    "service": {
        "name": "Service Documentation",
        "content": "# {{service_name}}\n\n## Connection Info\n\n## Credentials\n\n## Notes\n",
        "structured_data": {},
    },
    "database": {
        "name": "Database Configuration",
        "content": "# {{db_name}}\n\n## Connection\n- Host: \n- Port: \n- Database: \n- User: \n\n## Backup Schedule\n\n## Notes\n",
        "structured_data": {"type": "", "host": "", "port": 0, "database": "", "user": "", "backup_schedule": ""},
    },
    "server": {
        "name": "Server Configuration",
        "content": "# {{server_name}}\n\n## Connection\n- Host: \n- Port: 22\n- User: \n\n## Services Running\n\n## Monitoring\n\n## Notes\n",
        "structured_data": {"host": "", "port": 22, "user": "", "os": "", "services": []},
    },
    "cloud": {
        "name": "Cloud Provider Configuration",
        "content": "# {{provider_name}}\n\n## Account\n- Provider: \n- Region: \n- Account ID: \n\n## Services Used\n\n## Billing\n\n## Notes\n",
        "structured_data": {"provider": "", "region": "", "account_id": "", "services": []},
    },
    "api_doc": {
        "name": "API Documentation",
        "content": "# {{api_name}}\n\n## Base URL\n\n## Authentication\n\n## Endpoints\n\n### GET /example\n\n```\ncurl -H 'Authorization: Bearer TOKEN' https://api.example.com/v1/resource\n```\n\n## Rate Limits\n\n## Notes\n",
        "structured_data": {"base_url": "", "auth_type": "", "rate_limit": "", "version": ""},
    },
    "benchmark": {
        "name": "Benchmark Record",
        "content": "# {{benchmark_name}}\n\n## Dataset\n\n## Models Tested\n\n## Results\n\n| Model | Accuracy | Latency | Cost |\n|-------|----------|---------|------|\n|       |          |         |      |\n\n## Notes\n",
        "structured_data": {"dataset": "", "models": [], "metrics": {}},
    },
    "architecture": {
        "name": "Architecture Document",
        "content": "# {{system_name}}\n\n## Overview\n\n## Components\n\n## Data Flow\n\n```mermaid\ngraph LR\n  A[Client] --> B[API]\n  B --> C[Database]\n```\n\n## Dependencies\n\n## Notes\n",
        "structured_data": {"components": [], "dependencies": []},
    },
    "development": {
        "name": "Development Environment",
        "content": "# {{project_name}}\n\n## 기술 스택\n\n## 개발 환경 설정\n\n```bash\n# 의존성 설치\n\n# 개발 서버 실행\n\n# 테스트 실행\n```\n\n## CI/CD\n\n## 환경 변수\n\n| 변수명 | 설명 | 필수 |\n|--------|------|------|\n\n## 배포\n\n## 메모\n",
        "structured_data": {"repo_url": "", "language": "", "framework": "", "ci": ""},
    },
    "config": {
        "name": "Configuration File",
        "content": "# {{config_name}}\n\n## 서비스\n\n## 설정 내용\n\n```\n\n```\n\n## 변경 이력\n",
        "structured_data": {"config_type": "", "service": "", "server": ""},
    },
    "incident": {
        "name": "Incident Report",
        "content": "# 인시던트: {{incident_name}}\n\n## 요약\n\n## 심각도\n\n## 영향 범위\n\n## 타임라인\n\n| 시각 | 내용 |\n|------|------|\n\n## 근본 원인\n\n## 조치 내역\n\n## 재발 방지\n",
        "structured_data": {"severity": "", "status": "", "affected_services": [], "rca": ""},
    },
    "network": {
        "name": "Network Configuration",
        "content": "# 네트워크: {{network_name}}\n\n## 구성\n- CIDR: \n- Gateway: \n- DNS: \n\n## 방화벽 규칙\n\n| 포트 | 프로토콜 | 소스 | 설명 |\n|------|---------|------|------|\n\n## VPN\n\n## 메모\n",
        "structured_data": {"cidr": "", "gateway": "", "dns": [], "firewall_rules": []},
    },
    "backup": {
        "name": "Backup Configuration",
        "content": "# 백업: {{backup_name}}\n\n## 대상\n\n## 스케줄\n\n## 보관 정책\n- 보관 기간: \n- 최대 보관 수: \n\n## 복원 절차\n\n## 마지막 검증\n",
        "structured_data": {"schedule": "", "retention_days": 0, "target": "", "method": ""},
    },
}


class WikiStore:
    def __init__(self, data_dir: Path):
        self._db = data_dir / "wiki.db"
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS wiki_pages (
                    page_id       TEXT PRIMARY KEY,
                    name          TEXT NOT NULL,
                    category      TEXT NOT NULL DEFAULT '',
                    content       TEXT NOT NULL DEFAULT '',
                    credentials   TEXT NOT NULL DEFAULT '[]',
                    linked_service TEXT NOT NULL DEFAULT '',
                    tags          TEXT NOT NULL DEFAULT '[]',
                    version       INTEGER NOT NULL DEFAULT 1,
                    created_at    REAL NOT NULL,
                    updated_at    REAL NOT NULL,
                    updated_by    TEXT NOT NULL DEFAULT 'system'
                );
                CREATE TABLE IF NOT EXISTS wiki_history (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_id       TEXT NOT NULL,
                    version       INTEGER NOT NULL,
                    content       TEXT NOT NULL DEFAULT '',
                    credentials   TEXT NOT NULL DEFAULT '[]',
                    name          TEXT NOT NULL DEFAULT '',
                    category      TEXT NOT NULL DEFAULT '',
                    tags          TEXT NOT NULL DEFAULT '[]',
                    linked_service TEXT NOT NULL DEFAULT '',
                    change_note   TEXT NOT NULL DEFAULT '',
                    updated_by    TEXT NOT NULL DEFAULT 'system',
                    created_at    REAL NOT NULL,
                    FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id)
                );
                CREATE TABLE IF NOT EXISTS wiki_alerts (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_id       TEXT NOT NULL,
                    credential_key TEXT NOT NULL DEFAULT '',
                    alert_type    TEXT NOT NULL DEFAULT 'expiring',
                    alert_date    TEXT NOT NULL DEFAULT '',
                    acknowledged  INTEGER NOT NULL DEFAULT 0,
                    created_at    REAL NOT NULL,
                    FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id)
                );
                CREATE INDEX IF NOT EXISTS idx_wiki_pages_category ON wiki_pages(category);
                CREATE INDEX IF NOT EXISTS idx_wiki_history_page ON wiki_history(page_id);
                CREATE INDEX IF NOT EXISTS idx_wiki_alerts_page ON wiki_alerts(page_id);
            """)
            # v0.4.0 schema migration: add structured_data column
            try:
                conn.execute("SELECT structured_data FROM wiki_pages LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE wiki_pages ADD COLUMN structured_data TEXT NOT NULL DEFAULT '{}'")
                conn.commit()

            # v0.5.0: FTS5 full-text search index
            try:
                conn.execute("SELECT * FROM wiki_fts LIMIT 0")
            except sqlite3.OperationalError:
                conn.executescript("""
                    CREATE VIRTUAL TABLE wiki_fts USING fts5(
                        name, content, tags, category,
                        content='wiki_pages',
                        content_rowid='rowid',
                        tokenize='unicode61'
                    );
                    -- Populate from existing data
                    INSERT INTO wiki_fts(rowid, name, content, tags, category)
                        SELECT rowid, name, content, tags, category FROM wiki_pages;

                    -- Triggers to keep FTS in sync
                    CREATE TRIGGER wiki_fts_insert AFTER INSERT ON wiki_pages BEGIN
                        INSERT INTO wiki_fts(rowid, name, content, tags, category)
                            VALUES (new.rowid, new.name, new.content, new.tags, new.category);
                    END;
                    CREATE TRIGGER wiki_fts_delete AFTER DELETE ON wiki_pages BEGIN
                        INSERT INTO wiki_fts(wiki_fts, rowid, name, content, tags, category)
                            VALUES ('delete', old.rowid, old.name, old.content, old.tags, old.category);
                    END;
                    CREATE TRIGGER wiki_fts_update AFTER UPDATE ON wiki_pages BEGIN
                        INSERT INTO wiki_fts(wiki_fts, rowid, name, content, tags, category)
                            VALUES ('delete', old.rowid, old.name, old.content, old.tags, old.category);
                        INSERT INTO wiki_fts(rowid, name, content, tags, category)
                            VALUES (new.rowid, new.name, new.content, new.tags, new.category);
                    END;
                """)
            # v0.5.0: Prompt execution tracking
            try:
                conn.execute("SELECT * FROM wiki_prompt_runs LIMIT 0")
            except sqlite3.OperationalError:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS wiki_prompt_runs (
                        run_id TEXT PRIMARY KEY,
                        page_id TEXT NOT NULL,
                        prompt_version INTEGER NOT NULL DEFAULT 1,
                        model_id TEXT NOT NULL DEFAULT '',
                        input_tokens INTEGER NOT NULL DEFAULT 0,
                        output_tokens INTEGER NOT NULL DEFAULT 0,
                        latency_ms INTEGER NOT NULL DEFAULT 0,
                        success INTEGER NOT NULL DEFAULT 1,
                        variables TEXT NOT NULL DEFAULT '{}',
                        output_preview TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_prompt_runs_page ON wiki_prompt_runs(page_id);
                """)

            # v0.5.0: Benchmark results tracking
            try:
                conn.execute("SELECT * FROM wiki_benchmarks LIMIT 0")
            except sqlite3.OperationalError:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS wiki_benchmarks (
                        benchmark_id TEXT PRIMARY KEY,
                        page_id TEXT NOT NULL,
                        model_id TEXT NOT NULL,
                        metric_name TEXT NOT NULL,
                        metric_value REAL NOT NULL DEFAULT 0,
                        run_date TEXT NOT NULL DEFAULT '',
                        created_at REAL NOT NULL,
                        FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_benchmarks_page ON wiki_benchmarks(page_id);
                    CREATE INDEX IF NOT EXISTS idx_benchmarks_model ON wiki_benchmarks(model_id);
                """)

            # v0.5.0: Runbook execution tracking
            try:
                conn.execute("SELECT * FROM wiki_runbook_executions LIMIT 0")
            except sqlite3.OperationalError:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS wiki_runbook_executions (
                        execution_id TEXT PRIMARY KEY,
                        page_id TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'running',
                        steps_completed INTEGER NOT NULL DEFAULT 0,
                        steps_total INTEGER NOT NULL DEFAULT 0,
                        result_summary TEXT NOT NULL DEFAULT '',
                        executed_by TEXT NOT NULL DEFAULT 'system',
                        started_at REAL NOT NULL,
                        finished_at REAL,
                        FOREIGN KEY (page_id) REFERENCES wiki_pages(page_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_runbook_exec_page ON wiki_runbook_executions(page_id);
                """)

            # v0.5.1 schema migration: add deleted_at column for soft delete
            try:
                conn.execute("SELECT deleted_at FROM wiki_pages LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE wiki_pages ADD COLUMN deleted_at REAL DEFAULT NULL")
                conn.commit()

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

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def search_fts(self, query: str, limit: int = 50) -> list[dict]:
        """Full-text search across name, content, tags, category.

        Uses FTS5 first; if no results (e.g. CJK text that unicode61
        tokenizer cannot segment), falls back to LIKE search.
        """
        if not query or not query.strip():
            return []
        safe_query = query.replace('"', '""')
        with self._connect() as conn:
            # Try FTS5 first
            rows = conn.execute(
                'SELECT p.page_id, p.name, p.category, p.tags, p.updated_at, '
                'snippet(wiki_fts, 1, "<mark>", "</mark>", "...", 40) as snippet '
                'FROM wiki_fts f JOIN wiki_pages p ON f.rowid = p.rowid '
                'WHERE wiki_fts MATCH ? ORDER BY rank LIMIT ?',
                (f'"{safe_query}"', limit),
            ).fetchall()
            # Fallback to LIKE for CJK and short queries
            if not rows:
                like_pattern = f"%{query.strip()}%"
                rows = conn.execute(
                    "SELECT page_id, name, category, tags, updated_at, "
                    "'' as snippet "
                    "FROM wiki_pages "
                    "WHERE deleted_at IS NULL AND "
                    "(name LIKE ? OR content LIKE ? OR tags LIKE ? OR category LIKE ?) "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (like_pattern, like_pattern, like_pattern, like_pattern, limit),
                ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            results.append(d)
        return results

    def list_pages(
        self, category: str = "", query: str = "", tags: list | None = None
    ) -> list[dict]:
        """List pages with filtering. Returns metadata only (no content)."""
        clauses: list[str] = ["deleted_at IS NULL"]
        params: list[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if query:
            clauses.append("(name LIKE ? OR content LIKE ?)")
            params.extend([f"%{query}%", f"%{query}%"])
        if tags:
            for tag in tags:
                clauses.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
        where = " WHERE " + " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT page_id, name, category, linked_service, tags, version, "
                f"created_at, updated_at, updated_by FROM wiki_pages{where} "
                f"ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_meta(r) for r in rows]

    def get_page(self, page_id: str) -> dict | None:
        """Get full page with content and credentials metadata (values masked)."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM wiki_pages WHERE page_id = ? AND deleted_at IS NULL", (page_id,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        try:
            d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        try:
            creds = json.loads(d["credentials"]) if d.get("credentials") else []
        except (json.JSONDecodeError, TypeError):
            creds = []
        # Mask credential values — only expose keys and metadata
        for c in creds:
            if "value" in c:
                c["value"] = "••••••••"
        d["credentials"] = creds
        # Parse structured_data JSON
        try:
            d["structured_data"] = json.loads(d.get("structured_data") or "{}") if "structured_data" in d else {}
        except (json.JSONDecodeError, TypeError):
            d["structured_data"] = {}
        # Resolve [[Page Name]] wiki links in content
        if d.get("content"):
            d["content"] = self.resolve_wiki_links(d["content"])
        return d

    def categories(self) -> list[dict]:
        """Category summary with counts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) as count FROM wiki_pages "
                "WHERE deleted_at IS NULL "
                "GROUP BY category ORDER BY count DESC"
            ).fetchall()
        return [{"category": r["category"], "count": r["count"]} for r in rows]

    def recent(self, limit: int = 10) -> list[dict]:
        """Recently modified pages."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT page_id, name, category, linked_service, tags, version, "
                "created_at, updated_at, updated_by FROM wiki_pages "
                "WHERE deleted_at IS NULL "
                "ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_meta(r) for r in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def create_page(
        self,
        page_id: str,
        name: str,
        category: str,
        content: str,
        credentials: list | None = None,
        linked_service: str = "",
        tags: list | None = None,
        updated_by: str = "system",
        structured_data: dict | None = None,
    ) -> dict:
        now = time.time()
        creds_json = json.dumps(credentials or [])
        tags_json = json.dumps(tags or [])
        sd_json = json.dumps(structured_data or {})
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO wiki_pages "
                "(page_id, name, category, content, credentials, linked_service, "
                "tags, version, created_at, updated_at, updated_by, structured_data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)",
                (
                    page_id,
                    name,
                    category,
                    content,
                    creds_json,
                    linked_service,
                    tags_json,
                    now,
                    now,
                    updated_by,
                    sd_json,
                ),
            )
            # Initial history entry
            conn.execute(
                "INSERT INTO wiki_history "
                "(page_id, version, content, credentials, name, category, tags, "
                "linked_service, change_note, updated_by, created_at) "
                "VALUES (?, 1, ?, ?, ?, ?, ?, ?, 'Initial version', ?, ?)",
                (
                    page_id,
                    content,
                    creds_json,
                    name,
                    category,
                    tags_json,
                    linked_service,
                    updated_by,
                    now,
                ),
            )
        return {"ok": True, "page_id": page_id, "version": 1}

    def update_page(
        self,
        page_id: str,
        content: str | None = None,
        credentials: list | None = None,
        name: str | None = None,
        category: str | None = None,
        tags: list | None = None,
        linked_service: str | None = None,
        updated_by: str = "system",
        change_note: str = "",
        structured_data: dict | None = None,
    ) -> dict:
        """Update page and save history."""
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM wiki_pages WHERE page_id = ? AND deleted_at IS NULL", (page_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"page '{page_id}' not found"}
            current = dict(row)
            new_version = current["version"] + 1
            now = time.time()

            # Merge: only update fields that were explicitly provided
            new_content = content if content is not None else current["content"]
            new_creds = (
                json.dumps(credentials) if credentials is not None else current["credentials"]
            )
            new_name = name if name is not None else current["name"]
            new_category = category if category is not None else current["category"]
            new_tags = json.dumps(tags) if tags is not None else current["tags"]
            new_linked = linked_service if linked_service is not None else current["linked_service"]
            new_sd = (
                json.dumps(structured_data)
                if structured_data is not None
                else current.get("structured_data", "{}")
            )

            conn.execute(
                "UPDATE wiki_pages SET content=?, credentials=?, name=?, category=?, "
                "tags=?, linked_service=?, version=?, updated_at=?, updated_by=?, "
                "structured_data=? WHERE page_id=?",
                (
                    new_content,
                    new_creds,
                    new_name,
                    new_category,
                    new_tags,
                    new_linked,
                    new_version,
                    now,
                    updated_by,
                    new_sd,
                    page_id,
                ),
            )
            conn.execute(
                "INSERT INTO wiki_history "
                "(page_id, version, content, credentials, name, category, tags, "
                "linked_service, change_note, updated_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    page_id,
                    new_version,
                    new_content,
                    new_creds,
                    new_name,
                    new_category,
                    new_tags,
                    new_linked,
                    change_note,
                    updated_by,
                    now,
                ),
            )
        return {"ok": True, "page_id": page_id, "version": new_version}

    def delete_page(self, page_id: str) -> dict:
        """Soft-delete a page by setting deleted_at timestamp."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT page_id FROM wiki_pages WHERE page_id = ? AND deleted_at IS NULL",
                (page_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"page '{page_id}' not found"}
            conn.execute(
                "UPDATE wiki_pages SET deleted_at = ? WHERE page_id = ?",
                (time.time(), page_id),
            )
        return {"ok": True, "page_id": page_id}

    def restore_page(self, page_id: str) -> dict:
        """Restore a soft-deleted page."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT page_id FROM wiki_pages WHERE page_id = ? AND deleted_at IS NOT NULL",
                (page_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"deleted page '{page_id}' not found"}
            conn.execute(
                "UPDATE wiki_pages SET deleted_at = NULL WHERE page_id = ?",
                (page_id,),
            )
        return {"ok": True, "page_id": page_id}

    def purge_deleted(self, days: int = 30) -> dict:
        """Permanently remove pages soft-deleted more than *days* ago."""
        cutoff = time.time() - (days * 86400)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT page_id FROM wiki_pages WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (cutoff,),
            ).fetchall()
            page_ids = [r["page_id"] for r in rows]
            for pid in page_ids:
                conn.execute("DELETE FROM wiki_alerts WHERE page_id = ?", (pid,))
                conn.execute("DELETE FROM wiki_history WHERE page_id = ?", (pid,))
                conn.execute("DELETE FROM wiki_pages WHERE page_id = ?", (pid,))
        return {"ok": True, "purged": len(page_ids)}

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history(self, page_id: str) -> list[dict]:
        """Version history for a page."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, page_id, version, change_note, updated_by, created_at "
                "FROM wiki_history WHERE page_id = ? ORDER BY version DESC",
                (page_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_version(self, page_id: str, version: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wiki_history WHERE page_id = ? AND version = ?",
                (page_id, version),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        d["credentials"] = json.loads(d["credentials"])
        return d

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def list_alerts(self) -> list[dict]:
        """Expiring/expired credential alerts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT a.*, p.name as page_name FROM wiki_alerts a "
                "LEFT JOIN wiki_pages p ON a.page_id = p.page_id "
                "WHERE a.acknowledged = 0 ORDER BY a.alert_date ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def add_alert(
        self, page_id: str, credential_key: str, alert_type: str, alert_date: str
    ) -> dict:
        now = time.time()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO wiki_alerts "
                "(page_id, credential_key, alert_type, alert_date, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (page_id, credential_key, alert_type, alert_date, now),
            )
        return {"ok": True, "alert_id": cursor.lastrowid}

    def ack_alert(self, alert_id: int) -> dict:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE wiki_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
        return {"ok": True, "alert_id": alert_id}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Prompt runs
    # ------------------------------------------------------------------

    def record_prompt_run(self, page_id: str, run_id: str, model_id: str,
                          input_tokens: int, output_tokens: int, latency_ms: int,
                          success: bool, variables: dict, output_preview: str,
                          prompt_version: int = 1) -> dict:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO wiki_prompt_runs "
                "(run_id, page_id, prompt_version, model_id, input_tokens, output_tokens, "
                "latency_ms, success, variables, output_preview, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, page_id, prompt_version, model_id, input_tokens, output_tokens,
                 latency_ms, 1 if success else 0, json.dumps(variables), output_preview[:500],
                 time.time())
            )
        return {"ok": True, "run_id": run_id}

    def get_prompt_runs(self, page_id: str, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wiki_prompt_runs WHERE page_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (page_id, limit)
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["variables"] = json.loads(d.get("variables", "{}"))
            except (json.JSONDecodeError, TypeError):
                d["variables"] = {}
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------

    def record_benchmark(self, benchmark_id: str, page_id: str, model_id: str,
                         metric_name: str, metric_value: float, run_date: str = "") -> dict:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO wiki_benchmarks "
                "(benchmark_id, page_id, model_id, metric_name, metric_value, run_date, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (benchmark_id, page_id, model_id, metric_name, metric_value, run_date, time.time())
            )
        return {"ok": True}

    def get_benchmarks(self, page_id: str = "", model_id: str = "") -> list[dict]:
        clauses: list[str] = []
        params: list[Any] = []
        if page_id:
            clauses.append("page_id = ?"); params.append(page_id)
        if model_id:
            clauses.append("model_id = ?"); params.append(model_id)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM wiki_benchmarks{where} ORDER BY created_at DESC LIMIT 200",
                params
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Runbook executions
    # ------------------------------------------------------------------

    def record_runbook_execution(
        self, execution_id: str, page_id: str, steps_total: int,
        executed_by: str = "system",
    ) -> dict:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO wiki_runbook_executions "
                "(execution_id, page_id, status, steps_completed, steps_total, "
                "executed_by, started_at) VALUES (?, ?, 'running', 0, ?, ?, ?)",
                (execution_id, page_id, steps_total, executed_by, time.time()),
            )
        return {"ok": True, "execution_id": execution_id}

    def update_runbook_execution(
        self, execution_id: str, steps_completed: int,
        status: str = "running", result_summary: str = "",
    ) -> dict:
        finished = time.time() if status in ("completed", "failed") else None
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE wiki_runbook_executions SET steps_completed = ?, status = ?, "
                "result_summary = ?, finished_at = ? WHERE execution_id = ?",
                (steps_completed, status, result_summary, finished, execution_id),
            )
        return {"ok": True}

    def get_runbook_executions(self, page_id: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wiki_runbook_executions WHERE page_id = ? "
                "ORDER BY started_at DESC LIMIT ?",
                (page_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Export / Import
    # ------------------------------------------------------------------

    def export_all(self) -> list[dict]:
        """Export all pages for ZIP packaging."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM wiki_pages WHERE deleted_at IS NULL ORDER BY name"
            ).fetchall()
        pages = []
        for r in rows:
            d = dict(r)
            try:
                d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
            except (json.JSONDecodeError, TypeError):
                d["tags"] = []
            try:
                d["credentials"] = json.loads(d["credentials"]) if d.get("credentials") else []
            except (json.JSONDecodeError, TypeError):
                d["credentials"] = []
            try:
                d["structured_data"] = json.loads(d.get("structured_data") or "{}")
            except (json.JSONDecodeError, TypeError):
                d["structured_data"] = {}
            pages.append(d)
        return pages

    def import_pages(self, pages: list[dict], updated_by: str = "import") -> dict:
        """Import pages from exported data. Skips existing page_ids."""
        imported = 0
        skipped = 0
        for p in pages:
            existing = self.get_page(p.get("page_id", ""))
            if existing:
                skipped += 1
                continue
            self.create_page(
                page_id=p.get("page_id", ""),
                name=p.get("name", ""),
                category=p.get("category", ""),
                content=p.get("content", ""),
                credentials=p.get("credentials"),
                linked_service=p.get("linked_service", ""),
                tags=p.get("tags"),
                updated_by=updated_by,
                structured_data=p.get("structured_data"),
            )
            imported += 1
        return {"ok": True, "imported": imported, "skipped": skipped}

    # ------------------------------------------------------------------
    # Internal links
    # ------------------------------------------------------------------

    def resolve_wiki_links(self, content: str) -> str:
        """Replace [[Page Name]] with HTML links to wiki pages."""
        import re as _re

        def replacer(match: _re.Match) -> str:
            name = match.group(1)
            pages = self.list_pages(query=name)
            for p in pages:
                if p.get("name", "").lower() == name.lower():
                    pid = p.get("page_id", p.get("id", ""))
                    return f'<a href="#wiki/{pid}" class="wiki-link">{name}</a>'
            return f'<span class="wiki-link-broken">{name}</span>'

        return _re.sub(r'\[\[([^\]]+)\]\]', replacer, content)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_meta(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["tags"] = json.loads(d["tags"]) if d.get("tags") else []
        except (json.JSONDecodeError, TypeError):
            d["tags"] = []
        return d
