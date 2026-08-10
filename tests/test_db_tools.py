"""Database management tools tests."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace

from coworker.secrets import SecretStore
from coworker.tools.db_mgmt import (
    _execute_query,
    _is_readonly,
    _sqlite_query,
    db_tools,
)


def _make_context(secrets: SecretStore) -> SimpleNamespace:
    return SimpleNamespace(secrets=secrets)


def test_db_tools_factory():
    """Factory returns 4 tools (db_query, db_status, db_tables, db_backup)."""
    tools = db_tools()
    assert len(tools) == 4
    names = {t.__coworker_schema__["function"]["name"] for t in tools}
    assert names == {"db_query", "db_status", "db_tables", "db_backup"}


def test_is_readonly():
    assert _is_readonly("SELECT * FROM users") is True
    assert _is_readonly("  select count(*) from t") is True
    assert _is_readonly("SHOW TABLES") is True
    assert _is_readonly("DESCRIBE users") is True
    assert _is_readonly("EXPLAIN SELECT 1") is True
    assert _is_readonly("PRAGMA table_info(users)") is True
    assert _is_readonly("INSERT INTO users VALUES (1)") is False
    assert _is_readonly("UPDATE users SET x=1") is False
    assert _is_readonly("DELETE FROM users") is False
    assert _is_readonly("DROP TABLE users") is False


def test_db_query_readonly_enforcement(tmp_path):
    """When readonly=True, write queries must be rejected."""
    secrets = SecretStore(tmp_path / "secrets.json")
    secrets.put("database:test", {"type": "sqlite", "path": str(tmp_path / "test.db")})
    ctx = _make_context(secrets)

    tools = db_tools(ctx)
    # Find the db_query tool
    db_query = None
    for t in tools:
        if t.__coworker_schema__["function"]["name"] == "db_query":
            db_query = t
            break
    assert db_query is not None

    # Write query with readonly=True should be rejected
    result = db_query(query="INSERT INTO t VALUES (1)", database="test", readonly=True)
    assert result["ok"] is False
    assert "read-only" in result["error"].lower() or "readonly" in result["error"].lower()


def test_db_status_no_config():
    """When no database is configured, status returns an error."""
    tools = db_tools(context=None)
    db_status = None
    for t in tools:
        if t.__coworker_schema__["function"]["name"] == "db_status":
            db_status = t
            break
    result = db_status(database="default")
    assert result["ok"] is False
    assert "not configured" in result["error"]


def test_db_tables_no_config():
    """When no database is configured, tables returns an error."""
    tools = db_tools(context=None)
    db_tables = None
    for t in tools:
        if t.__coworker_schema__["function"]["name"] == "db_tables":
            db_tables = t
            break
    result = db_tables(database="default")
    assert result["ok"] is False
    assert "not configured" in result["error"]


def test_sqlite_query(tmp_path):
    """Verify SQLite queries actually work end-to-end."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items VALUES (1, 'alpha')")
    conn.execute("INSERT INTO items VALUES (2, 'beta')")
    conn.commit()
    conn.close()

    cfg = {"type": "sqlite", "path": str(db_path)}
    result = _execute_query(cfg, "SELECT * FROM items ORDER BY id")
    assert result["ok"] is True
    assert len(result["rows"]) == 2
    assert result["rows"][0]["name"] == "alpha"


def test_sqlite_query_missing_path():
    cfg = {"type": "sqlite", "path": ""}
    result = _execute_query(cfg, "SELECT 1")
    assert result["ok"] is False


def test_unsupported_db_type():
    cfg = {"type": "oracle"}
    result = _execute_query(cfg, "SELECT 1")
    assert result["ok"] is False
    assert "unsupported" in result["error"]
