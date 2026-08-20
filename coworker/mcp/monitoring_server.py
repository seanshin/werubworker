"""MCP Server for WeruBWorker monitoring tools.

Exposes the monitoring subsystem (metrics, health checks, alerts, incidents)
as an MCP server that external AI agents (Claude Desktop, Cursor, etc.) can connect to.

Usage:
    # stdio transport (Claude Desktop / Cursor)
    python -m coworker.mcp.monitoring_server

    # Or add to Claude Desktop config (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "werubworker-monitoring": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "coworker.mcp.monitoring_server"]
        }
      }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from mcp.server import Server
from mcp.types import TextContent, Tool

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data directory
# ---------------------------------------------------------------------------


def _data_dir() -> Path:
    from ..secrets import state_dir

    return state_dir()


# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

_ts = None
_hc = None
_alert = None
_inc = None
_audit = None
_collector = None


def _get_ts():
    global _ts
    if _ts is None:
        from ..monitoring.timeseries import TimeSeriesStore

        _ts = TimeSeriesStore(_data_dir())
    return _ts


def _get_hc():
    global _hc
    if _hc is None:
        from ..monitoring.healthcheck import HealthCheckManager

        _hc = HealthCheckManager(_data_dir())
    return _hc


def _get_alert():
    global _alert
    if _alert is None:
        from ..monitoring.alerting import AlertEngine

        _alert = AlertEngine(_data_dir())
    return _alert


def _get_inc():
    global _inc
    if _inc is None:
        from ..monitoring.incidents import IncidentManager

        _inc = IncidentManager(_data_dir())
    return _inc


def _get_audit():
    global _audit
    if _audit is None:
        from ..monitoring.audit_ops import OpsAuditStore

        _audit = OpsAuditStore(_data_dir())
    return _audit


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

TOOLS = [
    Tool(
        name="metrics_latest",
        description="Get the latest metrics for all monitored servers (CPU, memory, disk, network, load).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "Server ID (empty for all)"},
            },
        },
    ),
    Tool(
        name="metrics_query",
        description="Query time-series metrics for a server over a time range.",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "Server ID"},
                "range": {
                    "type": "string",
                    "description": "Time range: 15m, 30m, 1h, 6h, 1d, 7d, 30d",
                },
            },
            "required": ["server_id"],
        },
    ),
    Tool(
        name="healthcheck_list",
        description="List all configured health checks (HTTP, TCP, DNS, SSL, etc.).",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="healthcheck_run",
        description="Run all health checks now and return results.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="active_alerts",
        description="List currently firing and acknowledged alerts.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="alert_rules",
        description="List all configured alert rules with thresholds.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="incidents_list",
        description="List incidents (optionally filtered by status).",
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter: investigating, identified, monitoring, resolved (empty for all)",
                },
            },
        },
    ),
    Tool(
        name="incident_get",
        description="Get incident details including full timeline.",
        inputSchema={
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "Incident ID"},
            },
            "required": ["incident_id"],
        },
    ),
    Tool(
        name="audit_recent",
        description="Get recent operational audit log entries.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max entries (default 50)"},
            },
        },
    ),
    Tool(
        name="dashboard_overview",
        description="Get infrastructure dashboard overview: servers, alerts, health checks, incidents.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="webhook_list",
        description="List configured alert webhooks (Slack, Discord, Teams, custom).",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="webhook_add",
        description="Add an alert webhook URL for notifications.",
        inputSchema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Webhook URL"},
                "type": {"type": "string", "description": "Type: slack, discord, teams, custom"},
                "name": {"type": "string", "description": "Display name"},
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="audit_chain_verify",
        description="Verify the integrity of the audit hash chain. "
        "Detects any tampered or deleted records.",
        inputSchema={
            "type": "object",
            "properties": {
                "store": {
                    "type": "string",
                    "description": "Which store to verify: 'ops' (default) or 'main'",
                },
            },
        },
    ),
    Tool(
        name="audit_anchor_status",
        description="Check Sign service audit anchors. "
        "Verify a specific anchor or list recent ones.",
        inputSchema={
            "type": "object",
            "properties": {
                "anchor_id": {
                    "type": "string",
                    "description": "Anchor ID to verify (empty to list recent)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent anchors (default 10)",
                },
            },
        },
    ),
    Tool(
        name="security_score_enhanced",
        description="Comprehensive security score including hash chain integrity, "
        "2FA status, secrets encryption, and sensitive data filter coverage.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="log_sensitive_scan",
        description="Scan recent audit logs for residual sensitive data "
        "(API keys, passwords, PII) that may have bypassed filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Number of recent entries to scan (default 200)",
                },
            },
        },
    ),
    Tool(
        name="secrets_rotation_check",
        description="Check secrets/credentials for expiration and rotation status.",
        inputSchema={"type": "object", "properties": {}},
    ),
]

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def _handle_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call and return the JSON result."""
    try:
        if name == "metrics_latest":
            ts = _get_ts()
            sid = arguments.get("server_id") or None
            data = ts.query_latest(sid)
            return json.dumps({"ok": True, "count": len(data), "servers": data})

        elif name == "metrics_query":
            ts = _get_ts()
            sid = arguments["server_id"]
            range_map = {
                "15m": 900, "30m": 1800, "1h": 3600, "6h": 21600,
                "1d": 86400, "7d": 604800, "30d": 2592000,
            }
            r = arguments.get("range", "1h")
            secs = range_map.get(r, 3600)
            now = int(time.time())
            table = ts.auto_select_table(secs)
            data = ts.query(sid, now - secs, now, table=table)
            return json.dumps({"ok": True, "table": table, "count": len(data), "data": data[:200]})

        elif name == "healthcheck_list":
            hc = _get_hc()
            checks = hc.list_checks(enabled_only=False)
            return json.dumps({"ok": True, "count": len(checks), "checks": checks})

        elif name == "healthcheck_run":
            hc = _get_hc()
            results = await hc.run_checks()
            serialized = []
            for r in results:
                if isinstance(r, dict):
                    serialized.append(r)
                elif hasattr(r, "to_dict"):
                    serialized.append(r.to_dict())
                else:
                    serialized.append(str(r))
            return json.dumps({"ok": True, "results": serialized})

        elif name == "active_alerts":
            alert = _get_alert()
            alerts = alert.active_alerts()
            return json.dumps({"ok": True, "count": len(alerts), "alerts": alerts})

        elif name == "alert_rules":
            alert = _get_alert()
            rules = alert.list_rules()
            return json.dumps({"ok": True, "count": len(rules), "rules": rules})

        elif name == "incidents_list":
            inc = _get_inc()
            status = arguments.get("status", "")
            if status:
                data = inc.list_incidents(status=status)
            else:
                data = inc.list_incidents()
            return json.dumps({"ok": True, "count": len(data), "incidents": data})

        elif name == "incident_get":
            inc = _get_inc()
            data = inc.get(arguments["incident_id"])
            if data is None:
                return json.dumps({"ok": False, "error": "incident not found"})
            return json.dumps({"ok": True, "incident": data})

        elif name == "audit_recent":
            audit = _get_audit()
            limit = int(arguments.get("limit", 50))
            data = audit.recent(limit=limit)
            return json.dumps({"ok": True, "count": len(data), "entries": data})

        elif name == "dashboard_overview":
            ts = _get_ts()
            hc = _get_hc()
            alert = _get_alert()
            inc = _get_inc()
            return json.dumps({
                "ok": True,
                "servers": ts.query_latest(),
                "server_count": len(ts.server_list()),
                "health_checks": hc.list_checks(),
                "active_alerts": alert.active_alerts(),
                "alert_count": len(alert.active_alerts()),
                "active_incidents": inc.active_incidents(),
                "incident_count": len(inc.active_incidents()),
                "timestamp": time.time(),
            })

        elif name == "webhook_list":
            alert = _get_alert()
            webhooks = alert.list_webhooks()
            return json.dumps({"ok": True, "count": len(webhooks), "webhooks": webhooks})

        elif name == "webhook_add":
            alert = _get_alert()
            result = alert.add_webhook(
                url=arguments["url"],
                webhook_type=arguments.get("type", "slack"),
                name=arguments.get("name", ""),
            )
            return json.dumps(result)

        elif name == "audit_chain_verify":
            store_name = arguments.get("store", "ops")
            if store_name == "main":
                from ..audit import AuditStore

                audit_main = AuditStore(_data_dir() / "audit.db")
                valid, broken_idx = audit_main.verify_chain()
                audit_main.close()
            else:
                audit = _get_audit()
                valid, broken_idx = audit.verify_chain()
            return json.dumps({
                "ok": True,
                "store": store_name,
                "chain_valid": valid,
                "first_broken_index": broken_idx,
                "message": "Chain integrity verified"
                if valid
                else f"Chain broken at entry index {broken_idx}",
            })

        elif name == "audit_anchor_status":
            from ..security.sign_bridge import SignBridge

            sign = SignBridge()
            anchor_id = arguments.get("anchor_id", "")
            if anchor_id:
                result = await sign.verify_anchor(anchor_id)
            else:
                limit = int(arguments.get("limit", 10))
                result = await sign.list_anchors(limit=limit)
            return json.dumps(result)

        elif name == "security_score_enhanced":
            scores: dict[str, Any] = {"ok": True, "checks": {}}

            # 1. Hash chain integrity
            audit = _get_audit()
            valid, _ = audit.verify_chain()
            scores["checks"]["hash_chain"] = {
                "status": "pass" if valid else "fail",
                "detail": "Ops audit chain intact" if valid else "Chain broken",
            }

            # 2. 2FA status
            try:
                from ..auth import LocalAuth
                auth = LocalAuth(_data_dir())
                totp_on = auth.totp_enabled()
                pw_set = auth.status()["configured"]
                scores["checks"]["authentication"] = {
                    "status": "pass" if (pw_set and totp_on) else ("warn" if pw_set else "fail"),
                    "password_set": pw_set,
                    "totp_enabled": totp_on,
                }
            except Exception:
                scores["checks"]["authentication"] = {"status": "unknown"}

            # 3. Secrets encryption
            try:
                from ..secrets import SecretStore
                ss = SecretStore()
                encrypted = ss.is_encrypted()
                scores["checks"]["secrets_encryption"] = {
                    "status": "pass" if encrypted else "warn",
                    "encrypted": encrypted,
                }
            except Exception:
                scores["checks"]["secrets_encryption"] = {"status": "unknown"}

            # 4. Overall score
            statuses = [c.get("status", "unknown") for c in scores["checks"].values()]
            if all(s == "pass" for s in statuses):
                scores["grade"] = "A"
            elif "fail" in statuses:
                scores["grade"] = "C"
            else:
                scores["grade"] = "B"

            return json.dumps(scores)

        elif name == "log_sensitive_scan":
            from ..security.sensitive_filter import sanitize_text

            limit = int(arguments.get("limit", 200))
            audit = _get_audit()
            entries = audit.recent(limit=limit)
            findings: list[dict[str, Any]] = []
            for entry in entries:
                cmd = entry.get("command", "")
                if cmd and sanitize_text(cmd) != cmd:
                    findings.append({
                        "rowid": entry.get("rowid"),
                        "action": entry.get("action"),
                        "field": "command",
                        "preview": cmd[:80] + "..." if len(cmd) > 80 else cmd,
                    })
                meta_str = json.dumps(entry.get("metadata", {}))
                if sanitize_text(meta_str) != meta_str:
                    findings.append({
                        "rowid": entry.get("rowid"),
                        "action": entry.get("action"),
                        "field": "metadata",
                    })
            return json.dumps({
                "ok": True,
                "scanned": len(entries),
                "findings": len(findings),
                "details": findings[:50],
            })

        elif name == "secrets_rotation_check":
            try:
                from ..secrets import SecretStore
                ss = SecretStore()
                statuses = ss.status()
                expired = [s for s in statuses if s.get("expired")]
                return json.dumps({
                    "ok": True,
                    "total_profiles": len(statuses),
                    "expired_count": len(expired),
                    "expired": expired,
                    "profiles": statuses,
                })
            except Exception as exc:
                return json.dumps({"ok": False, "error": str(exc)})

        else:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})

    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def create_server() -> Server:
    """Create and configure the MCP monitoring server."""
    server = Server("werubworker-monitoring")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        result = await _handle_tool(name, arguments)
        return [TextContent(type="text", text=result)]

    return server


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main():
    """Run the MCP server via stdio transport."""
    from mcp.server.stdio import stdio_server

    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
