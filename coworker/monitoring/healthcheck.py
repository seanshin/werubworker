"""HealthCheckManager — SQLite-backed persistent health-check scheduler.

Supports multiple check types (HTTP, TCP, DNS, ping, SSL cert, Docker,
Kubernetes pod, process) with retry logic, consecutive-failure tracking,
and historical result storage with configurable retention.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import sqlite3
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class HealthCheckRule:
    id: str  # "check-{hex}"
    name: str
    type: str  # "http", "tcp", "dns", "ping", "ssl_cert", "docker", "k8s_pod", "process"
    target: str  # URL, host:port, domain, container name, pod name, process name
    interval_seconds: int = 60
    timeout_seconds: int = 10
    retries: int = 3
    alert_channels: list[str] = field(default_factory=list)  # e.g. ["slack:C01234"]
    escalation_after: int = 3  # escalate after N consecutive failures
    metadata: dict = field(default_factory=dict)  # expected_status_code, pattern, etc.
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "target": self.target,
            "interval_seconds": self.interval_seconds,
            "timeout_seconds": self.timeout_seconds,
            "retries": self.retries,
            "alert_channels": self.alert_channels,
            "escalation_after": self.escalation_after,
            "metadata": self.metadata,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HealthCheckRule:
        return cls(
            id=d["id"],
            name=d["name"],
            type=d["type"],
            target=d["target"],
            interval_seconds=d.get("interval_seconds", 60),
            timeout_seconds=d.get("timeout_seconds", 10),
            retries=d.get("retries", 3),
            alert_channels=d.get("alert_channels", []),
            escalation_after=d.get("escalation_after", 3),
            metadata=d.get("metadata", {}),
            enabled=d.get("enabled", True),
        )


@dataclass
class CheckResult:
    check_id: str
    timestamp: float
    status: str  # "ok", "fail", "warn"
    latency_ms: float
    error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Valid check types
# ---------------------------------------------------------------------------

_VALID_TYPES = frozenset(
    {"http", "tcp", "dns", "ping", "ssl_cert", "docker", "k8s_pod", "process"}
)


# ---------------------------------------------------------------------------
# HealthCheckManager
# ---------------------------------------------------------------------------


class HealthCheckManager:
    """Persistent health-check manager backed by SQLite."""

    def __init__(self, data_dir: Path):
        self._db = data_dir / "monitoring.db"
        self._lock = threading.Lock()
        self._consecutive_failures: dict[str, int] = {}
        self._init_db()

    # ------------------------------------------------------------------
    # SQLite helpers
    # ------------------------------------------------------------------

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
                CREATE TABLE IF NOT EXISTS health_checks (
                    id                TEXT PRIMARY KEY,
                    name              TEXT NOT NULL,
                    type              TEXT NOT NULL,
                    target            TEXT NOT NULL,
                    interval_seconds  INTEGER NOT NULL DEFAULT 60,
                    timeout_seconds   INTEGER NOT NULL DEFAULT 10,
                    retries           INTEGER NOT NULL DEFAULT 3,
                    alert_channels    TEXT NOT NULL DEFAULT '[]',
                    escalation_after  INTEGER NOT NULL DEFAULT 3,
                    metadata          TEXT NOT NULL DEFAULT '{}',
                    enabled           INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS health_results (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    check_id    TEXT NOT NULL,
                    ts          INTEGER NOT NULL,
                    status      TEXT NOT NULL,
                    latency_ms  REAL NOT NULL DEFAULT 0,
                    error       TEXT NOT NULL DEFAULT '',
                    metadata    TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (check_id) REFERENCES health_checks(id)
                );
                CREATE INDEX IF NOT EXISTS idx_health_results_check_ts
                    ON health_results(check_id, ts);
            """)

    # ------------------------------------------------------------------
    # CRUD — check rules
    # ------------------------------------------------------------------

    def add_check(self, rule: HealthCheckRule) -> dict:
        """Add or update a health-check rule."""
        if rule.type not in _VALID_TYPES:
            return {"ok": False, "error": f"unsupported check type '{rule.type}'"}
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO health_checks "
                "(id, name, type, target, interval_seconds, timeout_seconds, "
                "retries, alert_channels, escalation_after, metadata, enabled) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rule.id,
                    rule.name,
                    rule.type,
                    rule.target,
                    rule.interval_seconds,
                    rule.timeout_seconds,
                    rule.retries,
                    json.dumps(rule.alert_channels),
                    rule.escalation_after,
                    json.dumps(rule.metadata),
                    1 if rule.enabled else 0,
                ),
            )
        return {"ok": True, "check_id": rule.id}

    def remove_check(self, check_id: str) -> dict:
        """Remove a health-check rule and its result history."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM health_checks WHERE id = ?", (check_id,)
            ).fetchone()
            if row is None:
                return {"ok": False, "error": f"check '{check_id}' not found"}
            conn.execute("DELETE FROM health_results WHERE check_id = ?", (check_id,))
            conn.execute("DELETE FROM health_checks WHERE id = ?", (check_id,))
        self._consecutive_failures.pop(check_id, None)
        return {"ok": True, "check_id": check_id}

    def list_checks(self, enabled_only: bool = True) -> list[dict]:
        """List all (or only enabled) health-check rules."""
        with self._connect() as conn:
            if enabled_only:
                rows = conn.execute(
                    "SELECT * FROM health_checks WHERE enabled = 1 ORDER BY name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM health_checks ORDER BY name"
                ).fetchall()
        return [self._row_to_rule_dict(r) for r in rows]

    def get_check(self, check_id: str) -> dict | None:
        """Get a single health-check rule by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM health_checks WHERE id = ?", (check_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_rule_dict(row)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run_checks(self) -> list[dict]:
        """Run all enabled checks in parallel via asyncio.gather."""
        checks = self.list_checks(enabled_only=True)
        if not checks:
            return []
        rules = [HealthCheckRule.from_dict(c) for c in checks]
        tasks = [self.run_single(rule) for rule in rules]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[dict] = []
        for rule, raw in zip(rules, raw_results):
            if isinstance(raw, BaseException):
                result = CheckResult(
                    check_id=rule.id,
                    timestamp=time.time(),
                    status="fail",
                    latency_ms=0,
                    error=str(raw),
                )
            else:
                result = raw  # type: ignore[assignment]

            # Track consecutive failures
            if result.status == "ok":
                self._consecutive_failures[rule.id] = 0
            else:
                self._consecutive_failures[rule.id] = (
                    self._consecutive_failures.get(rule.id, 0) + 1
                )

            self._record_result(result)
            rd = result.to_dict()
            rd["consecutive_failures"] = self._consecutive_failures.get(rule.id, 0)
            rd["escalated"] = (
                self._consecutive_failures.get(rule.id, 0) >= rule.escalation_after
            )
            results.append(rd)
        return results

    async def run_single(self, rule: HealthCheckRule) -> CheckResult:
        """Run a single check with retry logic."""
        result: CheckResult | None = None
        for _attempt in range(max(rule.retries, 1)):
            result = await self._execute_check(rule)
            if result.status == "ok":
                return result
        return result  # type: ignore[return-value]  # last failed result

    async def _execute_check(self, rule: HealthCheckRule) -> CheckResult:
        """Dispatch to the appropriate checker; catch all exceptions."""
        handlers: dict[str, Any] = {
            "http": self._check_http,
            "tcp": self._check_tcp,
            "dns": self._check_dns,
            "ping": self._check_ping,
            "ssl_cert": self._check_ssl_cert,
            "docker": self._check_docker,
            "k8s_pod": self._check_k8s_pod,
            "process": self._check_process,
        }
        handler = handlers.get(rule.type)
        if handler is None:
            return CheckResult(
                check_id=rule.id,
                timestamp=time.time(),
                status="fail",
                latency_ms=0,
                error=f"unknown check type '{rule.type}'",
            )
        try:
            return await handler(rule)
        except Exception as exc:
            return CheckResult(
                check_id=rule.id,
                timestamp=time.time(),
                status="fail",
                latency_ms=0,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Check-type implementations
    # ------------------------------------------------------------------

    async def _check_http(self, rule: HealthCheckRule) -> CheckResult:
        """HTTP(S) GET check via httpx. Supports expected_status_code and pattern."""
        import httpx

        start = time.monotonic()
        async with httpx.AsyncClient(
            timeout=rule.timeout_seconds, verify=False
        ) as client:
            resp = await client.get(rule.target)
        latency = (time.monotonic() - start) * 1000
        expected = rule.metadata.get("expected_status_code", 200)
        status = "ok" if resp.status_code == expected else "fail"
        error = ""
        meta: dict[str, Any] = {"status_code": resp.status_code}

        # Optional response body pattern matching
        pattern = rule.metadata.get("pattern")
        if pattern and status == "ok":
            if not re.search(pattern, resp.text):
                status = "fail"
                error = f"pattern '{pattern}' not found in response body"

        if status == "fail" and not error:
            error = f"expected {expected}, got {resp.status_code}"

        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status=status,
            latency_ms=latency,
            error=error,
            metadata=meta,
        )

    async def _check_tcp(self, rule: HealthCheckRule) -> CheckResult:
        """TCP port connectivity check via asyncio.open_connection."""
        host, port_str = rule.target.rsplit(":", 1)
        port = int(port_str)
        start = time.monotonic()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=rule.timeout_seconds,
        )
        latency = (time.monotonic() - start) * 1000
        writer.close()
        await writer.wait_closed()
        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status="ok",
            latency_ms=latency,
        )

    async def _check_dns(self, rule: HealthCheckRule) -> CheckResult:
        """DNS resolution check via socket.getaddrinfo in a thread pool."""
        loop = asyncio.get_running_loop()
        start = time.monotonic()
        addrs = await asyncio.wait_for(
            loop.run_in_executor(
                None, socket.getaddrinfo, rule.target, None
            ),
            timeout=rule.timeout_seconds,
        )
        latency = (time.monotonic() - start) * 1000
        resolved = list({a[4][0] for a in addrs})
        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status="ok",
            latency_ms=latency,
            metadata={"resolved": resolved},
        )

    async def _check_ping(self, rule: HealthCheckRule) -> CheckResult:
        """ICMP ping check via subprocess (ping -c 1)."""
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "ping", "-c", "1", "-W", str(rule.timeout_seconds), rule.target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=rule.timeout_seconds + 5
        )
        latency = (time.monotonic() - start) * 1000

        if proc.returncode != 0:
            return CheckResult(
                check_id=rule.id,
                timestamp=time.time(),
                status="fail",
                latency_ms=latency,
                error=stderr.decode(errors="replace").strip() or "ping failed",
            )

        # Try to extract round-trip time from ping output
        meta: dict[str, Any] = {}
        output = stdout.decode(errors="replace")
        m = re.search(r"time[=<]([\d.]+)\s*ms", output)
        if m:
            meta["rtt_ms"] = float(m.group(1))

        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status="ok",
            latency_ms=latency,
            metadata=meta,
        )

    async def _check_ssl_cert(self, rule: HealthCheckRule) -> CheckResult:
        """SSL certificate expiry check. warn if <=30 days, fail if <=7 days."""
        loop = asyncio.get_running_loop()

        def _get_cert_expiry() -> tuple[float, datetime]:
            start = time.monotonic()
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection(
                (rule.target, 443), timeout=rule.timeout_seconds
            ) as sock:
                with ctx.wrap_socket(sock, server_hostname=rule.target) as ssock:
                    cert_info = ssock.getpeercert()
            latency = (time.monotonic() - start) * 1000
            not_after_str = cert_info["notAfter"]  # type: ignore[index]
            # Format: "Mon DD HH:MM:SS YYYY GMT"
            expiry = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=timezone.utc
            )
            return latency, expiry

        latency, expiry = await asyncio.wait_for(
            loop.run_in_executor(None, _get_cert_expiry),
            timeout=rule.timeout_seconds + 5,
        )

        now = datetime.now(timezone.utc)
        days_remaining = (expiry - now).days
        meta = {"expiry": expiry.isoformat(), "days_remaining": days_remaining}

        if days_remaining <= 7:
            status = "fail"
            error = f"certificate expires in {days_remaining} days"
        elif days_remaining <= 30:
            status = "warn"
            error = f"certificate expires in {days_remaining} days"
        else:
            status = "ok"
            error = ""

        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status=status,
            latency_ms=latency,
            error=error,
            metadata=meta,
        )

    async def _check_docker(self, rule: HealthCheckRule) -> CheckResult:
        """Docker container status check via docker inspect."""
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "--format", "{{.State.Status}}", rule.target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=rule.timeout_seconds
        )
        latency = (time.monotonic() - start) * 1000

        if proc.returncode != 0:
            return CheckResult(
                check_id=rule.id,
                timestamp=time.time(),
                status="fail",
                latency_ms=latency,
                error=stderr.decode(errors="replace").strip(),
            )

        container_status = stdout.decode().strip()
        status = "ok" if container_status == "running" else "fail"
        error = "" if status == "ok" else f"container status: {container_status}"

        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status=status,
            latency_ms=latency,
            error=error,
            metadata={"container_status": container_status},
        )

    async def _check_k8s_pod(self, rule: HealthCheckRule) -> CheckResult:
        """Kubernetes pod health check via kubectl get pod."""
        start = time.monotonic()
        cmd = ["kubectl", "get", "pod", rule.target, "-o", "json"]
        # Support namespace in metadata
        ns = rule.metadata.get("namespace")
        if ns:
            cmd.extend(["-n", ns])
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=rule.timeout_seconds
        )
        latency = (time.monotonic() - start) * 1000

        if proc.returncode != 0:
            return CheckResult(
                check_id=rule.id,
                timestamp=time.time(),
                status="fail",
                latency_ms=latency,
                error=stderr.decode(errors="replace").strip(),
            )

        pod_info = json.loads(stdout.decode())
        phase = pod_info.get("status", {}).get("phase", "Unknown")
        # Check container statuses for CrashLoopBackOff
        container_statuses = pod_info.get("status", {}).get("containerStatuses", [])
        crash_loop = any(
            cs.get("state", {}).get("waiting", {}).get("reason") == "CrashLoopBackOff"
            for cs in container_statuses
        )

        if crash_loop:
            status = "fail"
            error = "CrashLoopBackOff detected"
        elif phase == "Running":
            status = "ok"
            error = ""
        else:
            status = "fail"
            error = f"pod phase: {phase}"

        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status=status,
            latency_ms=latency,
            error=error,
            metadata={"phase": phase, "crash_loop": crash_loop},
        )

    async def _check_process(self, rule: HealthCheckRule) -> CheckResult:
        """Process existence check via pgrep."""
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "pgrep", "-f", rule.target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=rule.timeout_seconds
        )
        latency = (time.monotonic() - start) * 1000

        pids = stdout.decode().strip().split("\n") if stdout.decode().strip() else []
        if proc.returncode == 0 and pids:
            return CheckResult(
                check_id=rule.id,
                timestamp=time.time(),
                status="ok",
                latency_ms=latency,
                metadata={"pids": pids},
            )
        return CheckResult(
            check_id=rule.id,
            timestamp=time.time(),
            status="fail",
            latency_ms=latency,
            error=f"process '{rule.target}' not found",
        )

    # ------------------------------------------------------------------
    # Result storage & queries
    # ------------------------------------------------------------------

    def _record_result(self, result: CheckResult) -> None:
        """Persist a check result to SQLite."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO health_results (check_id, ts, status, latency_ms, error, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    result.check_id,
                    int(result.timestamp),
                    result.status,
                    result.latency_ms,
                    result.error,
                    json.dumps(result.metadata),
                ),
            )

    def get_history(self, check_id: str, hours: int = 24) -> list[dict]:
        """Retrieve check results for the last N hours."""
        cutoff = int(time.time()) - (hours * 3600)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT check_id, ts, status, latency_ms, error, metadata "
                "FROM health_results WHERE check_id = ? AND ts >= ? "
                "ORDER BY ts DESC",
                (check_id, cutoff),
            ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else {}
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            results.append(d)
        return results

    def uptime_percentage(self, check_id: str, days: int = 30) -> float:
        """Calculate the OK-result ratio over the last N days."""
        cutoff = int(time.time()) - (days * 86400)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as total, "
                "SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) as ok_count "
                "FROM health_results WHERE check_id = ? AND ts >= ?",
                (check_id, cutoff),
            ).fetchone()
        if row is None or row["total"] == 0:
            return 0.0
        return round((row["ok_count"] / row["total"]) * 100, 2)

    def prune_results(self, retention_days: int = 7) -> dict:
        """Delete results older than retention_days."""
        cutoff = int(time.time()) - (retention_days * 86400)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM health_results WHERE ts < ?", (cutoff,)
            )
            deleted = cursor.rowcount
        return {"ok": True, "deleted": deleted}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_rule_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["alert_channels"] = json.loads(d["alert_channels"]) if d.get("alert_channels") else []
        except (json.JSONDecodeError, TypeError):
            d["alert_channels"] = []
        try:
            d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else {}
        except (json.JSONDecodeError, TypeError):
            d["metadata"] = {}
        d["enabled"] = bool(d.get("enabled", 1))
        return d
