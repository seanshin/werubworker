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

    def _connect(self) -> sqlite3.Connection:
        self._db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db), timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def list_pages(
        self, category: str = "", query: str = "", tags: list | None = None
    ) -> list[dict]:
        """List pages with filtering. Returns metadata only (no content)."""
        clauses: list[str] = []
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
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
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
            row = conn.execute(
                "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        creds = json.loads(d["credentials"])
        # Mask credential values — only expose keys and metadata
        for c in creds:
            if "value" in c:
                c["value"] = "••••••••"
        d["credentials"] = creds
        return d

    def categories(self) -> list[dict]:
        """Category summary with counts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) as count FROM wiki_pages "
                "GROUP BY category ORDER BY count DESC"
            ).fetchall()
        return [{"category": r["category"], "count": r["count"]} for r in rows]

    def recent(self, limit: int = 10) -> list[dict]:
        """Recently modified pages."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT page_id, name, category, linked_service, tags, version, "
                "created_at, updated_at, updated_by FROM wiki_pages "
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
    ) -> dict:
        now = time.time()
        creds_json = json.dumps(credentials or [])
        tags_json = json.dumps(tags or [])
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO wiki_pages "
                "(page_id, name, category, content, credentials, linked_service, "
                "tags, version, created_at, updated_at, updated_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (page_id, name, category, content, creds_json, linked_service,
                 tags_json, now, now, updated_by),
            )
            # Initial history entry
            conn.execute(
                "INSERT INTO wiki_history "
                "(page_id, version, content, credentials, name, category, tags, "
                "linked_service, change_note, updated_by, created_at) "
                "VALUES (?, 1, ?, ?, ?, ?, ?, ?, 'Initial version', ?, ?)",
                (page_id, content, creds_json, name, category, tags_json,
                 linked_service, updated_by, now),
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
    ) -> dict:
        """Update page and save history."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wiki_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"page '{page_id}' not found"}
            current = dict(row)
            new_version = current["version"] + 1
            now = time.time()

            # Merge: only update fields that were explicitly provided
            new_content = content if content is not None else current["content"]
            new_creds = json.dumps(credentials) if credentials is not None else current["credentials"]
            new_name = name if name is not None else current["name"]
            new_category = category if category is not None else current["category"]
            new_tags = json.dumps(tags) if tags is not None else current["tags"]
            new_linked = linked_service if linked_service is not None else current["linked_service"]

            conn.execute(
                "UPDATE wiki_pages SET content=?, credentials=?, name=?, category=?, "
                "tags=?, linked_service=?, version=?, updated_at=?, updated_by=? "
                "WHERE page_id=?",
                (new_content, new_creds, new_name, new_category, new_tags,
                 new_linked, new_version, now, updated_by, page_id),
            )
            conn.execute(
                "INSERT INTO wiki_history "
                "(page_id, version, content, credentials, name, category, tags, "
                "linked_service, change_note, updated_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (page_id, new_version, new_content, new_creds, new_name,
                 new_category, new_tags, new_linked, change_note, updated_by, now),
            )
        return {"ok": True, "page_id": page_id, "version": new_version}

    def delete_page(self, page_id: str) -> dict:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT page_id FROM wiki_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"page '{page_id}' not found"}
            conn.execute("DELETE FROM wiki_alerts WHERE page_id = ?", (page_id,))
            conn.execute("DELETE FROM wiki_history WHERE page_id = ?", (page_id,))
            conn.execute("DELETE FROM wiki_pages WHERE page_id = ?", (page_id,))
        return {"ok": True, "page_id": page_id}

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
            conn.execute(
                "UPDATE wiki_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
            )
        return {"ok": True, "alert_id": alert_id}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_meta(row: sqlite3.Row) -> dict:
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        return d
