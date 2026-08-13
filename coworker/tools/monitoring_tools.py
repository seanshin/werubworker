"""Agent tools for the monitoring subsystem — metrics, health checks, alerts.

Exposes the monitoring/timeseries, monitoring/healthcheck, and monitoring/alerting
modules as agent-callable tools following the ``_attach`` / ``_meta`` / ``_schema``
pattern used by cloud_infra, db_mgmt, and other tool modules.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import aisuite as ai


# ---------------------------------------------------------------------------
# Schema helpers (same pattern as cloud_infra.py)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="monitoring",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["monitoring"],
        requires_approval=approval,
    )


def _schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _attach(
    fn: Callable[..., Any],
    schema: dict[str, Any],
    *,
    approval: bool = False,
    caps: list[str] | None = None,
) -> Callable[..., Any]:
    name = schema["function"]["name"]
    fn.__coworker_schema__ = schema
    fn.__aisuite_tool_metadata__ = _meta(name, approval=approval, capabilities=caps)
    fn.__doc__ = schema["function"]["description"]
    fn.__name__ = name
    return fn


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def monitoring_tools(context: Any = None) -> list:
    """Return monitoring tools: metrics query, health check management, alert management."""
    from ..monitoring.timeseries import TimeSeriesStore
    from ..monitoring.healthcheck import HealthCheckManager
    from ..monitoring.alerting import AlertEngine

    secrets = getattr(context, "secrets", None)
    data_dir = None

    # Resolve data_dir from context
    if hasattr(context, "wiki_store") and context.wiki_store is not None:
        # WikiStore._db is data_dir / "wiki.db" → parent is data_dir
        db_path = getattr(context.wiki_store, "_db", None)
        if db_path:
            data_dir = db_path.parent

    if data_dir is None:
        # Fallback: state directory
        from pathlib import Path
        data_dir = Path.home() / ".config" / "werubworker"

    # Lazy-init shared instances
    ts_store = TimeSeriesStore(data_dir)
    hc_manager = HealthCheckManager(data_dir)
    alert_engine = AlertEngine(data_dir)

    tools: list[Callable[..., Any]] = []

    # -- metrics_query -------------------------------------------------
    def metrics_query(
        server_id: str, range: str = "1h", metric: str = ""
    ) -> dict:
        """Query time-series metrics for a server."""
        import time as _time

        range_map = {
            "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200,
            "6h": 21600, "12h": 43200, "1d": 86400, "7d": 604800,
            "30d": 2592000, "90d": 7776000,
        }
        range_secs = range_map.get(range, 3600)
        now = int(_time.time())
        table = ts_store.auto_select_table(range_secs)
        rows = ts_store.query(server_id, now - range_secs, now, table=table)
        if metric and rows:
            rows = [
                {"ts": r["ts"], metric: r.get(metric) or r.get(f"{metric}_avg")}
                for r in rows
            ]
        return {"ok": True, "server_id": server_id, "table": table,
                "count": len(rows), "data": rows[:500]}

    _attach(
        metrics_query,
        _schema(
            "metrics_query",
            "Query time-series metrics for a server. Returns CPU, memory, disk, "
            "network, and load data points for the specified time range.",
            {
                "server_id": {"type": "string", "description": "Server identifier"},
                "range": {
                    "type": "string",
                    "description": "Time range: 15m, 30m, 1h, 2h, 6h, 12h, 1d, 7d, 30d, 90d",
                },
                "metric": {
                    "type": "string",
                    "description": "Filter to a single metric (cpu, memory, disk, load_1m)",
                },
            },
            ["server_id"],
        ),
    )
    tools.append(metrics_query)

    # -- metrics_latest ------------------------------------------------
    def metrics_latest(server_id: str = "") -> dict:
        """Get the latest metrics for all servers or a specific server."""
        rows = ts_store.query_latest(server_id or None)
        return {"ok": True, "count": len(rows), "servers": rows}

    _attach(
        metrics_latest,
        _schema(
            "metrics_latest",
            "Get the latest metrics for all servers (or a specific server). "
            "Returns cpu, memory, disk, network, load for each server.",
            {
                "server_id": {
                    "type": "string",
                    "description": "Server identifier (empty for all)",
                },
            },
            [],
        ),
    )
    tools.append(metrics_latest)

    # -- healthcheck_list ----------------------------------------------
    def healthcheck_list() -> dict:
        """List all configured health checks with their current status."""
        checks = hc_manager.list_checks(enabled_only=False)
        return {"ok": True, "count": len(checks), "checks": checks}

    _attach(
        healthcheck_list,
        _schema(
            "healthcheck_list",
            "List all configured health checks (HTTP, TCP, DNS, SSL, etc.).",
            {},
            [],
        ),
    )
    tools.append(healthcheck_list)

    # -- healthcheck_add -----------------------------------------------
    def healthcheck_add(
        name: str,
        type: str,
        target: str,
        interval_seconds: int = 60,
        timeout_seconds: int = 10,
    ) -> dict:
        """Add a new health check rule."""
        from ..monitoring.healthcheck import HealthCheckRule
        rule = HealthCheckRule(
            id="", name=name, type=type, target=target,
            interval_seconds=interval_seconds, timeout_seconds=timeout_seconds,
        )
        return hc_manager.add_check(rule)

    _attach(
        healthcheck_add,
        _schema(
            "healthcheck_add",
            "Add a health check (HTTP, TCP, DNS, ping, ssl_cert, docker, k8s_pod, process).",
            {
                "name": {"type": "string", "description": "Check name"},
                "type": {
                    "type": "string",
                    "description": "Check type: http, tcp, dns, ping, ssl_cert, docker, k8s_pod, process",
                },
                "target": {"type": "string", "description": "URL, host:port, domain, etc."},
                "interval_seconds": {"type": "integer", "description": "Check interval (default 60)"},
                "timeout_seconds": {"type": "integer", "description": "Timeout (default 10)"},
            },
            ["name", "type", "target"],
        ),
        approval=True,
    )
    tools.append(healthcheck_add)

    # -- healthcheck_history -------------------------------------------
    def healthcheck_history(check_id: str, hours: int = 24) -> dict:
        """Get health check result history."""
        results = hc_manager.get_history(check_id, hours=hours)
        uptime = hc_manager.uptime_percentage(check_id, days=max(1, hours // 24))
        return {"ok": True, "check_id": check_id,
                "uptime_pct": uptime, "count": len(results), "results": results[:200]}

    _attach(
        healthcheck_history,
        _schema(
            "healthcheck_history",
            "Get health check result history with uptime percentage.",
            {
                "check_id": {"type": "string", "description": "Health check ID"},
                "hours": {"type": "integer", "description": "Hours of history (default 24)"},
            },
            ["check_id"],
        ),
    )
    tools.append(healthcheck_history)

    # -- alert_rules ---------------------------------------------------
    def alert_rules() -> dict:
        """List all alert rules."""
        rules = alert_engine.list_rules()
        return {"ok": True, "count": len(rules), "rules": rules}

    _attach(
        alert_rules,
        _schema(
            "alert_rules",
            "List all configured alert rules with thresholds and channels.",
            {},
            [],
        ),
    )
    tools.append(alert_rules)

    # -- alert_add_rule ------------------------------------------------
    def alert_add_rule(
        name: str,
        metric: str,
        threshold: float,
        operator: str = ">",
        severity: str = "warning",
        server_id: str = "",
        channels: str = "",
    ) -> dict:
        """Add an alert rule."""
        from ..monitoring.alerting import AlertRule
        rule = AlertRule(
            id="", name=name, metric=metric, operator=operator,
            threshold=threshold, severity=severity, server_id=server_id,
            channels=[c.strip() for c in channels.split(",") if c.strip()],
        )
        return alert_engine.add_rule(rule)

    _attach(
        alert_add_rule,
        _schema(
            "alert_add_rule",
            "Add an alert rule. Fires when metric exceeds threshold.",
            {
                "name": {"type": "string", "description": "Rule name"},
                "metric": {"type": "string", "description": "Metric: cpu, memory, disk"},
                "threshold": {"type": "number", "description": "Threshold value"},
                "operator": {"type": "string", "description": "> < >= <= == (default >)"},
                "severity": {"type": "string", "description": "info, warning, critical"},
                "server_id": {"type": "string", "description": "Server ID (empty for all)"},
                "channels": {"type": "string", "description": "Comma-separated channels (slack:C01234)"},
            },
            ["name", "metric", "threshold"],
        ),
        approval=True,
    )
    tools.append(alert_add_rule)

    # -- active_alerts -------------------------------------------------
    def active_alerts() -> dict:
        """List currently firing and acknowledged alerts."""
        alerts = alert_engine.active_alerts()
        return {"ok": True, "count": len(alerts), "alerts": alerts}

    _attach(
        active_alerts,
        _schema(
            "active_alerts",
            "List currently firing and acknowledged alerts.",
            {},
            [],
        ),
    )
    tools.append(active_alerts)

    # -- alert_acknowledge ---------------------------------------------
    def alert_acknowledge(alert_id: str) -> dict:
        """Acknowledge an alert."""
        return alert_engine.acknowledge(alert_id)

    _attach(
        alert_acknowledge,
        _schema(
            "alert_acknowledge",
            "Acknowledge a firing alert (stops escalation).",
            {"alert_id": {"type": "string", "description": "Alert ID"}},
            ["alert_id"],
        ),
        approval=True,
    )
    tools.append(alert_acknowledge)

    # -- alert_resolve -------------------------------------------------
    def alert_resolve(alert_id: str) -> dict:
        """Manually resolve an alert."""
        return alert_engine.resolve(alert_id)

    _attach(
        alert_resolve,
        _schema(
            "alert_resolve",
            "Manually resolve an alert.",
            {"alert_id": {"type": "string", "description": "Alert ID"}},
            ["alert_id"],
        ),
        approval=True,
    )
    tools.append(alert_resolve)

    return tools
