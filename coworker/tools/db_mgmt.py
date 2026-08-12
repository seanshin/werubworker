"""Database management tools — query, status, table listing, and backup.

Supports PostgreSQL, MySQL, and SQLite. For PostgreSQL and MySQL, tries the
native Python driver first (``psycopg2`` / ``pymysql``), then falls back to the
CLI client (``psql`` / ``mysql``) via ``subprocess``. SQLite uses the stdlib
``sqlite3`` module.

Database connection profiles are stored in ``secrets.json`` under keys like
``database:<profile_name>`` (e.g. ``database:production``).

Write queries (INSERT/UPDATE/DELETE/…) and backups require approval.
"""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from typing import Any, Optional

import aisuite as ai

# ---------------------------------------------------------------------------
# Driver availability
# ---------------------------------------------------------------------------
try:
    import psycopg2  # type: ignore[import-untyped]

    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

try:
    import pymysql  # type: ignore[import-untyped]

    _HAS_PYMYSQL = True
except ImportError:
    _HAS_PYMYSQL = False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PREFIX = "database:"

# Statements that are safe to run without approval.
_READONLY_PREFIXES = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|DESC|EXPLAIN|PRAGMA)\b", re.IGNORECASE)


def _is_readonly(query: str) -> bool:
    """Return True if *query* starts with a read-only statement keyword."""
    return bool(_READONLY_PREFIXES.match(query.strip()))


# ---------------------------------------------------------------------------
# SecretStore helpers
# ---------------------------------------------------------------------------


def _expand_env(value: str) -> str:
    """Replace $VAR or ${VAR} with environment variable values."""
    if not isinstance(value, str) or "$" not in value:
        return value
    return re.sub(r'\$\{?(\w+)\}?', lambda m: os.environ.get(m.group(1), m.group(0)), value)


def _resolve_config(context: Any, database: str) -> Optional[dict[str, Any]]:
    """Look up ``database:<name>`` in the SecretStore attached to *context*.

    If a vault is available on *context*, retrieve the password from vault
    (key ``database:<name>:password``) and inject it into the returned config.
    Environment variable references ($VAR or ${VAR}) in host, user, password,
    and path fields are expanded.
    """
    secrets = getattr(context, "secrets", None) if context is not None else None
    if secrets is None:
        return None
    cfg = secrets.get(_PREFIX + database)
    if cfg is None:
        return None
    # Try to retrieve password from vault
    vault = getattr(context, "vault", None)
    if vault is not None:
        try:
            cfg["password"] = vault.retrieve(f"database:{database}:password")
        except (KeyError, RuntimeError):
            pass  # Not in vault or vault locked — use profile value
    # Expand environment variable references in connection fields
    for field in ("host", "user", "password", "path"):
        if field in cfg:
            cfg[field] = _expand_env(cfg[field])
    return cfg


def _list_databases(context: Any) -> list[dict[str, Any]]:
    """Return metadata for every registered database (never leaks passwords)."""
    secrets = getattr(context, "secrets", None) if context is not None else None
    if secrets is None:
        return []
    databases: list[dict[str, Any]] = []
    for entry in secrets.status():
        profile_key = entry["profile"]
        if not profile_key.startswith(_PREFIX):
            continue
        db_name = profile_key[len(_PREFIX) :]
        data = secrets.get(profile_key) or {}
        databases.append(
            {
                "name": db_name,
                "type": data.get("type", ""),
                "host": data.get("host", ""),
                "port": data.get("port", ""),
                "database": data.get("name", data.get("path", "")),
            }
        )
    return databases


def _add_database(
    context: Any,
    name: str,
    db_type: str,
    host: str = "",
    port: int = 0,
    db_name: str = "",
    user: str = "",
    password: str = "",
    path: str = "",
) -> dict[str, Any]:
    """Register a new database profile. Returns ``{ok: True}`` or an error dict."""
    secrets = getattr(context, "secrets", None) if context is not None else None
    if secrets is None:
        return {"ok": False, "error": "secret store not available"}
    name = name.strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    db_type = db_type.strip().lower()
    if db_type not in ("postgresql", "mysql", "sqlite"):
        return {"ok": False, "error": f"unsupported database type: {db_type}"}

    key = _PREFIX + name
    if secrets.get(key) is not None:
        return {"ok": False, "error": f"database '{name}' already exists"}

    profile: dict[str, Any] = {"type": db_type}
    if db_type == "sqlite":
        profile["path"] = path.strip()
    else:
        profile["host"] = host.strip()
        profile["port"] = int(port) if port else (5432 if db_type == "postgresql" else 3306)
        profile["name"] = db_name.strip()
        profile["user"] = user.strip()
        if password:
            # Store password in vault when available; fall back to secrets profile
            vault = getattr(context, "vault", None)
            if vault is not None:
                try:
                    vault.store(f"database:{name}:password", password)
                except Exception:
                    profile["password"] = password
            else:
                profile["password"] = password
    secrets.put(key, profile)
    return {"ok": True, "name": name}


def _remove_database(context: Any, name: str) -> dict[str, Any]:
    """Remove a registered database profile."""
    secrets = getattr(context, "secrets", None) if context is not None else None
    if secrets is None:
        return {"ok": False, "error": "secret store not available"}
    key = _PREFIX + name.strip()
    if secrets.delete(key):
        return {"ok": True, "removed": name}
    return {"ok": False, "error": f"database '{name}' not found"}


# ---------------------------------------------------------------------------
# Execution backends
# ---------------------------------------------------------------------------


def _run_cli(cmd: list[str], timeout: int = 30, env: Optional[dict] = None) -> str:
    """Run a CLI command and return stdout. Raises on failure."""
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"command failed with exit code {r.returncode}")
    return r.stdout.strip()


# -- PostgreSQL -------------------------------------------------------------


def _pg_python(cfg: dict, query: str) -> list[dict]:
    import psycopg2 as pg
    import psycopg2.extras  # type: ignore[import-untyped]

    conn = pg.connect(
        host=cfg.get("host", "localhost"),
        port=int(cfg.get("port", 5432)),
        dbname=cfg.get("name", ""),
        user=cfg.get("user", ""),
        password=cfg.get("password", ""),
        connect_timeout=10,
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            if cur.description:
                rows = cur.fetchmany(1000)
                return [dict(r) for r in rows]
            return [{"affected_rows": cur.rowcount}]
    finally:
        conn.close()


def _pg_cli(cfg: dict, query: str) -> str:
    env = {}
    if cfg.get("password"):
        env["PGPASSWORD"] = cfg["password"]
    cmd = [
        "psql",
        "-h",
        cfg.get("host", "localhost"),
        "-p",
        str(cfg.get("port", 5432)),
        "-U",
        cfg.get("user", ""),
        "-d",
        cfg.get("name", ""),
        "-c",
        query,
        "--no-psqlrc",
        "-P",
        "pager=off",
    ]
    return _run_cli(cmd, env=env)


# -- MySQL ------------------------------------------------------------------


def _mysql_python(cfg: dict, query: str) -> list[dict]:
    import pymysql as pm

    conn = pm.connect(
        host=cfg.get("host", "localhost"),
        port=int(cfg.get("port", 3306)),
        database=cfg.get("name", ""),
        user=cfg.get("user", ""),
        password=cfg.get("password", ""),
        connect_timeout=10,
        cursorclass=pm.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            if cur.description:
                rows = cur.fetchmany(1000)
                return [dict(r) for r in rows]
            conn.commit()
            return [{"affected_rows": cur.rowcount}]
    finally:
        conn.close()


def _mysql_cli(cfg: dict, query: str) -> str:
    cmd = [
        "mysql",
        "-h",
        cfg.get("host", "localhost"),
        "-P",
        str(cfg.get("port", 3306)),
        "-u",
        cfg.get("user", ""),
        cfg.get("name", ""),
        "-e",
        query,
    ]
    # Pass password via environment (avoids ps exposure)
    env = dict(os.environ, MYSQL_PWD=cfg.get("password", ""))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"mysql exit {result.returncode}")
    return result.stdout


# -- SQLite -----------------------------------------------------------------


def _sqlite_query(cfg: dict, query: str) -> list[dict]:
    path = cfg.get("path", "")
    if not path:
        raise ValueError("sqlite path not configured")
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(query)
        if cur.description:
            rows = cur.fetchmany(1000)
            return [dict(r) for r in rows]
        conn.commit()
        return [{"affected_rows": cur.rowcount}]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Unified dispatcher
# ---------------------------------------------------------------------------


def _execute_query(
    cfg: dict, query: str, *, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    """Execute *query* against the database described by *cfg*.

    *offset* and *limit* apply to Python-driver result sets (rows are fetched up
    to ``min(limit, 1000)`` after skipping *offset*).  CLI fallbacks ignore them.
    """
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    fetch_count = offset + limit  # fetch enough to slice

    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            if _HAS_PSYCOPG2:
                rows = _pg_python(cfg, query)
                sliced = rows[offset : offset + limit]
                return {"ok": True, "rows": sliced, "total_fetched": len(rows), "driver": "psycopg2"}
            out = _pg_cli(cfg, query)
            return {"ok": True, "output": out, "driver": "psql"}
        elif db_type == "mysql":
            if _HAS_PYMYSQL:
                rows = _mysql_python(cfg, query)
                sliced = rows[offset : offset + limit]
                return {"ok": True, "rows": sliced, "total_fetched": len(rows), "driver": "pymysql"}
            out = _mysql_cli(cfg, query)
            return {"ok": True, "output": out, "driver": "mysql"}
        elif db_type == "sqlite":
            rows = _sqlite_query(cfg, query)
            sliced = rows[offset : offset + limit]
            return {"ok": True, "rows": sliced, "total_fetched": len(rows), "driver": "sqlite3"}
        else:
            return {"ok": False, "error": f"unsupported database type: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _get_status(cfg: dict) -> dict[str, Any]:
    """Return status info: connection count, database size, version."""
    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            version = _execute_query(cfg, "SELECT version();")
            conns = _execute_query(cfg, "SELECT count(*) AS connections FROM pg_stat_activity;")
            size = _execute_query(
                cfg,
                "SELECT pg_size_pretty(pg_database_size(current_database())) AS size;",
            )
            return {
                "ok": True,
                "type": "postgresql",
                "version": _extract_scalar(version),
                "connections": _extract_scalar(conns),
                "size": _extract_scalar(size),
            }
        elif db_type == "mysql":
            version = _execute_query(cfg, "SELECT version() AS version;")
            conns = _execute_query(cfg, "SHOW STATUS LIKE 'Threads_connected';")
            return {
                "ok": True,
                "type": "mysql",
                "version": _extract_scalar(version),
                "connections": _extract_scalar(conns),
            }
        elif db_type == "sqlite":
            path = cfg.get("path", "")
            size = os.path.getsize(path) if path and os.path.exists(path) else 0
            version = _execute_query(cfg, "SELECT sqlite_version() AS version;")
            return {
                "ok": True,
                "type": "sqlite",
                "version": _extract_scalar(version),
                "size_bytes": size,
            }
        else:
            return {"ok": False, "error": f"unsupported type: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _extract_scalar(result: dict) -> Any:
    """Pull a single scalar value from a query result dict."""
    if not result.get("ok"):
        return result.get("error", "unknown")
    rows = result.get("rows")
    if rows and isinstance(rows, list) and len(rows) > 0:
        row = rows[0]
        if isinstance(row, dict):
            vals = list(row.values())
            return vals[0] if vals else None
    return result.get("output", "")


def _get_tables(cfg: dict) -> dict[str, Any]:
    """List tables with approximate row counts."""
    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            q = (
                "SELECT schemaname, relname AS table_name, n_live_tup AS row_count "
                "FROM pg_stat_user_tables ORDER BY relname;"
            )
            return _execute_query(cfg, q)
        elif db_type == "mysql":
            db_name = cfg.get("name", "")
            q = (
                f"SELECT table_name, table_rows AS row_count "
                f"FROM information_schema.tables "
                f"WHERE table_schema = '{db_name}' ORDER BY table_name;"
            )
            return _execute_query(cfg, q)
        elif db_type == "sqlite":
            # Get table list first, then row counts
            tables_result = _execute_query(
                cfg,
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;",
            )
            if not tables_result.get("ok"):
                return tables_result
            rows = tables_result.get("rows", [])
            table_info = []
            for row in rows:
                tname = row.get("name", "")
                # Validate table name to prevent SQL injection
                if not tname or not all(c.isalnum() or c == "_" for c in tname):
                    continue
                count_result = _execute_query(cfg, f'SELECT count(*) AS row_count FROM "{tname}";')
                count = _extract_scalar(count_result) if count_result.get("ok") else "?"
                table_info.append({"table_name": tname, "row_count": count})
            return {"ok": True, "rows": table_info, "driver": "sqlite3"}
        else:
            return {"ok": False, "error": f"unsupported type: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


_SAFE_TABLE_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _validate_table_name(table: str) -> str | None:
    """Return an error string if *table* contains unsafe characters, else None."""
    if not table or not _SAFE_TABLE_RE.match(table):
        return f"invalid table name: {table!r}"
    return None


def _get_columns(cfg: dict, table: str) -> dict:
    """Get column details for a table."""
    err = _validate_table_name(table)
    if err:
        return {"ok": False, "error": err}
    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            q = (f"SELECT column_name, data_type, is_nullable, column_default "
                 f"FROM information_schema.columns "
                 f"WHERE table_name = '{table}' ORDER BY ordinal_position;")
            return _execute_query(cfg, q)
        elif db_type == "mysql":
            return _execute_query(cfg, f"DESCRIBE `{table}`;")
        elif db_type == "sqlite":
            return _execute_query(cfg, f'PRAGMA table_info("{table}");')
        return {"ok": False, "error": f"unsupported type: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _get_indexes(cfg: dict, table: str) -> dict:
    """Get indexes for a table."""
    err = _validate_table_name(table)
    if err:
        return {"ok": False, "error": err}
    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            q = (f"SELECT indexname, indexdef FROM pg_indexes "
                 f"WHERE tablename = '{table}';")
            return _execute_query(cfg, q)
        elif db_type == "mysql":
            return _execute_query(cfg, f"SHOW INDEX FROM `{table}`;")
        elif db_type == "sqlite":
            return _execute_query(cfg, f'PRAGMA index_list("{table}");')
        return {"ok": False, "error": f"unsupported type: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _get_foreign_keys(cfg: dict, table: str) -> dict:
    """Get foreign key relationships."""
    err = _validate_table_name(table)
    if err:
        return {"ok": False, "error": err}
    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            q = (f"SELECT tc.constraint_name, kcu.column_name, "
                 f"ccu.table_name AS foreign_table, ccu.column_name AS foreign_column "
                 f"FROM information_schema.table_constraints tc "
                 f"JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name "
                 f"JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name "
                 f"WHERE tc.table_name = '{table}' AND tc.constraint_type = 'FOREIGN KEY';")
            return _execute_query(cfg, q)
        elif db_type == "sqlite":
            return _execute_query(cfg, f'PRAGMA foreign_key_list("{table}");')
        return {"ok": True, "rows": []}  # MySQL: complex query, skip for now
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _generate_erd_mermaid(cfg: dict) -> dict:
    """Generate Mermaid ER diagram from database schema."""
    tables_result = _get_tables(cfg)
    if not tables_result.get("ok"):
        return tables_result

    lines = ["erDiagram"]
    table_names = [r.get("table_name", r.get("name", "")) for r in tables_result.get("rows", [])]

    for table in table_names:
        if not table or not all(c.isalnum() or c == "_" for c in table):
            continue
        cols_result = _get_columns(cfg, table)
        if cols_result.get("ok"):
            lines.append(f"    {table} {{")
            for col in cols_result.get("rows", [])[:20]:  # Limit columns
                col_name = col.get("column_name", col.get("name", col.get("Field", "")))
                col_type = col.get("data_type", col.get("type", col.get("Type", "text")))
                if col_name:
                    safe_type = col_type.split("(")[0].replace(" ", "_") if col_type else "text"
                    lines.append(f"        {safe_type} {col_name}")
            lines.append("    }")

        # Foreign keys
        fk_result = _get_foreign_keys(cfg, table)
        if fk_result.get("ok"):
            for fk in fk_result.get("rows", []):
                ref_table = fk.get("foreign_table", fk.get("table", ""))
                if ref_table and ref_table in table_names:
                    lines.append(f"    {table} }}o--|| {ref_table} : references")

    return {"ok": True, "mermaid": "\n".join(lines)}


def _get_db_status(cfg: dict) -> dict[str, Any]:
    """Return status info: version, connection info (no password), size, table count."""
    db_type = cfg.get("type", "").lower()
    try:
        base = _get_status(cfg)
        # Add table count
        tables_result = _get_tables(cfg)
        table_count = len(tables_result.get("rows", [])) if tables_result.get("ok") else 0
        base["table_count"] = table_count
        # Add sanitised connection info (no password)
        base["host"] = cfg.get("host", "")
        base["port"] = cfg.get("port", "")
        base["database"] = cfg.get("name", cfg.get("path", ""))
        base["user"] = cfg.get("user", "")
        return base
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _list_migrations(cfg: dict) -> dict[str, Any]:
    """List migration history (framework-dependent)."""
    db_type = cfg.get("type", "").lower()
    try:
        if db_type == "postgresql":
            for table in ["schema_migrations", "alembic_version", "django_migrations", "_prisma_migrations"]:
                result = _execute_query(cfg, f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT 50;")
                if result.get("ok") and result.get("rows"):
                    return {"ok": True, "table": table, "rows": result["rows"], "driver": result.get("driver")}
            return {"ok": True, "rows": [], "message": "No migration table found"}
        elif db_type == "mysql":
            for table in ["schema_migrations", "alembic_version", "django_migrations"]:
                result = _execute_query(cfg, f"SELECT * FROM {table} ORDER BY 1 DESC LIMIT 50;")
                if result.get("ok") and result.get("rows"):
                    return {"ok": True, "table": table, "rows": result["rows"]}
            return {"ok": True, "rows": [], "message": "No migration table found"}
        elif db_type == "sqlite":
            result = _execute_query(
                cfg,
                "SELECT name FROM sqlite_master WHERE type='table' AND "
                "(name LIKE '%migration%' OR name LIKE '%alembic%');",
            )
            if result.get("ok") and result.get("rows"):
                table = result["rows"][0].get("name", "")
                if table:
                    return _execute_query(cfg, f'SELECT * FROM "{table}" ORDER BY 1 DESC LIMIT 50;')
            return {"ok": True, "rows": [], "message": "No migration table found"}
        return {"ok": False, "error": f"unsupported: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _do_backup(cfg: dict, output_path: str) -> dict[str, Any]:
    """Create a database backup using pg_dump / mysqldump / sqlite3 .backup."""
    db_type = cfg.get("type", "").lower()
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        db_name = cfg.get("name", cfg.get("path", "db"))
        if "/" in db_name:
            db_name = os.path.basename(db_name).rsplit(".", 1)[0]
        output_path = f"{db_name}_{ts}.sql"

    try:
        if db_type == "postgresql":
            if not shutil.which("pg_dump"):
                return {"ok": False, "error": "pg_dump not found on PATH"}
            env: dict[str, str] = {}
            if cfg.get("password"):
                env["PGPASSWORD"] = cfg["password"]
            cmd = [
                "pg_dump",
                "-h",
                cfg.get("host", "localhost"),
                "-p",
                str(cfg.get("port", 5432)),
                "-U",
                cfg.get("user", ""),
                "-d",
                cfg.get("name", ""),
                "-f",
                output_path,
            ]
            _run_cli(cmd, timeout=300, env=env)
            return {"ok": True, "path": output_path}

        elif db_type == "mysql":
            if not shutil.which("mysqldump"):
                return {"ok": False, "error": "mysqldump not found on PATH"}
            cmd = [
                "mysqldump",
                "-h",
                cfg.get("host", "localhost"),
                "-P",
                str(cfg.get("port", 3306)),
                "-u",
                cfg.get("user", ""),
                "--result-file",
                output_path,
                cfg.get("name", ""),
            ]
            env = dict(os.environ, MYSQL_PWD=cfg.get("password", ""))
            _run_cli(cmd, timeout=300, env=env)
            return {"ok": True, "path": output_path}

        elif db_type == "sqlite":
            src = cfg.get("path", "")
            if not src or not os.path.exists(src):
                return {"ok": False, "error": f"sqlite file not found: {src}"}
            conn = sqlite3.connect(src)
            try:
                with open(output_path, "w") as f:
                    for line in conn.iterdump():
                        f.write(f"{line}\n")
            finally:
                conn.close()
            return {"ok": True, "path": output_path}

        else:
            return {"ok": False, "error": f"unsupported type: {db_type}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Schema definitions (aisuite tool format)
# ---------------------------------------------------------------------------

_DB_QUERY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "db_query",
        "description": (
            "Execute a SQL query against a configured database. When readonly=True (default), "
            "only SELECT, SHOW, DESCRIBE, and EXPLAIN statements are allowed. Write queries "
            "require approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to execute.",
                },
                "database": {
                    "type": "string",
                    "description": "Database profile name (default: 'default').",
                },
                "readonly": {
                    "type": "boolean",
                    "description": "If true, only read-only queries are allowed (default: true).",
                },
            },
            "required": ["query"],
        },
    },
}

_DB_STATUS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "db_status",
        "description": ("Get database status: connection count, size, and version."),
        "parameters": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Database profile name (default: 'default').",
                },
            },
        },
    },
}

_DB_TABLES_SCHEMA = {
    "type": "function",
    "function": {
        "name": "db_tables",
        "description": "List tables with row counts in the specified database.",
        "parameters": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Database profile name (default: 'default').",
                },
            },
        },
    },
}

_DB_BACKUP_SCHEMA = {
    "type": "function",
    "function": {
        "name": "db_backup",
        "description": (
            "Create a database backup using pg_dump (PostgreSQL), mysqldump (MySQL), "
            "or sqlite3 dump (SQLite). Requires approval."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "database": {
                    "type": "string",
                    "description": "Database profile name (default: 'default').",
                },
                "output_path": {
                    "type": "string",
                    "description": "Output file path for the backup (auto-generated if empty).",
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Public factory — called by catalog.py
# ---------------------------------------------------------------------------


def db_tools(context: Any = None) -> list:
    """Return database management tools. DB config from secrets.json database:* profiles.

    Tools: db_query, db_status, db_tables, db_backup.
    """

    def db_query(query: str, database: str = "default", readonly: bool = True) -> dict:
        """Execute a SQL query. readonly=True allows only SELECT. Write queries require approval."""
        cfg = _resolve_config(context, database)
        if cfg is None:
            return {"ok": False, "error": f"database '{database}' not configured"}
        if readonly and not _is_readonly(query):
            return {
                "ok": False,
                "error": (
                    "Query is not read-only. Only SELECT, SHOW, DESCRIBE, and EXPLAIN "
                    "are allowed when readonly=True. Set readonly=False for write queries "
                    "(requires approval)."
                ),
            }
        return _execute_query(cfg, query)

    def db_status(database: str = "default") -> dict:
        """Database status: connection count, size, version."""
        cfg = _resolve_config(context, database)
        if cfg is None:
            return {"ok": False, "error": f"database '{database}' not configured"}
        return _get_status(cfg)

    def db_tables(database: str = "default") -> dict:
        """List tables with row counts."""
        cfg = _resolve_config(context, database)
        if cfg is None:
            return {"ok": False, "error": f"database '{database}' not configured"}
        return _get_tables(cfg)

    def db_backup(database: str = "default", output_path: str = "") -> dict:
        """Create database backup using pg_dump/mysqldump (requires approval)."""
        cfg = _resolve_config(context, database)
        if cfg is None:
            return {"ok": False, "error": f"database '{database}' not configured"}
        return _do_backup(cfg, output_path)

    _read_meta = ai.ToolMetadata(
        category="database",
        risk_level="low",
        capabilities=["database"],
        requires_approval=False,
    )

    _write_meta = ai.ToolMetadata(
        category="database",
        risk_level="high",
        capabilities=["database"],
        requires_approval=True,
    )

    tools = []
    for fn, schema, meta in [
        (db_query, _DB_QUERY_SCHEMA, _read_meta),
        (db_status, _DB_STATUS_SCHEMA, _read_meta),
        (db_tables, _DB_TABLES_SCHEMA, _read_meta),
        (db_backup, _DB_BACKUP_SCHEMA, _write_meta),
    ]:
        wrapped = ai.tool(fn, metadata=meta)
        wrapped.__coworker_schema__ = schema
        wrapped.__aisuite_tool_metadata__ = meta
        tools.append(wrapped)

    return tools
