"""MCP Server for WeruBWorker ITMS (IT Management System) integration.

Exposes a unified IT service management interface as an MCP server:
security scanning, backup/restore, workflow automation, batch operations,
anomaly detection, and postmortem generation — the full v2.3 toolset.

This complements the monitoring_server (metrics/alerts/incidents) with
operational management capabilities for CIO-level IT governance.

Usage:
    python -m coworker.mcp.itms_server

    # Or add to .mcp.json / Claude Desktop config:
    {
      "mcpServers": {
        "werubworker-itms": {
          "command": "/path/to/.venv/bin/python",
          "args": ["-m", "coworker.mcp.itms_server"]
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

_backup = None
_anomaly = None
_postmortem = None
_workflow = None
_batch = None
_secrets_store = None


def _get_secrets():
    global _secrets_store
    if _secrets_store is None:
        from ..secrets import SecretStore

        _secrets_store = SecretStore()
    return _secrets_store


def _get_backup():
    global _backup
    if _backup is None:
        from ..monitoring.backup import BackupManager

        _backup = BackupManager(_data_dir())
    return _backup


def _get_anomaly():
    global _anomaly
    if _anomaly is None:
        from ..monitoring.anomaly import AnomalyDetector
        from ..monitoring.timeseries import TimeSeriesStore

        ts = TimeSeriesStore(_data_dir())
        _anomaly = AnomalyDetector(ts)
    return _anomaly


def _get_postmortem():
    global _postmortem
    if _postmortem is None:
        from ..monitoring.postmortem import PostmortemGenerator
        from ..monitoring.incidents import IncidentManager
        from ..monitoring.timeseries import TimeSeriesStore
        from ..monitoring.alerting import AlertEngine

        _postmortem = PostmortemGenerator(
            IncidentManager(_data_dir()),
            TimeSeriesStore(_data_dir()),
            AlertEngine(_data_dir()),
        )
    return _postmortem


def _get_workflow():
    global _workflow
    if _workflow is None:
        from ..automation.workflow import WorkflowEngine

        _workflow = WorkflowEngine(_data_dir())
    return _workflow


def _get_batch():
    global _batch
    if _batch is None:
        from ..connectors.ssh.batch import BatchSSH

        _batch = BatchSSH(secrets=_get_secrets())
    return _batch


# ---------------------------------------------------------------------------
# Tool definitions — 15 ITMS tools
# ---------------------------------------------------------------------------

TOOLS = [
    # ── Security ──
    Tool(
        name="security_score",
        description="종합 보안 점수 산출 (SSL, 포트, 방화벽, 인증 로그 기반 A~D 등급).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "서버 ID (비어있으면 로컬)"},
            },
        },
    ),
    Tool(
        name="container_scan",
        description="컨테이너 이미지 취약점 스캔 (Trivy CLI 기반).",
        inputSchema={
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Docker 이미지명 (예: nginx:latest)"},
            },
            "required": ["image"],
        },
    ),
    Tool(
        name="dependency_audit",
        description="프로젝트 의존성 취약점 검사 (npm audit / pip-audit 자동 감지).",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "프로젝트 경로 (기본: .)"},
                "type": {"type": "string", "description": "감지 유형: auto, npm, pip"},
            },
        },
    ),
    Tool(
        name="firewall_check",
        description="방화벽 규칙 검증 (iptables/ufw/nftables).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "서버 ID (비어있으면 로컬)"},
            },
        },
    ),
    # ── Backup ──
    Tool(
        name="backup_create",
        description="WeruBWorker 데이터 백업 생성 (Wiki, 메트릭, 알림, 인시던트 등 8개 DB).",
        inputSchema={
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "백업 대상 (wiki, metrics, alerts, incidents 등). 비어있으면 전체.",
                },
            },
        },
    ),
    Tool(
        name="backup_list",
        description="백업 이력 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 건수 (기본 20)"},
            },
        },
    ),
    Tool(
        name="backup_restore",
        description="백업에서 데이터 복원.",
        inputSchema={
            "type": "object",
            "properties": {
                "backup_id": {"type": "string", "description": "백업 ID"},
            },
            "required": ["backup_id"],
        },
    ),
    # ── Anomaly Detection ──
    Tool(
        name="anomaly_detect",
        description="서버 메트릭 이상 탐지 (Z-score 기반).",
        inputSchema={
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "서버 ID (비어있으면 전체)"},
                "window": {"type": "integer", "description": "분석 윈도우 (분, 기본 60)"},
            },
        },
    ),
    # ── Postmortem ──
    Tool(
        name="postmortem_generate",
        description="인시던트 사후분석 보고서 생성 (타임라인 + 관련 알림 + 메트릭 기반).",
        inputSchema={
            "type": "object",
            "properties": {
                "incident_id": {"type": "string", "description": "인시던트 ID"},
            },
            "required": ["incident_id"],
        },
    ),
    # ── Workflow ──
    Tool(
        name="workflow_list",
        description="등록된 조건부 워크플로우 목록 조회.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="workflow_execute",
        description="워크플로우 실행 (조건부 if/then/else 분기 포함).",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string", "description": "워크플로우 ID"},
            },
            "required": ["workflow_id"],
        },
    ),
    # ── Batch SSH ──
    Tool(
        name="batch_execute",
        description="멀티 서버 일괄 SSH 명령 실행 (병렬 또는 롤링).",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "실행할 명령어"},
                "tag": {"type": "string", "description": "서버 태그 필터 (비어있으면 전체)"},
                "mode": {"type": "string", "description": "parallel 또는 rolling (기본 parallel)"},
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="batch_servers",
        description="등록된 SSH 서버 목록 및 태그 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "tag": {"type": "string", "description": "태그 필터 (비어있으면 전체)"},
            },
        },
    ),
    # ── Gitea ──
    Tool(
        name="gitea_repos",
        description="로컬 Gitea 리포지토리 목록 조회.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="gitea_webhook_events",
        description="최근 Gitea Webhook 이벤트 이력 조회.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 건수 (기본 30)"},
                "repo": {"type": "string", "description": "리포 필터 (비어있으면 전체)"},
            },
        },
    ),
]

# ---------------------------------------------------------------------------
# Tool handlers
# ---------------------------------------------------------------------------


async def _handle_tool(name: str, arguments: dict) -> str:
    """Dispatch a tool call and return the JSON result."""
    try:
        # ── Security ──
        if name == "security_score":
            from ..tools.security_scan import security_score

            result = security_score(
                server_id=arguments.get("server_id", ""),
                secrets=_get_secrets(),
            )
            return json.dumps(result)

        elif name == "container_scan":
            from ..tools.security_scan import container_scan

            result = container_scan(
                image=arguments["image"],
                secrets=_get_secrets(),
            )
            return json.dumps(result)

        elif name == "dependency_audit":
            from ..tools.security_scan import dependency_audit

            result = dependency_audit(
                project_path=arguments.get("path", "."),
                audit_type=arguments.get("type", "auto"),
            )
            return json.dumps(result)

        elif name == "firewall_check":
            from ..tools.security_scan import firewall_check

            result = firewall_check(
                server_id=arguments.get("server_id", ""),
                secrets=_get_secrets(),
            )
            return json.dumps(result)

        # ── Backup ──
        elif name == "backup_create":
            bm = _get_backup()
            targets = arguments.get("targets") or None
            result = bm.create_backup(targets)
            return json.dumps(result)

        elif name == "backup_list":
            bm = _get_backup()
            limit = int(arguments.get("limit", 20))
            backups = bm.list_backups(limit)
            return json.dumps({"ok": True, "count": len(backups), "backups": backups})

        elif name == "backup_restore":
            bm = _get_backup()
            result = bm.restore(arguments["backup_id"])
            return json.dumps(result)

        # ── Anomaly Detection ──
        elif name == "anomaly_detect":
            detector = _get_anomaly()
            sid = arguments.get("server_id", "")
            window = int(arguments.get("window", 60))
            if sid:
                anomalies = detector.detect(sid, window)
                data = [{"metric": a.metric, "value": a.value, "expected": a.expected,
                         "z_score": a.z_score, "severity": a.severity, "description": a.description}
                        for a in anomalies]
                return json.dumps({"ok": True, "server_id": sid, "count": len(data), "anomalies": data})
            else:
                all_results = detector.detect_all_servers()
                flat = []
                for s, anomalies in all_results.items():
                    for a in anomalies:
                        flat.append({"server_id": s, "metric": a.metric, "value": a.value,
                                     "expected": a.expected, "z_score": a.z_score, "severity": a.severity})
                return json.dumps({"ok": True, "count": len(flat), "anomalies": flat})

        # ── Postmortem ──
        elif name == "postmortem_generate":
            gen = _get_postmortem()
            report = await gen.generate(arguments["incident_id"])
            return json.dumps({
                "ok": True,
                "incident_id": report.incident_id,
                "title": report.title,
                "summary": report.summary,
                "markdown": report.full_markdown,
                "action_items": report.action_items,
            })

        # ── Workflow ──
        elif name == "workflow_list":
            wf = _get_workflow()
            workflows = wf.list_workflows()
            return json.dumps({"ok": True, "count": len(workflows), "workflows": workflows})

        elif name == "workflow_execute":
            wf = _get_workflow()
            result = await wf.execute(arguments["workflow_id"], context={"secrets": _get_secrets()})
            return json.dumps(result)

        # ── Batch SSH ──
        elif name == "batch_execute":
            batch = _get_batch()
            mode = arguments.get("mode", "parallel")
            tag = arguments.get("tag", "")
            cmd = arguments["command"]
            if mode == "rolling":
                result = await batch.execute_rolling(cmd, tag=tag)
            else:
                result = await batch.execute_parallel(cmd, tag=tag)
            return json.dumps({
                "ok": True, "total": result.total,
                "succeeded": result.succeeded, "failed": result.failed,
                "duration_ms": result.duration_ms,
                "results": result.results,
            })

        elif name == "batch_servers":
            batch = _get_batch()
            tag = arguments.get("tag", "")
            servers = batch.list_servers(tag=tag)
            tags = batch.list_tags()
            return json.dumps({"ok": True, "count": len(servers),
                               "servers": [{"server_id": s["server_id"], "host": s.get("host", ""),
                                            "label": s.get("label", ""), "tags": s.get("tags", [])}
                                           for s in servers],
                               "available_tags": tags})

        # ── Gitea ──
        elif name == "gitea_repos":
            import httpx

            try:
                resp = httpx.get("http://localhost:3000/api/v1/repos/search?limit=50",
                                 headers={"Authorization": "token " + (_get_secrets().get("gitea", {}).get("token", ""))},
                                 timeout=10)
                data = resp.json()
                repos = data.get("data", []) if isinstance(data, dict) else data
                return json.dumps({"ok": True, "count": len(repos),
                                   "repos": [{"name": r.get("full_name", ""), "description": r.get("description", ""),
                                              "html_url": r.get("html_url", ""), "stars": r.get("stars_count", 0),
                                              "updated": r.get("updated_at", "")} for r in repos[:20]]})
            except Exception as e:
                return json.dumps({"ok": False, "error": str(e)})

        elif name == "gitea_webhook_events":
            from ..connectors.gitea_webhook import GiteaWebhookHandler

            handler = GiteaWebhookHandler(_data_dir())
            events = handler.recent_events(
                limit=int(arguments.get("limit", 30)),
                repo=arguments.get("repo", ""),
            )
            return json.dumps({"ok": True, "count": len(events), "events": events})

        else:
            return json.dumps({"ok": False, "error": f"unknown tool: {name}"})

    except Exception as exc:
        log.exception("ITMS tool error: %s", name)
        return json.dumps({"ok": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Server setup
# ---------------------------------------------------------------------------


def create_server() -> Server:
    """Create and configure the MCP ITMS server."""
    server = Server("werubworker-itms")

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
    """Run the MCP ITMS server via stdio transport."""
    from mcp.server.stdio import stdio_server

    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
