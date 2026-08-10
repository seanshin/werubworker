"""SQLite-backed memory store (the default adapter)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .base import MemoryItem, MemoryStore, Scope


class SQLiteMemoryStore(MemoryStore):
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_conn(self._get_conn())

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection (created on first access per thread)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    @staticmethod
    def _init_conn(conn: sqlite3.Connection) -> None:
        """Create schema and indexes (idempotent)."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                key TEXT,
                content TEXT NOT NULL,
                workspace TEXT,
                session_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories (scope)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_workspace ON memories (workspace)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_session ON memories (session_id)")
        conn.commit()

    def add(
        self,
        content: str,
        *,
        scope: Scope = Scope.WORKSPACE,
        key: Optional[str] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> MemoryItem:
        scope = Scope(scope)
        conn = self._get_conn()
        cursor = conn.execute(
            "INSERT INTO memories (scope, key, content, workspace, session_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (scope.value, key, content, workspace, session_id),
        )
        conn.commit()
        item = self.get(cursor.lastrowid)
        assert item is not None
        return item

    def get(self, item_id: int) -> Optional[MemoryItem]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def list(
        self,
        *,
        scope: Optional[Scope] = None,
        workspace: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> list[MemoryItem]:
        query = "SELECT * FROM memories WHERE 1 = 1"
        params: list[object] = []
        if scope is not None:
            query += " AND scope = ?"
            params.append(Scope(scope).value)
        if workspace is not None:
            query += " AND workspace = ?"
            params.append(workspace)
        if session_id is not None:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY id"
        conn = self._get_conn()
        rows = conn.execute(query, params).fetchall()
        return [_row_to_item(row) for row in rows]

    def update(self, item_id: int, content: str) -> Optional[MemoryItem]:
        conn = self._get_conn()
        conn.execute("UPDATE memories SET content = ? WHERE id = ?", (content, item_id))
        conn.commit()
        return self.get(item_id)

    def delete(self, item_id: int) -> bool:
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM memories WHERE id = ?", (item_id,))
        conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def _row_to_item(row: sqlite3.Row) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        scope=Scope(row["scope"]),
        content=row["content"],
        key=row["key"],
        workspace=row["workspace"],
        session_id=row["session_id"],
        created_at=row["created_at"],
    )
